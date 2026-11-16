"""Caché de respuestas completas para las consultas de Cusco entero.

Los datos son históricos y hay una sola región, así que una consulta de ``departamento=PE-CUS``
devuelve siempre lo mismo hasta que cambien los datos. Este middleware guarda la respuesta ya
comprimida la primera vez y la repite a los demás visitantes; si llegan 60 a la vez por la misma
consulta, solo la primera calcula y el resto espera esa respuesta (un candado por clave).

- **Qué entra:** ``GET /api/*`` sin área dibujada (``bbox``/``lat``/``lon``) y con estado 200.
  El CSV y las consultas de área pasan de largo y conservan sus límites.
- **Clave:** ruta + parámetros ordenados + si el cliente acepta gzip + versión de los datos
  (fecha de ``plan_meta.json``): al recargar datos, las respuestas viejas dejan de usarse.
- **Límites:** va por fuera del ``RateLimiter``, así que una respuesta repetida no gasta cupo:
  el límite por IP cuenta solo el trabajo real. Sin eso, una sala entera detrás de la misma IP
  pública se quedaba sin cupo (prueba de carga del 14-nov: 86 % de rechazos 429).
- **Memoria:** acotada por cantidad y por tamaño; se descarta lo que hace más tiempo no se usa.

Prueba de carga (60 personas, 1 núcleo): abrir la página pasa de no responder a ~0,1 s.
"""

from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable
from urllib.parse import parse_qsl

# tiempo-real cambia cada 15 min: tiene su propio refresco (firecal.nrt), no esta caché.
SKIP_PATHS = {"/api/hotspots.csv", "/api/tiempo-real"}
CUSTOM_AOI_PARAMS = {"bbox", "lat", "lon", "radio_km"}
# Cabeceras que describen a la solicitud original, no a la respuesta: no se repiten.
DROP_HEADERS = {b"x-process-time-ms", b"x-ratelimit-remaining"}
MAX_ITEM_BYTES = 8 * 1024 * 1024


class ResponseCacheStore:
    """Respuestas guardadas + contadores. Vive en ``app.state.cache`` (una por aplicación)."""

    def __init__(self, enabled: bool, max_items: int, max_bytes: int,
                 version: Callable[[], object | None]) -> None:
        self.enabled = enabled
        self.max_items = max_items
        self.max_bytes = max_bytes
        self.version = version
        self._items: OrderedDict[tuple, tuple[int, list, bytes]] = OrderedDict()
        self._locks: dict[tuple, asyncio.Lock] = {}
        self.bytes = 0
        self.hits = 0
        self.misses = 0

    def key(self, scope) -> tuple | None:
        """Clave de la solicitud, o ``None`` si no se guarda."""
        if not self.enabled or scope["type"] != "http" or scope["method"] != "GET":
            return None
        path = scope["path"]
        if not path.startswith("/api/") or path in SKIP_PATHS:
            return None
        query = sorted(parse_qsl(scope["query_string"].decode("latin-1"), keep_blank_values=True))
        if any(k in CUSTOM_AOI_PARAMS for k, _ in query):
            return None
        version = self.version()
        if version is None:                       # aún no hay datos: nada que guardar
            return None
        gzip = any(k == b"accept-encoding" and b"gzip" in v.lower() for k, v in scope["headers"])
        return (path, tuple(query), gzip, version)

    def get(self, key: tuple):
        hit = self._items.get(key)
        if hit is not None:
            self._items.move_to_end(key)
        return hit

    def put(self, key: tuple, status: int, headers: list, body: bytes) -> None:
        if status != 200 or len(body) > min(MAX_ITEM_BYTES, self.max_bytes):
            return
        headers = [(k, v) for k, v in headers if k.lower() not in DROP_HEADERS]
        self._items[key] = (status, headers, body)
        self.bytes += len(body)
        while len(self._items) > self.max_items or self.bytes > self.max_bytes:
            _, (_, _, old) = self._items.popitem(last=False)
            self.bytes -= len(old)

    def lock(self, key: tuple) -> asyncio.Lock:
        return self._locks.setdefault(key, asyncio.Lock())

    def forget_lock(self, key: tuple, lock: asyncio.Lock) -> None:
        if not lock.locked():
            self._locks.pop(key, None)

    def clear(self) -> None:
        self._items.clear()
        self.bytes = 0

    def stats(self) -> dict:
        return {"cache_activa": self.enabled, "cache_respuestas": len(self._items),
                "cache_mb": round(self.bytes / 1e6, 2), "cache_aciertos": self.hits,
                "cache_calculadas": self.misses}


class ResponseCacheMiddleware:
    """Middleware ASGI: responde desde ``ResponseCacheStore`` o calcula una sola vez por clave."""

    def __init__(self, app, store: ResponseCacheStore) -> None:
        self.app = app
        self.store = store

    async def __call__(self, scope, receive, send) -> None:
        store = self.store
        key = store.key(scope) if scope["type"] == "http" else None
        if key is None:
            await self.app(scope, receive, send)
            return
        t0 = time.perf_counter()
        lock = store.lock(key)
        try:
            async with lock:
                hit = store.get(key)
                from_cache = hit is not None
                if hit is None:
                    hit = await self._compute(scope, receive)
                    store.misses += 1
                    store.put(key, *hit)
                else:
                    store.hits += 1
        finally:
            store.forget_lock(key, lock)
        status, headers, body = hit
        if from_cache:
            headers = [*headers,
                       (b"x-process-time-ms", f"{(time.perf_counter() - t0) * 1000:.1f}".encode()),
                       (b"x-cache", b"HIT")]
        await send({"type": "http.response.start", "status": status, "headers": headers})
        await send({"type": "http.response.body", "body": body})

    async def _compute(self, scope, receive) -> tuple[int, list, bytes]:
        """Ejecuta la aplicación y junta la respuesta completa (ya comprimida si aplica)."""
        start: dict = {}
        chunks: list[bytes] = []

        async def capture(message) -> None:
            if message["type"] == "http.response.start":
                start.update(message)
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        await self.app(scope, receive, capture)
        return start.get("status", 500), list(start.get("headers", [])), b"".join(chunks)

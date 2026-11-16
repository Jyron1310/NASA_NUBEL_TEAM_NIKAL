"""Protocolo de solicitudes: límites por cliente y turnos para las consultas pesadas.

FastAPI ejecuta los endpoints síncronos en un *pool* de hilos (~40). Sin control, unos pocos
clientes pidiendo CSV grandes o AOI dibujados ocupan todos los hilos y la CPU, y la web deja de
responder. Este módulo pone tres barreras con primitivas de ``threading`` (sin dependencias nuevas):

1. ``RateLimiter``: **cubeta de fichas por cliente** (IP). Cada solicitud gasta una ficha; las
   fichas se recargan a ``requests_per_minute``. Hay una segunda cubeta, más chica, para las
   solicitudes pesadas. Sin fichas -> **429** con ``Retry-After``. Un ``threading.Lock`` protege
   el diccionario de clientes (lo usan varios hilos a la vez).
2. ``HeavyGate``: **semáforo** (``threading.BoundedSemaphore``) que deja correr como mucho
   ``max_concurrent_heavy`` consultas pesadas en todo el proceso. Las demás esperan su turno hasta
   ``queue_timeout_s``; si no lo consiguen -> **503** con ``Retry-After``. Así las consultas
   livianas (calendario de un departamento, ya en caché) siempre tienen hilos libres.
3. ``SingleFlight`` (``firecal.concurrency``): **un candado por clave**. Si llegan a la vez N
   solicitudes idénticas sin caché, solo la primera calcula y las demás reutilizan el resultado.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from firecal.concurrency import SingleFlight  # noqa: F401 - reexportado
from firecal.i18n import t
from firecal.settings import RateLimitParams

# Rutas pesadas siempre; /calendario y /anomalias solo si el AOI es dibujado (bbox o punto).
HEAVY_PATHS = {"/api/hotspots.csv"}
HEAVY_IF_CUSTOM_AOI = {"/api/calendario", "/api/anomalias", "/api/focos.geojson", "/api/resumen"}
HEAVY_PREFIX_IF_CUSTOM_AOI = "/api/analitica/"
IDLE_FORGET_S = 600.0


@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBuckets:
    """Cubetas de fichas por clave, seguras entre hilos."""

    def __init__(self, per_minute: float, capacity: int, max_keys: int,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.rate = per_minute / 60.0
        self.capacity = float(capacity)
        self.max_keys = max_keys
        self.clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def take(self, key: str, cost: float = 1.0) -> tuple[bool, float, int]:
        """Gasta ``cost`` fichas si hay. Devuelve (permitido, espera en s, fichas restantes)."""
        now = self.clock()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                if len(self._buckets) >= self.max_keys:
                    self._forget_idle(now)
                b = self._buckets[key] = _Bucket(self.capacity, now)
            b.tokens = min(self.capacity, b.tokens + (now - b.updated) * self.rate)
            b.updated = now
            if b.tokens >= cost:
                b.tokens -= cost
                return True, 0.0, int(b.tokens)
            return False, (cost - b.tokens) / self.rate, int(b.tokens)

    def _forget_idle(self, now: float) -> None:
        """Olvida clientes inactivos; si no alcanza, el más antiguo (memoria acotada)."""
        idle = [k for k, b in self._buckets.items() if now - b.updated > IDLE_FORGET_S]
        for k in idle:
            del self._buckets[k]
        if len(self._buckets) >= self.max_keys:
            oldest = min(self._buckets, key=lambda k: self._buckets[k].updated)
            del self._buckets[oldest]

    def __len__(self) -> int:
        with self._lock:
            return len(self._buckets)


class HeavyGate:
    """Semáforo de consultas pesadas con espera limitada y contadores para /health."""

    def __init__(self, max_concurrent: int, timeout_s: float, max_queue: int | None = None) -> None:
        self.max_concurrent = max_concurrent
        self.timeout_s = timeout_s
        # Cada pesada en espera ocupa un hilo del pool (~40). Con la fila llena se rechaza de
        # inmediato para que las consultas livianas siempre tengan hilos libres.
        self.max_queue = max_queue
        self._sem = threading.BoundedSemaphore(max_concurrent)
        self._lock = threading.Lock()
        self.active = 0
        self.waiting = 0
        self.rejected = 0

    def _busy(self) -> HTTPException:
        with self._lock:
            self.rejected += 1
        return HTTPException(
            status_code=503,
            detail=t(es="Servidor ocupado con otras descargas o consultas pesadas. "
                        "Intenta de nuevo en unos segundos.",
                     en="Server busy with other downloads or heavy queries. Try again in "
                        "a few seconds."),
            headers={"Retry-After": "5"})

    def acquire(self) -> None:
        """Pide un turno; 503 si la fila está llena o no hay uno libre dentro de ``timeout_s``."""
        if self._sem.acquire(blocking=False):            # turno libre: sin esperar
            with self._lock:
                self.active += 1
            return
        with self._lock:
            full = self.max_queue is not None and self.waiting >= self.max_queue
            if not full:
                self.waiting += 1
        if full:
            raise self._busy()
        try:
            got = self._sem.acquire(timeout=self.timeout_s)
        finally:
            with self._lock:
                self.waiting -= 1
        if not got:
            raise self._busy()
        with self._lock:
            self.active += 1

    def release(self) -> None:
        with self._lock:
            self.active -= 1
        self._sem.release()

    @contextmanager
    def turn(self) -> Iterator[None]:
        self.acquire()
        try:
            yield
        finally:
            self.release()

    def stats(self) -> dict:
        with self._lock:
            return {"pesadas_activas": self.active, "pesadas_en_espera": self.waiting,
                    "max_pesadas": self.max_concurrent, "rechazadas_503": self.rejected}


# ---------------------------------------------------------------------------------- middleware
def client_key(request: Request, trust_proxy: bool, proxy_hops: int = 1) -> str:
    """IP del cliente.

    Sin proxy: la IP de la conexión. Tras ``proxy_hops`` proxies de confianza (Azure, Cloud Run),
    cada proxy AGREGA al final de X-Forwarded-For la IP que lo contactó; por eso la IP real es la
    ``proxy_hops``-ésima contando desde la DERECHA. Las de la izquierda las puede inventar el
    cliente: usarlas permitiría saltarse el límite cambiando la cabecera en cada solicitud.
    """
    if trust_proxy:
        parts = [p.strip() for p in request.headers.get("x-forwarded-for", "").split(",")
                 if p.strip()]
        if parts:
            return parts[max(len(parts) - proxy_hops, 0)]
    return request.client.host if request.client else "desconocido"


def is_heavy(request: Request) -> bool:
    path = request.url.path
    if path in HEAVY_PATHS:
        return True
    q = request.query_params
    custom = "bbox" in q or "lat" in q
    return custom and (path in HEAVY_IF_CUSTOM_AOI or path.startswith(HEAVY_PREFIX_IF_CUSTOM_AOI))


class RateLimiter:
    """Aplica las dos cubetas (general y pesadas) a las rutas /api/*."""

    def __init__(self, params: RateLimitParams) -> None:
        self.params = params
        self.enabled = params.enabled
        env_trust = os.environ.get("FIRECAL_TRUST_PROXY") == "1"
        self.trust_proxy = params.trust_proxy_headers or env_trust
        # Cuántos proxies agregan IP al final de X-Forwarded-For. En Cloud Run es 1: llega
        # "<lo que mandó el cliente>, <IP real>" (comprobado en producción el 14-nov: con 2, las IP
        # inventadas creaban clientes nuevos). FIRECAL_PROXY_HOPS lo cambia sin reconstruir.
        self.proxy_hops = int(os.environ.get("FIRECAL_PROXY_HOPS") or params.proxy_hops)
        self.general = TokenBuckets(params.requests_per_minute, params.burst, params.max_clients)
        self.heavy = TokenBuckets(params.heavy_per_minute, params.heavy_burst, params.max_clients)
        self._lock = threading.Lock()
        self.rejected = 0

    def check(self, request: Request) -> JSONResponse | None:
        """None si pasa; si no, la respuesta 429 lista para devolver."""
        if not self.enabled or not request.url.path.startswith("/api/"):
            return None
        key = client_key(request, self.trust_proxy, self.proxy_hops)
        ok, wait, remaining = self.general.take(key)
        limit = self.params.burst
        if ok and is_heavy(request):
            ok, wait, _ = self.heavy.take(key)
            limit = self.params.heavy_burst
        if ok:
            request.state.rate_remaining = remaining
            return None
        with self._lock:
            self.rejected += 1
        retry = max(1, math.ceil(wait))
        return JSONResponse(
            status_code=429,
            content={"detail": t(es=f"Demasiadas solicitudes desde tu conexión. Espera "
                                    f"{retry} s y vuelve a intentar.",
                                 en=f"Too many requests from your connection. Wait {retry} s "
                                    "and try again.")},
            headers={"Retry-After": str(retry), "X-RateLimit-Limit": str(limit),
                     "X-RateLimit-Remaining": "0"},
            media_type="application/json; charset=utf-8")

    def stats(self) -> dict:
        with self._lock:
            return {"activo": self.enabled, "clientes": len(self.general),
                    "rechazadas_429": self.rejected}

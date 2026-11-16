"""Tests del protocolo de solicitudes (api/limits.py): cubetas, semáforo y candado por clave."""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

from api.limits import HeavyGate, TokenBuckets
from api.main import create_app
from firecal.concurrency import SingleFlight
from firecal.settings import ScientificParams, Settings


# ------------------------------------------------------------------ unidades
def test_token_bucket_burst_then_refill():
    now = [0.0]
    tb = TokenBuckets(per_minute=60, capacity=3, max_keys=10, clock=lambda: now[0])
    assert [tb.take("a")[0] for _ in range(4)] == [True, True, True, False]
    ok, wait, _ = tb.take("a")
    assert not ok and 0 < wait <= 1.0          # 60/min = 1 ficha por segundo
    assert tb.take("b")[0]                       # otro cliente tiene su propia cubeta
    now[0] += 1.0
    assert tb.take("a")[0]


def test_token_bucket_memory_is_bounded():
    now = [0.0]
    tb = TokenBuckets(per_minute=60, capacity=1, max_keys=5, clock=lambda: now[0])
    for i in range(50):
        now[0] += 1
        tb.take(f"ip{i}")
    assert len(tb) <= 5


def test_token_bucket_thread_safe():
    """Con 20 hilos peleando por 100 fichas, se conceden exactamente 100."""
    tb = TokenBuckets(per_minute=1e-6, capacity=100, max_keys=10)
    granted, lock = [], threading.Lock()

    def worker():
        n = sum(tb.take("x")[0] for _ in range(20))
        with lock:
            granted.append(n)

    threads = [threading.Thread(target=worker) for _ in range(20)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(granted) == 100


def test_heavy_gate_limits_concurrency():
    gate = HeavyGate(max_concurrent=2, timeout_s=5)
    peak, current, lock = [0], [0], threading.Lock()

    def job():
        with gate.turn():
            with lock:
                current[0] += 1
                peak[0] = max(peak[0], current[0])
            time.sleep(0.05)
            with lock:
                current[0] -= 1

    threads = [threading.Thread(target=job) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 2 and gate.stats()["pesadas_activas"] == 0


def test_heavy_gate_rejects_after_timeout():
    from fastapi import HTTPException

    gate = HeavyGate(max_concurrent=1, timeout_s=0.05)
    gate.acquire()
    with pytest.raises(HTTPException) as exc:
        gate.acquire()
    assert exc.value.status_code == 503 and exc.value.headers["Retry-After"]
    gate.release()
    assert gate.stats()["rechazadas_503"] == 1


def test_heavy_gate_rejects_at_once_when_queue_is_full():
    """Con la fila llena el 503 es inmediato: las pesadas en espera no agotan los hilos."""
    from fastapi import HTTPException

    gate = HeavyGate(max_concurrent=1, timeout_s=5, max_queue=1)
    gate.acquire()                                   # turno ocupado
    waiter = threading.Thread(target=lambda: (gate.acquire(), gate.release()))
    waiter.start()
    for _ in range(100):                             # espera a que el hilo entre en la fila
        if gate.stats()["pesadas_en_espera"] == 1:
            break
        time.sleep(0.01)
    t0 = time.perf_counter()
    with pytest.raises(HTTPException) as exc:
        gate.acquire()                               # fila llena: no espera los 5 s
    assert exc.value.status_code == 503 and time.perf_counter() - t0 < 1
    gate.release()
    waiter.join()
    assert gate.stats() == {"pesadas_activas": 0, "pesadas_en_espera": 0, "max_pesadas": 1,
                            "rechazadas_503": 1}


def test_single_flight_computes_once():
    sf, cache, calls, lock = SingleFlight(), {}, [0], threading.Lock()

    def compute():
        with lock:
            calls[0] += 1
        time.sleep(0.1)
        cache["k"] = 42
        return 42

    results = []
    threads = [threading.Thread(target=lambda: results.append(sf.run("k", lambda: cache.get("k"),
                                                                     compute)))
               for _ in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert calls[0] == 1 and results == [42] * 10


# ------------------------------------------------------------------ integración con la API
def _settings_with_limits(base: Settings, **overrides) -> Settings:
    """Límites activos y caché de respuestas apagada: aquí se prueba el límite solo (con la caché,
    una consulta repetida no gasta cupo; eso se prueba en test_cache.py)."""
    raw = base.params.model_dump()
    raw["api"]["response_cache"]["enabled"] = False
    raw["api"]["rate_limit"].update({"enabled": True, **overrides})
    return Settings(env=base.env, params=ScientificParams.model_validate(raw), paths=base.paths)


def test_api_returns_429_with_retry_after(plan_home):
    s = _settings_with_limits(plan_home.settings, burst=3, requests_per_minute=1)
    api = TestClient(create_app(s))
    codes = [api.get("/api/departamentos").status_code for _ in range(5)]
    assert codes[:3] == [200, 200, 200] and codes[3:] == [429, 429]
    r = api.get("/api/departamentos")
    assert int(r.headers["Retry-After"]) >= 1 and "Demasiadas solicitudes" in r.json()["detail"]
    # /health y la web no cuentan para el límite.
    assert api.get("/health").status_code == 200
    assert api.get("/").status_code in (200, 404)     # 404 si la interfaz no está compilada
    assert api.get("/health/limits").json()["rechazadas_429"] >= 3


def test_api_heavy_bucket_is_separate(plan_home):
    s = _settings_with_limits(plan_home.settings, heavy_burst=1, heavy_per_minute=1)
    api = TestClient(create_app(s))
    q = {"bbox": "-72.6,-13.8,-71.8,-13.2"}
    assert api.get("/api/calendario", params=q).status_code == 200
    assert api.get("/api/calendario", params=q).status_code == 429       # pesada: sin fichas
    assert api.get("/api/calendario", params={"departamento": "PE-CUS"}).status_code == 200


def test_api_trusts_forwarded_for_only_when_enabled(plan_home):
    s = _settings_with_limits(plan_home.settings, burst=1, requests_per_minute=1,
                              trust_proxy_headers=True)
    api = TestClient(create_app(s))
    # El proxy agrega la IP real al final; lo de la izquierda lo controla el cliente.
    a = {"X-Forwarded-For": "203.0.113.1"}
    spoof = {"X-Forwarded-For": "1.2.3.4, 203.0.113.1"}
    b = {"X-Forwarded-For": "203.0.113.2"}
    assert api.get("/api/departamentos", headers=a).status_code == 200
    assert api.get("/api/departamentos", headers=spoof).status_code == 429  # inventar no sirve
    assert api.get("/api/departamentos", headers=b).status_code == 200      # otra IP real
    # Sin confianza en el proxy la cabecera se ignora: todas son el mismo cliente.
    s2 = _settings_with_limits(plan_home.settings, burst=1, requests_per_minute=1)
    api2 = TestClient(create_app(s2))
    assert api2.get("/api/departamentos", headers=a).status_code == 200
    assert api2.get("/api/departamentos", headers=b).status_code == 429


def test_api_gate_returns_503_when_busy(plan_home):
    s = _settings_with_limits(plan_home.settings, max_concurrent_heavy=1, queue_timeout_s=0.05)
    app = create_app(s)
    api = TestClient(app)
    app.state.gate.acquire()                     # simula una descarga larga en curso
    try:
        r = api.get("/api/hotspots.csv", params={"departamento": "PE-CUS",
                                                 "fecha_inicio": "2020-01", "fecha_fin": "2020-01"})
        assert r.status_code == 503 and "ocupado" in r.json()["detail"]
        # Las livianas siguen respondiendo.
        assert api.get("/api/calendario", params={"departamento": "PE-CUS"}).status_code == 200
    finally:
        app.state.gate.release()
    r = api.get("/api/hotspots.csv", params={"departamento": "PE-CUS",
                                             "fecha_inicio": "2020-01", "fecha_fin": "2020-01"})
    assert r.status_code == 200
    assert app.state.gate.stats()["pesadas_activas"] == 0   # el turno se liberó al terminar el CSV


def test_csv_releases_turn_before_sending(plan_home):
    """El turno cubre la consulta, no el envío: una descarga lenta no retiene el carril."""
    import asyncio

    s = _settings_with_limits(plan_home.settings, max_concurrent_heavy=1, queue_timeout_s=0.05)
    app = create_app(s)
    activas_al_enviar, filas, first = [], [0], [True]

    async def receive():
        if first[0]:
            first[0] = False
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()                 # el cliente sigue conectado

    async def send(message):
        if message["type"] == "http.response.body" and message.get("body"):
            # Mientras el CSV todavía se está enviando, ¿sigue ocupado el turno?
            activas_al_enviar.append(app.state.gate.stats()["pesadas_activas"])
            filas[0] += message["body"].count(b"\n")

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
             "scheme": "http", "path": "/api/hotspots.csv", "raw_path": b"/api/hotspots.csv",
             "root_path": "", "headers": [], "client": ("127.0.0.1", 50000),
             "server": ("testserver", 80),
             "query_string": b"departamento=PE-CUS&fecha_inicio=2020-01&fecha_fin=2020-12"}
    asyncio.run(app(scope, receive, send))
    assert filas[0] - 1 == 7295                      # cabecera + los focos de 2020
    assert activas_al_enviar and set(activas_al_enviar) == {0}


def test_csv_row_cap(plan_home):
    raw = plan_home.settings.params.model_dump()
    raw["api"]["max_csv_rows"] = 10
    s = Settings(env=plan_home.settings.env, params=ScientificParams.model_validate(raw),
                 paths=plan_home.settings.paths)
    app = create_app(s)
    r = TestClient(app).get("/api/hotspots.csv", params={
        "departamento": "PE-CUS", "fecha_inicio": "2020-08", "fecha_fin": "2020-09"})
    assert r.status_code == 422 and "máximo es 10" in r.json()["detail"]
    assert app.state.gate.stats()["pesadas_activas"] == 0   # el error también libera el turno


def test_proxy_hops_from_env(plan_home, monkeypatch):
    """FIRECAL_PROXY_HOPS=2: detrás de 2 proxies el visitante queda penúltimo en X-Forwarded-For.
    (Cloud Run usa 1, el valor por defecto: '<lo que mandó el cliente>, <IP real>'.)"""
    monkeypatch.setenv("FIRECAL_TRUST_PROXY", "1")
    monkeypatch.setenv("FIRECAL_PROXY_HOPS", "2")
    s = _settings_with_limits(plan_home.settings, burst=1, requests_per_minute=1)
    api = TestClient(create_app(s))
    lb = "169.254.1.1"                               # IP del segundo proxy, igual para todos
    a = {"X-Forwarded-For": f"203.0.113.1, {lb}"}
    b = {"X-Forwarded-For": f"203.0.113.2, {lb}"}
    spoof = {"X-Forwarded-For": f"1.2.3.4, 203.0.113.1, {lb}"}
    assert api.get("/api/departamentos", headers=a).status_code == 200
    assert api.get("/api/departamentos", headers=b).status_code == 200   # otro visitante: su cupo
    assert api.get("/api/departamentos", headers=spoof).status_code == 429  # inventar no sirve


def test_gzip_and_cache_headers(plan_home):
    """Mejora 4 de la auditoría: compresión y caché (datos históricos)."""
    api = TestClient(create_app(plan_home.settings))
    r = api.get("/api/focos.geojson", params={"departamento": "PE-CUS", "fecha_inicio": "2020-01",
                                              "fecha_fin": "2020-12"},
                headers={"Accept-Encoding": "gzip"})
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    assert r.headers["cache-control"] == "public, max-age=3600"
    assert api.get("/health").headers["cache-control"] == "no-store"
    err = api.get("/api/calendario", params={"departamento": "PE-PUN"})
    assert err.status_code == 404 and err.headers["cache-control"] == "no-store"


def test_custom_aoi_analytics_count_as_heavy():
    """Auditoría: focos.geojson, resumen y analíticas con área dibujada son pesadas."""
    from starlette.requests import Request

    from api.limits import is_heavy

    def req(path, qs):
        return Request({"type": "http", "path": path, "query_string": qs.encode(), "headers": []})

    assert is_heavy(req("/api/focos.geojson", "bbox=1,2,3,4"))
    assert is_heavy(req("/api/analitica/ranking", "lat=1&lon=2&radio_km=3"))
    assert is_heavy(req("/api/resumen", "bbox=1,2,3,4"))
    assert not is_heavy(req("/api/resumen", "departamento=PE-CUS"))

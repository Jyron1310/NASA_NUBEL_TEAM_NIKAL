"""Tests de la caché de respuestas (api/cache.py) y de la carga de datos en memoria.

Origen: prueba de carga del 14-nov (docs/team/AUDITORIA.md §10). Con 60 personas a la vez no
respondía; con los datos en tablas en memoria y esta caché, abre en ~0,1 s.
"""

from __future__ import annotations

import os

from fastapi.testclient import TestClient

from api.main import create_app
from firecal.plan.events import meta_path
from firecal.settings import ScientificParams, Settings

CUS = {"departamento": "PE-CUS"}
BBOX = {"bbox": "-72.6,-13.8,-71.8,-13.2"}


def _settings(base: Settings, cache: dict | None = None, limits: dict | None = None) -> Settings:
    raw = base.params.model_dump()
    raw["api"]["response_cache"].update(cache or {})
    raw["api"]["rate_limit"].update(limits or {})
    return Settings(env=base.env, params=ScientificParams.model_validate(raw), paths=base.paths)


def test_repeated_query_is_served_from_cache(plan_home):
    app = create_app(plan_home.settings)
    api = TestClient(app)
    a = api.get("/api/calendario", params=CUS)
    b = api.get("/api/calendario", params=CUS)
    assert a.status_code == b.status_code == 200
    assert "x-cache" not in a.headers and b.headers["x-cache"] == "HIT"
    assert b.content == a.content                              # la misma respuesta, byte a byte
    assert b.headers["cache-control"] == "public, max-age=3600"
    assert b.json()["total_focos_armonizados"] == 15818.39     # METHODOLOGY.md (v1.3)
    st = api.get("/health/limits").json()
    assert st["cache_aciertos"] == 1 and st["cache_calculadas"] == 1 and st["cache_respuestas"] == 1


def test_cache_key_ignores_parameter_order_but_not_values(plan_home):
    api = TestClient(create_app(plan_home.settings))
    api.get("/api/focos.geojson?departamento=PE-CUS&fecha_inicio=2020-08&fecha_fin=2020-08")
    same = api.get("/api/focos.geojson?fecha_fin=2020-08&fecha_inicio=2020-08&departamento=PE-CUS")
    other = api.get("/api/focos.geojson?departamento=PE-CUS&fecha_inicio=2020-09&fecha_fin=2020-09")
    assert same.headers.get("x-cache") == "HIT" and "x-cache" not in other.headers
    assert same.json()["n_focos"] == 2984 and other.json()["n_focos"] != 2984


def test_each_language_has_its_own_entry(plan_home):
    api = TestClient(create_app(plan_home.settings))
    es = api.get("/api/resumen", params={**CUS, "lang": "es"})
    en = api.get("/api/resumen", params={**CUS, "lang": "en"})
    assert "x-cache" not in en.headers                         # otro idioma: no se mezcla
    assert es.json()["titulo"] != en.json()["titulo"]
    again = api.get("/api/resumen", params={**CUS, "lang": "en"})
    assert again.headers["x-cache"] == "HIT" and again.json()["titulo"] == en.json()["titulo"]


def test_gzip_and_plain_clients_get_their_own_copy(plan_home):
    api = TestClient(create_app(plan_home.settings))
    q = {**CUS, "fecha_inicio": "2020-01", "fecha_fin": "2020-12"}
    gz = api.get("/api/focos.geojson", params=q, headers={"Accept-Encoding": "gzip"})
    plain = api.get("/api/focos.geojson", params=q, headers={"Accept-Encoding": "identity"})
    assert gz.headers["content-encoding"] == "gzip" and "content-encoding" not in plain.headers
    assert "x-cache" not in plain.headers                      # no se le sirve la copia en gzip
    assert plain.json()["features"] == gz.json()["features"]
    gz2 = api.get("/api/focos.geojson", params=q, headers={"Accept-Encoding": "gzip"})
    assert gz2.headers["x-cache"] == "HIT" and gz2.headers["content-encoding"] == "gzip"
    assert gz2.json()["n_focos"] == 7295


def test_drawn_areas_csv_and_errors_are_not_cached(plan_home):
    app = create_app(plan_home.settings)
    api = TestClient(app)
    csv_q = {**CUS, "fecha_inicio": "2020-08", "fecha_fin": "2020-08"}
    for path, q in (("/api/calendario", BBOX), ("/api/hotspots.csv", csv_q),
                    ("/api/calendario", {"departamento": "PE-PUN"}),          # 404 sin datos
                    ("/api/calendario", {"departmento": "PE-CUS"}),           # 422 mal escrito
                    ("/health", {})):
        first, second = api.get(path, params=q), api.get(path, params=q)
        assert first.status_code == second.status_code
        assert "x-cache" not in second.headers, path
    assert app.state.cache.stats()["cache_respuestas"] == 0


def test_cached_answers_do_not_spend_the_ip_quota(plan_home):
    """Una sala entera sale por la misma IP: lo repetido no gasta cupo, lo nuevo sí."""
    s = _settings(plan_home.settings,
                  limits={"enabled": True, "burst": 2, "requests_per_minute": 1})
    api = TestClient(create_app(s))
    codes = [api.get("/api/calendario", params=CUS).status_code for _ in range(30)]
    assert codes == [200] * 30                                 # 1 calculada + 29 desde la caché
    assert api.get("/api/metadatos").status_code == 200        # 2.ª consulta nueva: última ficha
    r = api.get("/api/departamentos")                          # 3.ª consulta nueva: sin fichas
    assert r.status_code == 429 and "Retry-After" in r.headers
    assert api.get("/api/departamentos").status_code == 429    # el 429 no se guardó
    assert api.get("/api/calendario", params=CUS).status_code == 200   # lo guardado sigue saliendo


def test_cache_can_be_disabled(plan_home):
    app = create_app(_settings(plan_home.settings, cache={"enabled": False}))
    api = TestClient(app)
    api.get("/api/calendario", params=CUS)
    assert "x-cache" not in api.get("/api/calendario", params=CUS).headers
    assert app.state.cache.stats()["cache_activa"] is False


def test_cache_memory_is_bounded(plan_home):
    app = create_app(_settings(plan_home.settings, cache={"max_items": 3}))
    api = TestClient(app)
    for m in range(1, 9):
        api.get("/api/anomalias", params={**CUS, "mes": f"2020-{m:02d}"})
    assert app.state.cache.stats()["cache_respuestas"] == 3
    # Quedan los 3 más recientes; el más antiguo se descartó y se vuelve a calcular.
    assert api.get("/api/anomalias", params={**CUS, "mes": "2020-08"}).headers["x-cache"] == "HIT"
    assert "x-cache" not in api.get("/api/anomalias", params={**CUS, "mes": "2020-01"}).headers


def test_new_data_invalidates_the_cache(plan_home):
    app = create_app(plan_home.settings)
    api = TestClient(app)
    api.get("/api/metadatos")
    assert api.get("/api/metadatos").headers["x-cache"] == "HIT"
    meta = meta_path(plan_home.settings)
    st = meta.stat()
    try:
        os.utime(meta, (st.st_atime, st.st_mtime + 5))        # como si se recargaran los datos
        assert "x-cache" not in api.get("/api/metadatos").headers
    finally:
        os.utime(meta, (st.st_atime, st.st_mtime))


def test_simultaneous_identical_queries_compute_once(plan_home):
    """60 personas piden lo mismo a la vez: una calcula, las demás reciben esa respuesta."""
    import asyncio

    import httpx

    app = create_app(plan_home.settings)
    q = {**CUS, "fecha_inicio": "2019-01", "fecha_fin": "2019-12"}

    async def visitas():
        # Un solo bucle de eventos, como uvicorn en producción.
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            return await asyncio.gather(*(c.get("/api/focos.geojson", params=q)
                                          for _ in range(60)))

    rs = asyncio.run(visitas())
    assert {r.status_code for r in rs} == {200}
    assert len({r.content for r in rs}) == 1                   # todas reciben la misma respuesta
    st = app.state.cache.stats()
    assert st["cache_calculadas"] == 1 and st["cache_aciertos"] == 59


def test_data_is_loaded_in_memory_tables(plan_home):
    """Tablas en memoria (no vistas sobre ~560 Parquet): la consulta no vuelve a tocar el disco."""
    from firecal.plan.query import PlanStore

    store = PlanStore(plan_home.settings)
    cur = store.cursor()
    kinds = dict(cur.execute("SELECT table_name, table_type FROM information_schema.tables "
                             "WHERE table_name IN ('cd', 'fo')").fetchall())
    n_cd = cur.execute("SELECT count(*) FROM cd").fetchall()[0][0]
    n_fo = cur.execute("SELECT count(*) FROM fo").fetchall()[0][0]
    cur.close()
    assert kinds == {"cd": "BASE TABLE", "fo": "BASE TABLE"}
    assert (n_cd, n_fo) == (36568, 59211)                      # METHODOLOGY.md §14 (v1.3)

"""Tests con los datos reales de Cusco (METHODOLOGY.md, casos de prueba de §12)."""

from __future__ import annotations

import csv
import io

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from firecal.plan.query import category, color_breaks, month_quality
from firecal.plan.sources import COLS_FOCOS, CONTROL


def _csv_rows(resp) -> list[dict]:
    return list(csv.DictReader(io.StringIO(resp.content.decode("utf-8-sig"))))


# ------------------------------------------------------------------ unidades
def test_month_quality_follows_contract():
    # Sin focos: por fecha.
    assert month_quality(2001, 5) == ("extrapolado", "Terra*kT")
    assert month_quality(2002, 7) == ("referencia", "MODIS")
    assert month_quality(2012, 12) == ("referencia", "MODIS")
    assert month_quality(2013, 1) == ("calibrado", "VIIRS*k")
    # Con focos: manda la fracción extrapolada de los datos.
    assert month_quality(2002, 6, 1.0) == ("extrapolado", "Terra*kT")
    assert month_quality(2002, 7, 0.0) == ("referencia", "MODIS")
    assert month_quality(2002, 7, 0.4) == ("mixto", "Terra*kT + MODIS")


def test_color_breaks_quantiles_and_category():
    assert color_breaks([0, 0, None]) == []
    b = color_breaks([float(x) for x in range(1, 101)])
    assert b == sorted(b) and len(b) == 4 and b[0] in (50, 51) and b[-1] in (99, 100)
    assert category(None) is None and category(0.0) == "normal" and category(2) == "muy por encima"


# ------------------------------------------------------------------ carga y contrato
def test_load_matches_maestro_controls(plan_home):
    c = plan_home.meta["controles"]
    for name in ("celda_dia", "focos"):
        assert c[name]["coincide_maestro"], c[name]["problemas"]
        assert c[name]["filas"] == CONTROL[name]["filas"]
        assert c[name]["sha256"] == CONTROL[name]["sha256"]
    f = plan_home.meta["factores"]
    assert f["VIIRS*k|alto"] == 0.33 and f["VIIRS*k|bajo"] == 0.247
    assert f["Terra*kT|alto"] == 2.619 and f["MODIS|bajo"] == 1.0


def test_contract_change_is_detected(plan_home, monkeypatch):
    from firecal.plan import events

    monkeypatch.setitem(events.CONTROL, "focos", {**CONTROL["focos"], "filas": 1})
    with pytest.raises(events.DataContractError, match="filas"):
        events.read_sources(strict=True)


# ------------------------------------------------------------------ API
@pytest.fixture(scope="module")
def api(plan_home) -> TestClient:
    return TestClient(create_app(plan_home.settings))


def _cal(api, **params):
    r = api.get("/api/calendario", params={"departamento": "PE-CUS", **params})
    assert r.status_code == 200, r.text
    return r.json()


def test_health_and_departamentos(api):
    assert api.get("/health").json() == {"status": "ok", "data_mode": "real", "data_ready": True}
    b = api.get("/api/departamentos").json()
    assert [d["code"] for d in b["departamentos"]] == ["PE-CUS"]
    assert b["geojson"]["features"][0]["geometry"]["type"] == "MultiPolygon"


def test_maestro_case_whole_period(api):
    b = _cal(api)
    assert abs(b["total_focos_armonizados"] - 15818) <= 1
    assert sum(c.get("celdas_dia", 0) for c in b["celdas"]) == 36568
    assert b["fecha_inicio"] == "2000-11" and b["fecha_fin"] == "2025-12"
    assert b["unidad"]["nombre"] == "Focos armonizados"
    assert "eq_hotspots" not in b["celdas"][5]          # el campo de la API es focos_armonizados


@pytest.mark.parametrize(("year", "expected"), [(2005, 1355), (2012, 678), (2013, 424),
                                                (2020, 1206), (2022, 850), (2024, 640),
                                                (2025, 387)])
def test_maestro_cases_by_year(api, year, expected):
    b = _cal(api, fecha_inicio=f"{year}-01", fecha_fin=f"{year}-12")
    assert abs(b["total_focos_armonizados"] - expected) <= 1


@pytest.mark.parametrize("params", [
    {"departamento": "PE-CUS", "fecha_inicio": "1999-01", "fecha_fin": "2000-10"},
    {"departamento": "PE-PUN"},
    {"bbox": "-80,-5,-79.5,-4.5"},
    {"lat": -5.0, "lon": -80.0, "radio_km": 10},
])
def test_maestro_sin_datos_not_zero(api, params):
    r = api.get("/api/calendario", params=params)
    assert r.status_code == 404 and "Sin datos" in r.json()["detail"]


def test_months_outside_coverage_are_sin_dato(api):
    b = _cal(api, fecha_inicio="2000-01", fecha_fin="2001-12")
    by = {(c["anio"], c["mes"]): c for c in b["celdas"]}
    assert by[(2000, 10)]["sin_dato"] and "focos_armonizados" not in by[(2000, 10)]
    assert not by[(2000, 11)]["sin_dato"] and by[(2000, 11)]["parcial"]
    assert by[(2001, 1)]["calidad"] == "extrapolado"
    assert b["matriz_focos_armonizados"][0][9] is None                     # 2000-10: null, no 0
    assert any("extrapolado" in n for n in b["notes"])


def test_no_frp_and_no_eventos_in_api(api):
    text = api.get("/api/calendario", params={"departamento": "PE-CUS"}).text.lower()
    assert "frp" not in text and "evento" not in text


def test_download_whole_period_contract(api):
    r = api.get("/api/hotspots.csv", params={"departamento": "PE-CUS", "fecha_inicio": "2000-11",
                                             "fecha_fin": "2025-12"})
    assert r.status_code == 200 and r.content.startswith(b"\xef\xbb\xbf")
    rows = _csv_rows(r)
    assert list(rows[0].keys()) == COLS_FOCOS                        # 18 columnas, mismo orden
    assert len(rows) == 59211 and r.headers["X-Row-Count"] == "59211"
    assert abs(sum(float(x["eq_foco"]) for x in rows) - 15818.36) < 0.05
    assert all(len(x["hora_utc"]) == 4 for x in rows)                # texto con ceros a la izq.
    assert "cusco_2000-11_2025-12" in r.headers["Content-Disposition"]


@pytest.mark.parametrize("aoi", [
    {"departamento": "PE-CUS"},
    {"bbox": "-72.6,-13.8,-71.8,-13.2"},
    {"lat": -13.52, "lon": -71.97, "radio_km": 40},
])
def test_screen_total_equals_download_sum(api, aoi):
    """METHODOLOGY.md: Σ eq_foco de la descarga = total mostrado en pantalla."""
    q = {**aoi, "fecha_inicio": "2019-01", "fecha_fin": "2021-12"}
    cal = api.get("/api/calendario", params=q).json()
    rows = _csv_rows(api.get("/api/hotspots.csv", params=q))
    assert abs(sum(float(x["eq_foco"]) for x in rows) - cal["total_focos_armonizados"]) <= 1


def test_anomalias_with_daily_detail(api):
    b = api.get("/api/anomalias", params={"departamento": "PE-CUS", "mes": "2020-09"}).json()
    assert b["calidad"] == "calibrado" and b["mediana_hist"] is not None
    assert abs(sum(d["focos_armonizados"] for d in b["dias"]) - b["focos_armonizados"]) < 0.05
    assert len(b["historial"]) >= 20
    vals = sorted(h["focos_armonizados"] for h in b["historial"])
    assert b["mediana_hist"] == pytest.approx(vals[len(vals) // 2] if len(vals) % 2 else
                                              (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2,
                                              abs=0.01)
    r = api.get("/api/anomalias", params={"departamento": "PE-CUS", "mes": "2026-01"})
    assert r.status_code == 404


@pytest.mark.parametrize(("params", "status", "text"), [
    ({}, 422, "AOI vacío"),
    ({"departamento": "PE-CUS", "fecha_inicio": "2020-05", "fecha_fin": "2019-01"}, 422,
     "Rango invertido"),
    ({"departamento": "PE-CUS", "fecha_inicio": "2020-13"}, 422, "AAAA-MM"),
    ({"bbox": "-80,-20,-60,0"}, 422, "Área demasiado grande"),
    ({"departamento": "PE-CUS", "bbox": "-72,-14,-71,-13"}, 422, "un solo tipo"),
])
def test_calendario_errors(api, params, status, text):
    r = api.get("/api/calendario", params=params)
    assert r.status_code == status, r.text
    assert text in r.json()["detail"]


def test_legacy_v1_retired(api):
    assert api.post("/api/v1/calendar", json={}).status_code in (404, 405)
    assert "/api/v1/calendar" not in api.get("/openapi.json").json()["paths"]


def test_metadatos(api):
    b = api.get("/api/metadatos").json()
    assert b["unidad"]["nombre"] == "Focos armonizados"
    assert all(v["coincide"] for v in b["controles_maestro"].values())
    assert any("FIRMS" in c for c in b["creditos"])
    assert b["armonizacion"]["serie"][2]["k"] == {"alto": 0.33, "bajo": 0.247}


def test_frontend_served(api):
    from api.main import DEFAULT_FRONTEND

    if not (DEFAULT_FRONTEND / "index.html").is_file():
        pytest.skip("frontend sin compilar: cd frontend && npm run build")
    r = api.get("/")
    assert r.status_code == 200 and "Nikal Cusco" in r.text


def test_quality_comes_from_data(api):
    """Julio de 2002: sus focos (19 al 27) ya son Terra + Aqua -> referencia, no extrapolado."""
    b = _cal(api, fecha_inicio="2002-05", fecha_fin="2002-08")
    by = {(c["anio"], c["mes"]): c for c in b["celdas"]}
    assert by[(2002, 6)]["calidad"] == "extrapolado" and by[(2002, 6)]["fraccion_extrapolada"] == 1
    assert by[(2002, 7)]["calidad"] == "referencia" and by[(2002, 7)]["fraccion_extrapolada"] == 0
    assert by[(2002, 8)]["calidad"] == "referencia"


def test_departamentos_geojson(api):
    b = api.get("/api/departamentos.geojson").json()
    assert b["type"] == "FeatureCollection" and b["features"][0]["properties"]["code"] == "PE-CUS"


def test_cors_extra_origins_from_env(plan_home, monkeypatch):
    from firecal.settings import EnvSettings, Settings

    monkeypatch.setenv("FIRECAL_CORS_ORIGINS", "https://demo.vercel.app, https://x.example")
    s = Settings(env=EnvSettings(_env_file=None), params=plan_home.settings.params,
                 paths=plan_home.settings.paths)
    c = TestClient(create_app(s))
    r = c.get("/api/metadatos", headers={"Origin": "https://demo.vercel.app"})
    assert r.headers.get("access-control-allow-origin") == "https://demo.vercel.app"
    r = c.get("/api/metadatos", headers={"Origin": "https://malo.example"})
    assert "access-control-allow-origin" not in r.headers


def test_margin_matches_antonio_example(api):
    """Ejemplo de antonio/backend-modelo (docs/DESPLIEGUE_MODELO.md): agosto de 2001."""
    b = _cal(api, fecha_inicio="2001-08", fecha_fin="2001-08")
    c = b["celdas"][0]
    assert c["calidad"] == "extrapolado" and c["fraccion_extrapolada"] == 1
    assert c["focos_armonizados"] == pytest.approx(176.02, abs=0.01)
    # Datos v1.3: agosto de 2022 sube con NOAA-20 y la mediana de agosto pasa de 151.5 a 156.73.
    assert c["mediana_hist"] == 156.73 and c["anomalia"] == pytest.approx(0.16, abs=0.01)
    assert c["incertidumbre"] == pytest.approx(77.4, abs=0.1)
    assert c["rango"] == [pytest.approx(98.6, abs=0.1), pytest.approx(253.4, abs=0.1)]
    assert c["anomalia_rango"] == [pytest.approx(-0.49, abs=0.01), pytest.approx(0.82, abs=0.01)]
    assert c["categoria"] == "incierta"


def test_no_margin_outside_extrapolated(api):
    c = _cal(api, fecha_inicio="2020-09", fecha_fin="2020-09")["celdas"][0]
    assert c["incertidumbre"] == 0 and c["rango"][0] == c["rango"][1]
    assert c["rango"][0] == pytest.approx(c["focos_armonizados"], abs=0.06)
    assert c["categoria"] != "incierta"


def test_focos_geojson_for_map(api):
    q = {"departamento": "PE-CUS", "fecha_inicio": "2020-09", "fecha_fin": "2020-09"}
    g = api.get("/api/focos.geojson", params=q).json()
    cal = api.get("/api/calendario", params=q).json()
    assert g["type"] == "FeatureCollection" and g["n_focos"] == len(g["features"]) > 0
    assert abs(g["total_focos_armonizados"] - cal["total_focos_armonizados"]) < 0.05
    props = g["features"][0]["properties"]
    assert "frp" not in props and {"eq_foco", "sensor", "fecha_local"} <= set(props)
    big = api.get("/api/focos.geojson", params={"departamento": "PE-CUS",
                                                "fecha_inicio": "2000-11", "fecha_fin": "2025-12"})
    assert big.status_code == 422 and "máximo" in big.json()["detail"]


# ------------------------------------------------------------------ mejoras de la auditoría
@pytest.mark.parametrize("mes", ["2020-01-15", "2020-8", "20-08", "2020/08"])
def test_strict_month_format(api, mes):
    r = api.get("/api/calendario", params={"departamento": "PE-CUS", "fecha_inicio": mes})
    assert r.status_code == 422 and "AAAA-MM" in r.json()["detail"]


def test_unknown_parameter_is_reported(api):
    r = api.get("/api/calendario", params={"departmento": "PE-CUS"})
    assert r.status_code == 422 and "departmento" in r.json()["detail"]


def test_bbox_label_is_readable(api):
    b = api.get("/api/calendario", params={"bbox": "-72.6,-13.8,-71.8,-13.2"}).json()
    assert b["aoi"]["descripcion"] == "el área seleccionada"
    assert b["aoi"]["bbox"] == [-72.6, -13.8, -71.8, -13.2]


def test_resumen_with_charts_in_one_call(api):
    b = api.get("/api/resumen", params={"departamento": "PE-CUS", "graficos": "true"}).json()
    assert len(b["frases"]) == 5
    assert set(b["graficos"]) == {"estacionalidad", "ranking", "acumulado", "altitud"}
    assert "graficos" not in api.get("/api/resumen", params={"departamento": "PE-CUS"}).json()


# ------------------------------------------------------------ QA de Erik (14-nov, rama erik/qa)
def test_qa_erik_fechas_absurdas_se_recortan(api):
    """3: 2020-01..9999-12 armaba 7 980 años (4,7 MB). Se recorta a la cobertura."""
    body = _cal(api, departamento="PE-CUS", fecha_inicio="2020-01", fecha_fin="9999-12")
    assert max(c["anio"] for c in body["celdas"]) == 2025
    body = _cal(api, departamento="PE-CUS", fecha_inicio="0000-01", fecha_fin="2001-01")
    assert min(c["anio"] for c in body["celdas"]) == 2000


def test_qa_erik_mensajes(api):
    """11 y 12: validación en el idioma de la persona, radio 0 y 'mes inválida'."""
    r = api.get("/api/calendario", params={"lat": "abc", "lon": -72, "radio_km": 5})
    assert r.status_code == 422 and r.json()["errors"][0]["error"] == "debe ser un número"
    r = api.get("/api/calendario", params={"lat": -13.5, "lon": -72, "radio_km": 0})
    assert r.status_code == 422 and "mayor que 0" in r.json()["detail"]
    r = api.get("/api/anomalias", params={"departamento": "PE-CUS", "mes": "2020-13"})
    assert r.status_code == 422 and "inválida" not in r.json()["detail"]

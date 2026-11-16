"""Informe técnico automático (GET /api/informe, firecal/plan/informe.py)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from api.main import create_app

PROHIBIDAS = re.compile(r"\b(riesgo|alerta|evento|risk|alert|event)s?\b", re.IGNORECASE)


@pytest.fixture(scope="module")
def api(plan_home) -> TestClient:
    return TestClient(create_app(plan_home.settings))


def _html(api, **params) -> str:
    r = api.get("/api/informe", params={"lang": "es", **params})
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/html")
    return r.text


def _texto(h: str) -> str:
    return re.sub(r"<[^>]+>", " ", h)


@pytest.mark.parametrize("lang", ["es", "en"])
def test_cusco_entero_por_defecto(api, lang):
    h = _html(api, lang=lang)
    assert "Cusco" in h and "2000-11" in h and "2025-12" in h
    for sec in (("Resumen", "Summary"), ("Método", "Method"), ("Limitaciones", "Limitations"),
                ("Trazabilidad", "Traceability")):
        assert sec[0 if lang == "es" else 1] in h
    assert "cusco-v1.3" in h and "15,818" in h               # versión y total de METHODOLOGY.md
    assert "d686c8fd" in h and "934c28d5" in h               # SHA-256 de los dos CSV
    assert "/api/calendario?" in h and "/api/metadatos" in h  # llamadas que lo reproducen
    assert "0.33" in h and "0.324" in h and "FIRMS" in h     # factores k y k20
    assert not PROHIBIDAS.search(_texto(h)), PROHIBIDAS.search(_texto(h))


def test_periodo_y_mes(api):
    h = _html(api, fecha_inicio="2020-01", fecha_fin="2024-12", mes="2024-09")
    assert "2020-01 – 2024-12" in h and "Situación de septiembre de 2024" in h
    filas = re.findall(r"<tr><td><b>(\d{4})</b>", h)
    assert filas == [str(y) for y in range(2020, 2025)]


def test_ambito_con_nivel_de_peligro(api):
    h = _html(api, ambito="distrito:080910", mes="2023-08")  # Pichari
    assert "Pichari" in h and "CENEPRED" in h and "Saaty" in h
    assert "/api/ambitos/distrito/080910" in h and "vulnerabilidad" in h
    assert not PROHIBIDAS.search(_texto(h))


def test_area_dibujada_y_punto(api):
    h = _html(api, bbox="-72.2,-13.6,-71.8,-13.3", fecha_inicio="2015-01")
    assert "bbox=-72.2" in h and "/api/hotspots.csv?" in h
    h = _html(api, lat=-12.6, lon=-73.8, radio_km=15)
    assert "radio_km=15" in h


def test_errores(api):
    g = lambda **p: api.get("/api/informe", params=p).status_code  # noqa: E731
    assert g(ambito="distrito:999999") == 404
    assert g(bbox="-80,-5,-79,-4") == 404                 # fuera de Cusco: sin datos, nunca 0
    assert g(mes="2024-13") == 422
    assert g(ambito="distrito") == 422
    assert g(ambito="distrito:080910", bbox="-72,-14,-71,-13") == 422
    assert g(zona="x") == 422

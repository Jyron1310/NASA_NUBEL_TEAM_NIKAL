"""Idioma de los textos de la API (?lang=en|es; por defecto api.default_lang = en)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from firecal.i18n import join_list, month_name, reset_lang, set_lang, t
from firecal.settings import ScientificParams, Settings


def _settings(base: Settings, **api) -> Settings:
    raw = base.params.model_dump()
    raw["api"].update(api)
    return Settings(env=base.env, params=ScientificParams.model_validate(raw), paths=base.paths)


@pytest.fixture(scope="module")
def api_en(plan_home) -> TestClient:
    return TestClient(create_app(_settings(plan_home.settings, default_lang="en")))


def test_t_and_fallbacks():
    token = set_lang("en")
    try:
        assert t(es="hola", en="hello") == "hello"
        assert t(es="solo español") == "solo español"          # sin traducción: respaldo
        assert month_name(8) == "August" and join_list(["a", "b", "c"]) == "a, b and c"
    finally:
        reset_lang(token)
    token = set_lang("pt")                                      # no soportado: idioma por defecto
    try:
        assert t(es="hola", en="hello") == "hello"
    finally:
        reset_lang(token)


def test_default_is_english(api_en):
    b = api_en.get("/api/calendario", params={"departamento": "PE-CUS"}).json()
    assert b["unidad"]["nombre"] == "Harmonized hotspots"
    assert any(n.startswith("2025: the value") for n in b["notes"])
    r = api_en.get("/api/calendario", params={"departamento": "PE-PUN"})
    assert r.status_code == 404 and r.json()["detail"].startswith("No data for 'PE-PUN'")


def test_lang_param_switches_to_spanish(api_en):
    b = api_en.get("/api/calendario", params={"departamento": "PE-CUS", "lang": "es"}).json()
    assert b["unidad"]["nombre"] == "Focos armonizados"
    r = api_en.get("/api/calendario", params={"departamento": "PE-PUN", "lang": "es"})
    assert r.json()["detail"].startswith("Sin datos para 'PE-PUN'")


def test_contract_fields_and_codes_do_not_change(api_en):
    """Los nombres de campos y los códigos (categoria, calidad) son el contrato: no se traducen."""
    en = api_en.get("/api/calendario", params={"departamento": "PE-CUS", "fecha_inicio": "2001-08",
                                               "fecha_fin": "2001-08"}).json()["celdas"][0]
    es = api_en.get("/api/calendario", params={"departamento": "PE-CUS", "fecha_inicio": "2001-08",
                                               "fecha_fin": "2001-08", "lang": "es"}
                    ).json()["celdas"][0]
    assert en == es and en["categoria"] == "incierta" and en["calidad"] == "extrapolado"


def test_analytics_in_english(api_en):
    r = api_en.get("/api/analitica/acumulado", params={"departamento": "PE-CUS", "anio": 2020})
    b = r.json()
    assert b["titulo"] == "How did 2020 progress compared with normal?"
    assert "By August 24 it had already reached" in b["en_simple"]
    assert b["veredicto"] == "muy por encima de lo normal"          # código del contrato
    est = api_en.get("/api/analitica/estacionalidad", params={"departamento": "PE-CUS"}).json()
    assert est["en_simple"].startswith("The hotspot season runs from July to October")
    assert est["meses"][7]["nombre"] == "August"
    alt = api_en.get("/api/analitica/altitud", params={"departamento": "PE-CUS"}).json()
    assert alt["bandas"][0]["banda"] == "below 1,500 m"
    res = api_en.get("/api/resumen", params={"departamento": "PE-CUS"}).json()
    assert res["titulo"] == "Hotspots in Cusco, in plain words" and len(res["frases"]) == 5


def test_errors_and_limits_in_english(plan_home):
    s = _settings(plan_home.settings, default_lang="en")
    raw = s.params.model_dump()
    raw["api"]["rate_limit"].update({"enabled": True, "burst": 1, "requests_per_minute": 1})
    raw["api"]["response_cache"]["enabled"] = False   # sin caché: la consulta repetida gasta cupo
    s = Settings(env=s.env, params=ScientificParams.model_validate(raw), paths=s.paths)
    api = TestClient(create_app(s))
    assert api.get("/api/departamentos").status_code == 200
    r = api.get("/api/departamentos")
    assert r.status_code == 429 and r.json()["detail"].startswith("Too many requests")
    r = api.get("/api/departamentos", params={"lang": "es"})
    assert r.json()["detail"].startswith("Demasiadas solicitudes")

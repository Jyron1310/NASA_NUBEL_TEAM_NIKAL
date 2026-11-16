"""Ámbitos de Cusco: nivel de peligro (formato CENEPRED) e informes (firecal/plan/ambitos.py)."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from firecal.plan.ambitos import (
    MIN_AREA_KM2,
    PARAMETROS,
    REF,
    clasificar,
    niveles_disponibles,
    pesos_ahp,
)

PROHIBIDAS = re.compile(r"\b(riesgo|alerta|evento|risk|alert|event)s?\b", re.IGNORECASE)


@pytest.fixture(scope="module")
def api(plan_home) -> TestClient:
    return TestClient(create_app(plan_home.settings))


def _get(api, ruta, **params):
    r = api.get(ruta, params={"lang": "es", **params})
    assert r.status_code == 200, r.text
    return r


def test_pesos_saaty_consistentes():
    pesos, cr = pesos_ahp()
    assert set(pesos) == set(PARAMETROS) and sum(pesos.values()) == pytest.approx(1, abs=0.002)
    assert pesos["densidad"] > pesos["recurrencia"] > pesos["extremo"]
    assert cr < 0.10  # Saaty: matriz consistente


def test_clasificar_en_cuatro_niveles():
    assert [clasificar(x, True) for x in (0.9, 0.6, 0.3, 0.1)] == [
        "muy_alto",
        "alto",
        "medio",
        "bajo",
    ]
    assert clasificar(0.99, False) == "bajo"  # sin fuego: siempre bajo


def test_niveles_disponibles(api):
    d = _get(api, "/api/ambitos").json()
    niveles = [n["nivel"] for n in d["niveles"]]
    assert niveles == niveles_disponibles()
    assert niveles[:2] == ["provincia", "distrito"] and niveles[2:] == [
        f"pfaf_{i:02d}" for i in range(1, 13)
    ]
    por = {n["nivel"]: n for n in d["niveles"]}
    assert por["provincia"]["n_unidades"] == 13 and por["distrito"]["n_unidades"] == 108
    assert d["metodo"]["consistente"]


@pytest.mark.parametrize("nivel", ["provincia", "distrito", "pfaf_08", "pfaf_12"])
def test_tipificacion_ordenada_y_coherente(api, nivel):
    d = _get(api, f"/api/ambitos/{nivel}").json()
    us = d["unidades"]
    clasif = [u for u in us if u["nivel_peligro"] != "sin_clasificar"]
    assert len(clasif) >= 4
    assert [u["puesto"] for u in clasif] == sorted(u["puesto"] for u in clasif)
    for u in clasif:
        assert 0 <= u["indice"] <= 1
        if all(abs(u["indice"] - x) > 0.001 for x in (0.25, 0.5, 0.75)):  # índice redondeado
            assert u["nivel_peligro"] == clasificar(u["indice"], u["con_focos"])
    for u in us:
        if u["nivel_peligro"] == "sin_clasificar":
            assert u["area_km2"] < MIN_AREA_KM2 and u["indice"] is None
    assert {u["nivel_peligro"] for u in clasif} == {"muy_alto", "alto", "medio", "bajo"}


@pytest.mark.parametrize(
    ("nivel", "minimo"), [("provincia", 0.98), ("distrito", 0.98), ("pfaf_08", 0.99)]
)
def test_los_ambitos_cubren_el_fuego_de_cusco(api, nivel, minimo):
    """Las unidades suman casi todo el fuego de Cusco 2003-2025 (cada celda va a una sola).

    Los distritos y provincias son de INEI y el límite de la serie es de FAO GAUL: en el borde hay
    celdas que no caen en ningún distrito (~1.7 %). Las cuencas se recortan al límite GAUL."""
    us = _get(api, f"/api/ambitos/{nivel}").json()["unidades"]
    suma = sum(u["media_anual"] for u in us) * (REF[1] - REF[0] + 1)
    cal = _get(
        api,
        "/api/calendario",
        departamento="PE-CUS",
        fecha_inicio=f"{REF[0]}-01",
        fecha_fin=f"{REF[1]}-12",
    ).json()["total_focos_armonizados"]
    assert minimo * cal <= suma <= cal * 1.001
    cob = _get(api, f"/api/ambitos/{nivel}").json()["cobertura"]
    assert cob == pytest.approx(suma / cal, abs=0.001)


def test_un_nivel_con_pocas_unidades_no_se_clasifica(api):
    us = _get(api, "/api/ambitos/pfaf_01").json()["unidades"]
    assert len(us) == 1 and us[0]["nivel_peligro"] == "sin_clasificar"


def test_detalle_de_una_provincia(api):
    d = _get(api, "/api/ambitos/provincia/0809").json()  # La Convención
    u = d["unidad"]
    assert u["nombre"] == "La Convencion" and u["nivel_peligro"] in {"muy_alto", "alto"}
    assert len(d["frases"]) == 5 and d["informe"] == "/api/ambitos/provincia/0809/informe"
    assert set(d["serie_anual"]) == {str(a) for a in range(REF[0], REF[1] + 1)}
    assert u["media_anual"] == pytest.approx(sum(d["serie_anual"].values()) / 23, abs=0.1)


def test_csv_y_geojson(api):
    r = _get(api, "/api/ambitos/distrito.csv")
    lineas = r.content.decode("utf-8").splitlines()
    assert lineas[0].startswith("﻿puesto,codigo,nombre,provincia") and len(lineas) == 109
    assert "nivel_de_peligro.csv" in r.headers["Content-Disposition"]
    g = _get(api, "/api/ambitos/distrito.geojson").json()
    assert len(g["features"]) == 108
    p = g["features"][0]["properties"]
    assert {"codigo", "nombre", "nivel_peligro", "etiqueta", "color"} <= set(p)


@pytest.mark.parametrize("lang", ["es", "en"])
def test_informe_html(api, lang):
    r = api.get("/api/ambitos/distrito/080910/informe", params={"lang": lang})  # Pichari
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    h = r.text
    assert "Pichari" in h and "CENEPRED" in h and "<svg" in h and "FIRMS" in h
    assert ("Nivel de peligro por focos de calor" if lang == "es" else "Hotspot hazard level") in h
    assert ("definiciones técnicas" if lang == "es" else "technical definitions") in h.lower()
    assert "MOD14" in h and "VNP14IMG" in h and "type = 0" in h
    texto = re.sub(r"<[^>]+>", " ", h)
    assert not PROHIBIDAS.search(texto), PROHIBIDAS.search(texto)


def test_vocabulario_en_las_respuestas(api):
    for ruta in ("/api/ambitos", "/api/ambitos/provincia", "/api/ambitos/provincia/0803"):
        for lang in ("es", "en"):
            texto = api.get(ruta, params={"lang": lang}).text
            assert not PROHIBIDAS.search(texto), (ruta, lang, PROHIBIDAS.search(texto))


def test_errores(api):
    assert api.get("/api/ambitos/municipio").status_code == 404
    assert api.get("/api/ambitos/distrito/999999").status_code == 404
    assert api.get("/api/ambitos/distrito", params={"zona": "x"}).status_code == 422


def test_definiciones_tecnicas_en_la_api(api):
    for lang, palabra in (("es", "Foco de calor"), ("en", "Hotspot")):
        d = api.get("/api/ambitos", params={"lang": lang}).json()["metodo"]["definiciones"]
        assert set(d) == {"foco_de_calor", "foco_armonizado", "nivel_de_peligro"}
        assert d["foco_de_calor"].startswith(palabra) and "FIRMS" in d["foco_de_calor"]


def test_informe_de_un_mes(api):
    """Con mes=AAAA-MM el informe agrega la situación de ese mes frente a los mismos meses."""
    h = _get(api, "/api/ambitos/provincia/0809/informe", mes="2020-08").text  # La Convención
    assert "Situación de agosto de 2020" in h and "Puesto" in h and "Día por día" in h
    vacio = _get(
        api, "/api/ambitos/distrito/080403/informe", mes="2007-08"
    ).text  # Lamay, sin focos
    assert "Sin focos de calor" in vacio and "Puesto" not in vacio and "Día por día" not in vacio
    assert "Muy pocos focos de calor" in vacio
    assert (
        api.get("/api/ambitos/provincia/0809/informe", params={"mes": "1999-01"}).status_code == 404
    )
    assert (
        api.get("/api/ambitos/provincia/0809/informe", params={"mes": "2020-13"}).status_code == 422
    )


# ------------------------------------------------------------------ focos por día del año
def test_dia_del_anio_sin_bisiestos():
    from firecal.plan.ambitos import dia_del_anio

    fechas = ["2020-02-28", "2020-02-29", "2020-03-01", "2021-03-01", "2020-12-31", "2021-01-01"]
    assert list(dia_del_anio(fechas)) == [59, 59, 60, 60, 365, 1]


def test_dias_suma_lo_mismo_que_la_tipificacion(api):
    tipos = _get(api, "/api/ambitos/provincia").json()["unidades"]
    crudo = _get(api, "/api/ambitos/provincia/dias", ventana=1).json()
    suave = _get(api, "/api/ambitos/provincia/dias", ventana=31).json()
    assert len(crudo["dias"]) == 365 and crudo["anios"] == REF[1] - REF[0] + 1
    por_anio = sum(n["focos_por_anio"] for n in crudo["niveles"])
    # mismas celdas y años que la tipificación (media_anual por unidad, 2003-2025)
    assert por_anio == pytest.approx(sum(u["media_anual"] for u in tipos), rel=0.002)
    # el promedio móvil circular no cambia el total del año
    total = lambda d: sum(f["total"] for f in d["dias"])  # noqa: E731
    assert total(crudo) == pytest.approx(por_anio, rel=1e-3)
    assert total(suave) == pytest.approx(total(crudo), rel=1e-3)
    assert sum(n["parte"] for n in crudo["niveles"]) == pytest.approx(1, abs=0.002)
    for n in crudo["niveles"]:
        if n["focos_por_anio"] > 0:
            assert n["dia_p10"] <= n["dia_p50"] <= n["dia_p90"] and 1 <= n["dia_pico"] <= 365
    assert not PROHIBIDAS.search(crudo["en_simple"] + crudo["como_leerlo"])


def test_dias_parametros(api):
    corto = _get(api, "/api/ambitos/distrito/dias", desde=2020, hasta=2020, ventana=15).json()
    assert corto["anios"] == 1 and corto["ventana"] == 15
    for params in ({"ventana": 5}, {"desde": 1999}, {"desde": 2024, "hasta": 2020}):
        assert api.get("/api/ambitos/provincia/dias", params=params).status_code == 422
    assert api.get("/api/ambitos/no_existe/dias").status_code == 404


def test_celdas_del_dia_cuadran_con_la_curva(api):
    crudo = _get(api, "/api/ambitos/provincia/dias", ventana=1).json()["dias"]
    uno = _get(api, "/api/ambitos/provincia/dias/244", ventana=1).json()
    siete = _get(api, "/api/ambitos/provincia/dias/1", ventana=7).json()
    assert uno["total"] == pytest.approx(crudo[243]["total"], abs=0.01)
    assert sum(f["properties"]["n"] for f in uno["geojson"]["features"]) == pytest.approx(
        uno["total"], abs=0.05
    )
    # ventana circular: el 1 de enero junta del 29 de diciembre al 4 de enero
    ventana = [crudo[i]["total"] for i in (362, 363, 364, 0, 1, 2, 3)]
    assert siete["total"] == pytest.approx(sum(ventana), abs=0.01)
    for dia in (0, 366):
        assert api.get(f"/api/ambitos/provincia/dias/{dia}").status_code == 422

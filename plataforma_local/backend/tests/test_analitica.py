"""Analíticas sencillas sobre la serie armonizada de Cusco (firecal/plan/analitica.py)."""

from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from firecal.plan.analitica import _veces
from firecal.plan.sources import CELDA_DIA_CSV, harmonized_dir

CUSCO = {"departamento": "PE-CUS"}


@pytest.fixture(scope="module")
def api(plan_home) -> TestClient:
    return TestClient(create_app(plan_home.settings))


@pytest.fixture(scope="module")
def celda_dia() -> pd.DataFrame:
    df = pd.read_csv(harmonized_dir() / CELDA_DIA_CSV)
    df["anio"] = df["fecha_local"].str[:4].astype(int)
    df["mes"] = df["fecha_local"].str[5:7].astype(int)
    return df


def _get(api: TestClient, ruta: str, **params) -> dict:
    res = api.get(f"/api/analitica/{ruta}", params={**CUSCO, **params})
    assert res.status_code == 200, res.text
    body = res.json()
    # Toda analítica se explica sola: frase simple, cómo leerla y aviso de que no es pronóstico.
    assert body["en_simple"] and body["como_leerlo"] and body["titulo"].startswith("¿")
    assert any("No es un pronóstico" in n for n in body["notes"])
    assert "incendio" not in body["en_simple"].lower() and "hectárea" not in body["en_simple"]
    return body


def test_veces_en_palabras():
    assert _veces(1355, 555) == "más del doble de"
    assert _veces(1100, 555) == "cerca del doble de"
    assert _veces(700, 555) == "26 % más que"
    assert _veces(560, 555) == "parecido a"
    assert _veces(385, 555) == "31 % menos que"
    assert _veces(2000, 555) == "unas 4 veces"


def test_estacionalidad(api, celda_dia):
    d = _get(api, "estacionalidad")
    assert d["anios_referencia"] == [2003, 2025]
    assert d["temporada"] == [7, 8, 9, 10] and d["mes_pico"] == 9
    assert sum(m["parte_del_anio"] for m in d["meses"]) == pytest.approx(1, abs=0.01)
    ref = celda_dia[celda_dia["anio"] >= 2003]
    sep = ref[ref["mes"] == 9].groupby("anio")["eq_hotspots"].sum()
    assert d["meses"][8]["mediana"] == pytest.approx(sep.median(), abs=0.1)
    assert "julio a octubre" in d["en_simple"] and "septiembre" in d["en_simple"]


def test_ranking(api, celda_dia):
    d = _get(api, "ranking")
    anual = celda_dia.groupby("anio")["eq_hotspots"].sum()
    assert [a["anio"] for a in d["anios"][:2]] == [2005, 2020]
    assert d["anios"][0]["total"] == pytest.approx(1355, abs=1)
    assert d["anio_tipico"] == pytest.approx(anual.loc[2003:2025].median(), abs=0.1)
    assert {a["anio"] for a in d["anios"]} == set(range(2001, 2026))     # 2000 está incompleto
    por_anio = {a["anio"]: a for a in d["anios"]}
    assert por_anio[2001]["calidad"] == "extrapolado" and por_anio[2001]["incertidumbre"] > 0
    assert por_anio[2002]["calidad"] == "mixto" and por_anio[2003]["calidad"] == "ok"
    # La frase no nombra como extremo un año con focos extrapolados.
    assert "2005" in d["en_simple"] and "2004" in d["en_simple"] and "2002" not in d["en_simple"]


def test_acumulado(api, celda_dia):
    d = _get(api, "acumulado", anio=2020)
    assert d["total"] == pytest.approx(1206, abs=1) and d["veredicto"].startswith("muy por encima")
    assert d["curva"][-1]["dia"] == 365 and d["curva"][-1]["acumulado"] == d["total"]
    valores = [c["acumulado"] for c in d["curva"]]
    assert valores == sorted(valores)                                    # una suma nunca baja
    assert all(c["bajo"] <= c["normal"] <= c["alto"] for c in d["curva"])
    # El "año típico" es el mismo número que en el ranking.
    assert d["normal"] == _get(api, "ranking")["anio_tipico"]
    assert _get(api, "acumulado")["anio"] == 2025                        # por defecto, el último
    assert _get(api, "acumulado", anio=2025)["veredicto"].startswith("muy por debajo")
    assert any("extrapolados" in n for n in _get(api, "acumulado", anio=2001)["notes"])
    assert api.get("/api/analitica/acumulado", params={**CUSCO, "anio": 1999}).status_code == 422


def test_altitud(api, celda_dia):
    d = _get(api, "altitud")
    assert sum(b["focos_armonizados"] for b in d["bandas"]) == pytest.approx(15818, abs=1)
    assert sum(b["parte"] for b in d["bandas"]) == pytest.approx(1, abs=0.01)
    alto = celda_dia.loc[celda_dia["alt_m"] >= 3500, "eq_hotspots"].sum()
    assert d["bandas"][3]["focos_armonizados"] == pytest.approx(alto, abs=0.1)


def test_recurrencia(api, celda_dia):
    d = _get(api, "recurrencia", limite=10)
    viirs = celda_dia[celda_dia["anio"] >= 2013]
    anios = viirs.groupby(["cell_lat", "cell_lon"])["anio"].nunique()
    assert d["lugares"] == len(anios) and d["anios_posibles"] == 13
    assert sum(x["lugares"] for x in d["por_numero_de_anios"]) == len(anios)
    assert d["lugares_recurrentes"] == int((anios >= d["umbral_recurrente"]).sum())
    assert len(d["celdas"]) == 10 and d["celdas"][0]["anios"] == anios.max()
    assert [c["anios"] for c in d["celdas"]] == sorted((c["anios"] for c in d["celdas"]),
                                                       reverse=True)


def test_resumen_y_sin_datos(api):
    r = api.get("/api/resumen", params=CUSCO).json()
    assert len(r["frases"]) == 5 and all(f["pregunta"] and f["respuesta"] for f in r["frases"])
    for ruta in ("resumen", "analitica/ranking", "analitica/recurrencia"):
        fuera = api.get(f"/api/{ruta}", params={"departamento": "PE-PUN"})
        assert fuera.status_code == 404 and "Sin datos" in fuera.json()["detail"]
    # Un rectángulo dentro de Cusco también funciona y da menos que el departamento.
    caja = api.get("/api/analitica/ranking", params={"bbox": "-72.6,-13.4,-72.0,-12.8"}).json()
    assert 0 < caja["anio_tipico"] < 555


def test_area_dibujada_cuadra_con_el_calendario(api):
    """En un rectángulo, las analíticas suman lo mismo que el calendario (eq_foco de los focos)."""
    caja = {"bbox": "-72.6,-13.4,-72.0,-12.8"}
    por_anio = {a["anio"]: a["total"] for a in
                api.get("/api/analitica/ranking", params=caja).json()["anios"]}
    cal = api.get("/api/calendario", params={**caja, "fecha_inicio": "2020-01",
                                             "fecha_fin": "2020-12"}).json()
    assert por_anio[2020] == pytest.approx(cal["total_focos_armonizados"], abs=0.1)
    alt = api.get("/api/analitica/altitud", params=caja).json()
    todo = api.get("/api/calendario", params=caja).json()["total_focos_armonizados"]
    assert sum(b["focos_armonizados"] for b in alt["bandas"]) == pytest.approx(todo, abs=0.5)
    acum = api.get("/api/analitica/acumulado", params={**caja, "anio": 2020}).json()
    assert acum["total"] == pytest.approx(cal["total_focos_armonizados"], abs=0.1)


def test_fecha_de_cruce_en_anio_bisiesto(api):
    """2020 (bisiesto) superó lo de un año típico el 24 de agosto (verificado con los CSV)."""
    r = api.get("/api/analitica/acumulado", params={"departamento": "PE-CUS", "anio": 2020})
    assert "El 24 de agosto" in r.json()["en_simple"]


def test_nota_de_2025(api):
    r = api.get("/api/analitica/acumulado", params={"departamento": "PE-CUS", "anio": 2025}).json()
    assert any(n.startswith("2025:") for n in r["notes"])
    assert any(n.startswith("2025:") for n in api.get(
        "/api/resumen", params={"departamento": "PE-CUS"}).json()["notes"])
    otro = api.get("/api/analitica/acumulado", params={"departamento": "PE-CUS", "anio": 2019})
    assert not any(n.startswith("2025:") for n in otro.json()["notes"])


# ------------------------------------------------------------ QA de Erik (14-nov, rama erik/qa)
def test_qa_erik_poco_fuego_no_inventa_temporada(api):
    """5: con todas las medianas en 0 el 'mes pico' salía enero y la frase se contradecía."""
    res = api.get("/api/analitica/estacionalidad", params={"lat": -13.52, "lon": -71.97,
                                                          "radio_km": 3})
    if res.status_code == 404:                  # sin focos en el área: también es válido
        return
    body = res.json()
    if max(m["mediana"] for m in body["meses"]) < 0.5:
        assert "muy pocos focos de calor" in body["en_simple"]
        assert "con unos 0" not in body["en_simple"]


@pytest.mark.parametrize("bbox", ["-73.2,-12.2,-72.4,-11.4", "-72.2,-13.7,-71.8,-13.4"])
def test_qa_erik_anio_tranquilo_no_es_extrapolado(api, bbox):
    """6: 2001 o 2002 con 0 focos (solo Terra) no pueden ser 'el año más tranquilo'."""
    body = api.get("/api/analitica/ranking", params={"bbox": bbox}).json()
    assert all(f["calidad"] == "extrapolado" for f in body["anios"] if f["anio"] <= 2002
               and f["calidad"] != "mixto")
    assert "tranquilo fue 2001" not in body["en_simple"]
    assert "tranquilo fue 2002" not in body["en_simple"]


def test_qa_erik_plurales(api):
    """10: '1 focos armonizados' y '1 lugares'."""
    for ruta in ("estacionalidad", "ranking", "acumulado", "recurrencia"):
        txt = _get(api, ruta)["en_simple"]
        assert " 1 focos" not in txt and " 1 lugares" not in txt


def test_qa_erik_area_sin_fuego(api):
    """13: área de Cusco sin fuego: mensaje claro, sin coordenadas crudas."""
    res = api.get("/api/resumen", params={"bbox": "-71.36,-13.82,-71.34,-13.80"})
    if res.status_code == 404:
        detail = res.json()["detail"]
        assert "No se detectaron focos" in detail and "bbox [" not in detail

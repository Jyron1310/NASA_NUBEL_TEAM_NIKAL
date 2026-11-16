"""Capa en tiempo real (firecal/nrt.py): FIRMS simulado, sin red ni cuota."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from shapely.geometry import box

from api.main import create_app
from firecal.nrt import NrtNotConfigured, NrtStore, NrtUnavailable, parse_csv

KEY = "abc123secretkey"
VIIRS_HEAD = ("latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
              "confidence,version,bright_ti5,frp,daynight\n")
MODIS_HEAD = ("latitude,longitude,brightness,scan,track,acq_date,acq_time,satellite,instrument,"
              "confidence,version,bright_t31,frp,daynight\n")


def _row(lat, lon, horas_atras, conf="n", modis=False):
    d = datetime.now(UTC) - timedelta(hours=horas_atras)
    sat = "T" if modis else "N"
    inst = "MODIS" if modis else "VIIRS"
    return (f"{lat},{lon},330.1,0.4,0.4,{d:%Y-%m-%d},{d:%H%M},{sat},{inst},{conf},2.0NRT,"
            "290.0,12.5,D\n")


def _transport(calls: list, fail: bool = False):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if fail:
            return httpx.Response(500, text="error")
        if "MODIS_NRT" in str(request.url):
            return httpx.Response(200, text=MODIS_HEAD + _row(-13.5, -72.0, 3, "85", True))
        return httpx.Response(200, text=VIIRS_HEAD + _row(-13.5, -72.0, 2)       # dentro
                              + _row(-13.6, -72.1, 30, "h")                        # dentro, 30 h
                              + _row(-16.4, -71.5, 1))                             # fuera
    return httpx.MockTransport(handler)


CUSCO_BOX = box(-74.0, -15.5, -70.3, -11.2)


def test_sin_clave_no_configurado():
    with pytest.raises(NrtNotConfigured):
        NrtStore(None, CUSCO_BOX).geojson(24)


def test_filtra_cusco_ventana_y_sin_frp():
    calls: list = []
    nrt = NrtStore(KEY, box(-73, -14, -71, -13), client=httpx.Client(transport=_transport(calls)))
    g24 = nrt.geojson(24)
    # 4 fuentes x 1 VIIRS dentro (<24 h) = 3 VIIRS + 1 MODIS; el de Arequipa queda fuera
    assert g24["metadata"]["detecciones"] == 4
    assert len(nrt.geojson(48)["features"]) == 7           # + los 3 VIIRS de hace 30 h
    props = g24["features"][0]["properties"]
    assert "frp" not in props and "brightness" not in str(props)
    assert {f["properties"]["instrumento"] for f in g24["features"]} == {"VIIRS", "MODIS"}
    assert len(calls) == 4                                   # se reutiliza: 4 transacciones
    assert all("/5" in c for c in calls)                     # siempre 5 días


def test_clave_nunca_en_respuesta_ni_logs(caplog):
    calls: list = []
    nrt = NrtStore(KEY, CUSCO_BOX, client=httpx.Client(transport=_transport(calls, fail=True)))
    caplog.set_level(logging.DEBUG)
    with pytest.raises(NrtUnavailable) as exc:
        nrt.geojson(24)
    assert KEY not in str(exc.value) and KEY not in caplog.text
    assert KEY in calls[0]                                    # la clave sí va a FIRMS


def test_firms_cae_se_mantiene_lo_anterior():
    calls: list = []
    ok = httpx.Client(transport=_transport(calls))
    nrt = NrtStore(KEY, CUSCO_BOX, refresh_min=0, client=ok)
    assert nrt.geojson(24)["metadata"]["detecciones"] > 0
    nrt._client = httpx.Client(transport=_transport(calls, fail=True))
    g = nrt.geojson(24)
    assert g["metadata"]["detecciones"] > 0 and g["metadata"]["desactualizado"] is True


def test_parse_ignora_filas_rotas():
    filas = parse_csv(VIIRS_HEAD + "x,y,1,1,1,fecha,hora,N,VIIRS,n,2,1,1,D\n", "VIIRS_SNPP_NRT")
    assert filas == []


@pytest.fixture
def api(plan_home) -> TestClient:
    return TestClient(create_app(plan_home.settings))


def test_endpoint_sin_clave_503_y_horas_invalidas(api):
    r = api.get("/api/tiempo-real")
    assert r.status_code == 503 and "MAP_KEY" in r.json()["detail"]
    assert api.get("/api/tiempo-real", params={"horas": 7}).status_code == 422


def test_endpoint_con_clave(api):
    calls: list = []
    region = api.app.state.plan.region_geom
    api.app.state.nrt = NrtStore(KEY, region, client=httpx.Client(transport=_transport(calls)))
    r = api.get("/api/tiempo-real", params={"horas": 48})
    assert r.status_code == 200
    body = r.json()
    assert body["metadata"]["detecciones"] >= 1 and "FIRMS" in body["metadata"]["credito"]
    assert KEY not in r.text
    assert r.headers["cache-control"] == "public, max-age=300"
    assert r.headers.get("x-cache") is None                  # fuera de la caché de respuestas

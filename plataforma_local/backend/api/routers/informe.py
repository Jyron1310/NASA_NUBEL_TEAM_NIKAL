"""Informe técnico automático de focos de calor para cualquier área y periodo.

``GET /api/informe``: HTML imprimible (Imprimir -> PDF). Área: ``departamento=PE-CUS``,
``bbox=oeste,sur,este,norte``, ``lat`` + ``lon`` + ``radio_km`` o ``ambito=nivel:codigo``
(provincia, distrito o pfaf_01 ... pfaf_12). Periodo: ``fecha_inicio`` y ``fecha_fin`` (AAAA-MM) y,
opcional, ``mes=AAAA-MM`` para detallar un mes. Solo usa los datos de la plataforma
(firecal/plan/informe.py).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from api.routers.plan import (
    BBox,
    Dep,
    Fin,
    Inicio,
    Lat,
    Lon,
    Radio,
    _call,
    _custom_aoi,
    _known_params,
    _store,
)
from firecal.i18n import t
from firecal.plan.informe import informe_tecnico

router = APIRouter(prefix="/api", tags=["informe"], dependencies=[Depends(_known_params)])


@router.get("/informe", response_class=HTMLResponse)
def informe(request: Request, departamento: Dep = None, bbox: BBox = None, lat: Lat = None,
            lon: Lon = None, radio_km: Radio = None, ambito: str | None = None,
            fecha_inicio: Inicio = None, fecha_fin: Fin = None,
            mes: str | None = None) -> HTMLResponse:
    """Informe técnico: resumen, calendario, análisis, método, limitaciones y trazabilidad."""
    store = _store(request)
    params = {"departamento": departamento, "bbox": bbox, "lat": lat, "lon": lon,
              "radio_km": radio_km}
    if not ambito and not bbox and lat is None:
        params["departamento"] = departamento or "PE-CUS"

    def run() -> str:
        return informe_tecnico(store, params, ambito, fecha_inicio, fecha_fin, mes)

    if _custom_aoi(bbox, lat):
        with request.app.state.gate.turn():
            body = _call(run)
    else:
        body = _call(run)
    return HTMLResponse(body, headers={"Content-Language": t(es="es", en="en")})

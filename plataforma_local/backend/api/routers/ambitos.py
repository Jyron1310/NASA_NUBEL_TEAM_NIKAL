"""Ámbitos de Cusco: nivel de peligro por focos de calor (formato CENEPRED) e informes.

- ``GET /api/ambitos``: niveles disponibles (provincia, distrito, pfaf_01 ... pfaf_12).
- ``GET /api/ambitos/{nivel}``: unidades ordenadas por nivel de peligro, parámetros y método.
- ``GET /api/ambitos/{nivel}.geojson``: las mismas unidades con geometría y color, para el mapa.
- ``GET /api/ambitos/{nivel}.csv``: tabla para los tomadores de decisión (UTF-8 con BOM).
- ``GET /api/ambitos/{nivel}/dias``: focos por día del año según el nivel de peligro (dinámico).
- ``GET /api/ambitos/{nivel}/dias/{dia}``: las celdas de ese día (para el mapa).
- ``GET /api/ambitos/{nivel}/{codigo}``: una unidad, con frases "en simple" y serie anual.
- ``GET /api/ambitos/{nivel}/{codigo}/informe``: informe imprimible (HTML; Imprimir -> PDF).

Método y límites en ``firecal/plan/ambitos.py``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, Response

from api.routers.plan import _call, _envelope, _known_params, _store
from firecal.i18n import t
from firecal.plan import ambitos

router = APIRouter(prefix="/api/ambitos", tags=["ámbitos"], dependencies=[Depends(_known_params)])


@router.get("")
def niveles(request: Request) -> dict:
    """Niveles de ámbito disponibles con su número de unidades."""
    store = _store(request)
    out = []
    for n in ambitos.niveles_disponibles():
        capa = ambitos._capa(n)
        out.append(
            {
                "nivel": n,
                "titulo": ambitos.titulo_nivel(n),
                "n_unidades": len(capa["features"]),
                "grupo": "politico" if n in ("provincia", "distrito") else "hidrografico",
                "fuente": capa["fuente"],
            }
        )
    return _envelope(
        store, {"niveles": out, "metodo": ambitos.metodo(), "notes": ambitos.metodo()["notas"]}
    )


@router.get("/{nivel}.geojson")
def nivel_geojson(request: Request, nivel: str) -> dict:
    """Unidades del nivel con geometría, nivel de peligro y color (para pintar el mapa)."""
    store = _store(request)
    return _call(ambitos.geojson_nivel, store, nivel)


@router.get("/{nivel}.csv")
def nivel_csv(request: Request, nivel: str) -> Response:
    """Tabla del nivel, ordenada por nivel de peligro (abre bien en Excel)."""
    store = _store(request)
    texto = _call(ambitos.csv_nivel, store, nivel)
    return Response(
        texto.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": "attachment; "
            f'filename="nikal_cusco_{nivel}_nivel_de_peligro.csv"'
        },
    )


@router.get("/{nivel}")
def nivel(request: Request, nivel: str) -> dict:
    """Unidades del nivel ordenadas de mayor a menor nivel de peligro."""
    store = _store(request)
    body = _call(ambitos.resumen_nivel, store, nivel)
    return _envelope(store, {**body, "notes": body["metodo"]["notas"]})


@router.get("/{nivel}/dias")
def dias(
    request: Request,
    nivel: str,
    desde: int = ambitos.REF[0],
    hasta: int = ambitos.REF[1],
    ventana: int = 7,
) -> dict:
    """Focos armonizados por día del año, separados por el nivel de peligro (CENEPRED) de la unidad.

    Se calcula al pedirlo con los años (``desde``-``hasta``) y la ventana de suavizado (1, 7, 15
    o 31 días) elegidos."""
    store = _store(request)
    body = _call(ambitos.distribucion_diaria, store, nivel, desde, hasta, ventana)
    return _envelope(store, {**body, "notes": body["metodo"]["notas"]})


@router.get("/{nivel}/dias/{dia}")
def dia_mapa(
    request: Request,
    nivel: str,
    dia: int,
    desde: int = ambitos.REF[0],
    hasta: int = ambitos.REF[1],
    ventana: int = 7,
) -> dict:
    """Celdas con focos en ese día del año (± media ventana) y el nivel de peligro de su unidad."""
    store = _store(request)
    return _envelope(store, _call(ambitos.celdas_dia, store, nivel, dia, desde, hasta, ventana))


@router.get("/{nivel}/{codigo}")
def unidad(request: Request, nivel: str, codigo: str) -> dict:
    """Una unidad: parámetros frente a la mediana del nivel, frases en simple y serie anual."""
    store = _store(request)
    d = _call(ambitos.detalle, store, nivel, codigo)
    d.pop("aoi")
    return _envelope(
        store,
        {**d, "informe": f"/api/ambitos/{nivel}/{codigo}/informe", "notes": d["metodo"]["notas"]},
    )


@router.get("/{nivel}/{codigo}/informe", response_class=HTMLResponse)
def informe(request: Request, nivel: str, codigo: str, mes: str | None = None) -> HTMLResponse:
    """Informe automático de la unidad, listo para imprimir o guardar en PDF.

    Con ``mes=AAAA-MM`` agrega la situación de ese mes frente a los mismos meses de otros años."""
    store = _store(request)
    return HTMLResponse(
        _call(ambitos.informe_html, store, nivel, codigo, mes),
        headers={"Content-Language": t(es="es", en="en")},
    )

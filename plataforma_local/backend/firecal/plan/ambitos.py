"""Nivel de peligro por focos de calor e informes por ámbito (provincia, distrito, cuenca).

Ámbitos (``config/ambitos/*.geojson``, ver ``scripts/build_ambitos.py``):
- político-administrativos: provincias y distritos de Cusco (INEI, código de ubigeo);
- hidrográficos: cuencas Pfafstetter de HydroBASINS, niveles 1 a 12, recortadas a Cusco.

Cada celda de la serie armonizada (0.01°) se asigna al ámbito que contiene su centro.

**Nivel de peligro (formato de CENEPRED: muy alto, alto, medio, bajo).** Es el peligro *relativo*
por actividad histórica de focos de calor, comparando las unidades de un mismo nivel dentro de
Cusco. No incluye vulnerabilidad (población, viviendas, cobertura, servicios): es un insumo para la
evaluación de CENEPRED, no la reemplaza.

Parámetros (años completos 2003-2025, sin focos extrapolados; por 100 km² dentro de Cusco):
1. ``densidad``: focos armonizados por año (media).
2. ``recurrencia``: lugares de ~1 km que ardieron en 4 o más de los 13 años con VIIRS (2013-2025).
3. ``extremo``: focos armonizados del año más activo.

Pesos por comparación de pares de Saaty (proceso de análisis jerárquico, el del manual de
CENEPRED), con su razón de consistencia. Cada parámetro se convierte en su percentil dentro del
nivel (0 = el menor, 1 = el mayor); el índice es la suma ponderada y se clasifica en cuartos fijos:
>= 0.75 muy alto, >= 0.50 alto, >= 0.25 medio, < 0.25 bajo. Una unidad sin focos es siempre "bajo".
No se clasifican los niveles con menos de 4 unidades ni las unidades con menos de 10 km² en Cusco.
"""

from __future__ import annotations

import csv
import html
import io
import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import shape

from firecal.i18n import month_name, t
from firecal.plan.query import AOI, PlanError, PlanNoData, PlanStore, unidad

AMBITOS_DIR = Path(__file__).resolve().parents[2] / "config" / "ambitos"
REF = (2003, 2025)  # años completos sin focos extrapolados
RECURRENCIA_DESDE = 2013  # solo VIIRS, como en las analíticas
RECURRENTE_MIN_ANIOS = 4  # 1 de cada 3 de los 13 años (igual que analitica.recurrencia)
MIN_UNIDADES = 4
MIN_AREA_KM2 = 10.0  # recortes chicos en el borde de Cusco: un foco los dispara
PARAMETROS = ("densidad", "recurrencia", "extremo")
# Matriz de comparación de pares (Saaty, 1-9): fila más importante que columna. Propuesta inicial,
# editable:
# la densidad media pesa algo más que la recurrencia y bastante más que el año extremo.
SAATY = [[1, 2, 3], [1 / 2, 1, 2], [1 / 3, 1 / 2, 1]]
INDICE_ALEATORIO = {1: 0.0, 2: 0.0, 3: 0.58, 4: 0.90, 5: 1.12}
UMBRALES = ((0.75, "muy_alto"), (0.50, "alto"), (0.25, "medio"), (0.0, "bajo"))
COLOR = {
    "muy_alto": "#c0392b",
    "alto": "#e67e22",
    "medio": "#f1c40f",
    "bajo": "#27ae60",
    "sin_clasificar": "#98a2b3",
}


def etiqueta(nivel: str) -> str:
    return {
        "muy_alto": t(es="Muy alto", en="Very high"),
        "alto": t(es="Alto", en="High"),
        "medio": t(es="Medio", en="Medium"),
        "bajo": t(es="Bajo", en="Low"),
        "sin_clasificar": t(es="Sin clasificar", en="Not classified"),
    }[nivel]


def pesos_ahp(matriz=SAATY) -> tuple[dict, float]:
    """Pesos (autovector principal normalizado) y razón de consistencia de Saaty."""
    m = np.asarray(matriz, dtype=float)
    vals, vecs = np.linalg.eig(m)
    i = int(np.argmax(vals.real))
    w = np.abs(vecs[:, i].real)
    w = w / w.sum()
    n = len(m)
    ci = (vals[i].real - n) / (n - 1) if n > 1 else 0.0
    ri = INDICE_ALEATORIO.get(n, 1.12)
    cr = ci / ri if ri else 0.0
    return dict(zip(PARAMETROS, (round(float(x), 3) for x in w), strict=True)), round(float(cr), 3)


def clasificar(indice: float, con_focos: bool) -> str:
    if not con_focos:
        return "bajo"
    return next(n for u, n in UMBRALES if indice >= u)


# ------------------------------------------------------------------ carga de ámbitos
def niveles_disponibles() -> list[str]:
    orden = ["provincia", "distrito"] + [f"pfaf_{i:02d}" for i in range(1, 13)]
    return [n for n in orden if (AMBITOS_DIR / f"{n}.geojson").is_file()]


def titulo_nivel(nivel: str) -> str:
    if nivel == "provincia":
        return t(es="Provincias", en="Provinces")
    if nivel == "distrito":
        return t(es="Distritos", en="Districts")
    return t(
        es=f"Cuencas Pfafstetter, nivel {int(nivel[5:])}",
        en=f"Pfafstetter basins, level {int(nivel[5:])}",
    )


class _Cache:
    lock = threading.Lock()
    stamp = None
    capas: dict = {}
    tipos: dict = {}


def _capa(nivel: str) -> dict:
    if nivel not in niveles_disponibles():
        raise PlanNoData(
            t(
                es=f"Ámbito desconocido '{nivel}'. Disponibles: "
                f"{', '.join(niveles_disponibles())}.",
                en=f"Unknown scope '{nivel}'. Available: {', '.join(niveles_disponibles())}.",
            )
        )
    if nivel not in _Cache.capas:
        data = json.loads((AMBITOS_DIR / f"{nivel}.geojson").read_text(encoding="utf-8"))
        data["geoms"] = [shape(f["geometry"]) for f in data["features"]]
        _Cache.capas[nivel] = data
    return _Cache.capas[nivel]


def _preparar(store: PlanStore) -> None:
    """Asigna cada celda de la serie a sus ámbitos (tabla ``ambito_celdas`` en DuckDB)."""
    store.meta  # noqa: B018 - carga los datos
    con = store._ensure()
    clave = (id(con), store._stamp)  # por conexión: otro PlanStore con los mismos datos también
    if _Cache.stamp == clave:
        return
    with _Cache.lock:
        if _Cache.stamp == clave:
            return
        celdas = con.execute("SELECT DISTINCT cell_lat, cell_lon FROM cd").df()
        pts = shapely.points(celdas["cell_lon"].to_numpy(), celdas["cell_lat"].to_numpy())
        filas = []
        for nivel in niveles_disponibles():
            capa = _capa(nivel)
            arbol = shapely.STRtree(capa["geoms"])
            ip, ig = arbol.query(pts, predicate="intersects")
            visto = set()
            for p, g in zip(ip, ig, strict=True):
                if p in visto:  # un punto en el borde de dos unidades: la primera
                    continue
                visto.add(p)
                filas.append(
                    (
                        nivel,
                        capa["features"][g]["properties"]["codigo"],
                        float(celdas.at[p, "cell_lat"]),
                        float(celdas.at[p, "cell_lon"]),
                    )
                )
        df = pd.DataFrame(filas, columns=["nivel", "codigo", "alat", "alon"])
        con.register("_amb_tmp", df)
        con.execute("CREATE OR REPLACE TABLE ambito_celdas AS SELECT * FROM _amb_tmp")
        con.unregister("_amb_tmp")
        _Cache.tipos = {}
        _Cache.stamp = clave


# ------------------------------------------------------------------ tipificación
def tipificar(store: PlanStore, nivel: str) -> pd.DataFrame:
    """Una fila por unidad del nivel: parámetros, índice, nivel de peligro y puesto."""
    _preparar(store)
    if nivel in _Cache.tipos:
        return _Cache.tipos[nivel]
    capa = _capa(nivel)
    cur = store.cursor()
    anual = cur.execute(
        "SELECT a.codigo, c.anio, sum(c.eq_hotspots) AS n FROM cd c JOIN ambito_celdas a "
        "ON a.alat = c.cell_lat AND a.alon = c.cell_lon "
        "WHERE a.nivel = ? AND c.anio BETWEEN ? AND ? GROUP BY 1, 2",
        [nivel, *REF],
    ).df()
    rec = cur.execute(
        "SELECT codigo, count(*) FILTER (WHERE anios >= ?) AS lugares FROM ("
        " SELECT a.codigo, c.cell_lat, c.cell_lon, count(DISTINCT c.anio) AS anios "
        " FROM cd c JOIN ambito_celdas a ON a.alat = c.cell_lat AND a.alon = c.cell_lon "
        " WHERE a.nivel = ? AND c.anio BETWEEN ? AND ? GROUP BY 1, 2, 3) GROUP BY 1",
        [RECURRENTE_MIN_ANIOS, nivel, RECURRENCIA_DESDE, REF[1]],
    ).df()
    cur.close()
    anios = list(range(REF[0], REF[1] + 1))
    tabla = anual.pivot_table(
        index="codigo", columns="anio", values="n", aggfunc="sum", fill_value=0.0
    ).reindex(columns=anios, fill_value=0.0)
    props = pd.DataFrame([f["properties"] for f in capa["features"]]).set_index("codigo")
    tabla = tabla.reindex(props.index, fill_value=0.0)
    area = props["area_km2"].astype(float)
    df = pd.DataFrame(
        {
            "nombre": props["nombre"],
            "provincia": props.get("provincia"),
            "area_km2": area,
            "media_anual": tabla.mean(axis=1),
            "anio_max": tabla.idxmax(axis=1).where(tabla.max(axis=1) > 0),
            "max_anual": tabla.max(axis=1),
            "ultimo_anio": tabla[REF[1]],
            "lugares_recurrentes": rec.set_index("codigo")["lugares"]
            .reindex(props.index)
            .fillna(0),
        }
    )
    df["densidad"] = df["media_anual"] / area * 100
    df["recurrencia"] = df["lugares_recurrentes"] / area * 100
    df["extremo"] = df["max_anual"] / area * 100
    pesos, _ = pesos_ahp()
    ok = df["area_km2"] >= MIN_AREA_KM2
    n = int(ok.sum())
    df["indice"] = np.nan
    df["nivel_peligro"] = "sin_clasificar"
    if n >= MIN_UNIDADES:
        sub = df[ok]
        pct = {p: (sub[p].rank(method="min") - 1) / (n - 1) for p in PARAMETROS}
        df.loc[ok, "indice"] = sum(pesos[p] * pct[p] for p in PARAMETROS)
        df.loc[ok, "nivel_peligro"] = [
            clasificar(i, f)
            for i, f in zip(df.loc[ok, "indice"], sub["media_anual"] > 0, strict=True)
        ]
    df["puesto"] = df["indice"].rank(ascending=False, method="min")
    df["serie"] = [tabla.loc[c].round(2).tolist() for c in df.index]
    _Cache.tipos[nivel] = df
    return df


def definiciones() -> dict:
    """Definiciones técnicas de la unidad de medida (se muestran en la API y en cada informe)."""
    return {
        "foco_de_calor": t(
            es="Foco de calor (anomalía térmica activa, «hotspot»): píxel en el que el algoritmo "
               "de "
            "detección de fuegos activos del sensor encuentra, en el momento del paso del "
            "satélite, "
            "una emisión en el infrarrojo medio (~4 µm) claramente mayor que la de su entorno "
            "(prueba contextual con las bandas de ~4 y ~11 µm). Productos: MODIS Colección 6.1 "
            "(MOD14/MYD14, píxel de ~1 km, satélites Terra y Aqua) y VIIRS 375 m (VNP14IMG en "
            "S-NPP, VJ114IMG en NOAA-20), distribuidos por NASA FIRMS. Cada registro trae la "
            "posición del centro del píxel, la fecha y hora UTC, la confianza y la potencia "
            "radiativa. Puede corresponder a un incendio de vegetación, a una quema agrícola o de "
            "pastos o a otra fuente caliente: no indica la causa, el tamaño del área quemada ni el "
            "número de incendios. Aquí se usan solo los focos clasificados como vegetación "
            "(type = 0), con confianza MODIS ≥ 30 o VIIRS nominal/alta.",
            en="Hotspot (active thermal anomaly): a pixel in which the sensor's active fire "
            "detection algorithm finds, at the time of the satellite overpass, a mid-infrared "
            "(~4 µm) emission clearly higher than its surroundings (contextual test with the ~4 "
            "and ~11 µm bands). Products: MODIS Collection 6.1 (MOD14/MYD14, ~1 km pixel, Terra "
            "and Aqua satellites) and VIIRS 375 m (VNP14IMG on S-NPP, VJ114IMG on NOAA-20), "
            "distributed by NASA FIRMS. Each record gives the pixel-centre position, UTC date "
            "and time, confidence and radiative power. It may be a vegetation fire, an "
            "agricultural or pasture burn, or another hot source: it does not tell the cause, the "
            "burned area or the number of fires. Only hotspots classified as vegetation "
            "(type = 0) are used, with MODIS confidence ≥ 30 or VIIRS nominal/high.",
        ),
        "foco_armonizado": t(
            es="Foco de calor armonizado: celda de 0,01° (~1,1 km) con al menos un foco de calor "
            "en un día local (UTC−5), expresada en la escala de MODIS para que el sensor de origen "
            "no cambie la serie: MODIS vale 1; VIIRS se multiplica por k (0,330 sobre 2500 m y "
            "0,247 debajo; NOAA-20: 0,324 y 0,235); Terra antes de julio de 2002, por kT.",
            en="Harmonized hotspot: a 0.01° (~1.1 km) cell with at least one hotspot on a local "
            "day (UTC−5), expressed on the MODIS scale so the source sensor does not change the "
            "series: MODIS counts 1; VIIRS is multiplied by k (0.330 above 2500 m and 0.247 "
            "below; NOAA-20: 0.324 and 0.235); Terra before July 2002, by kT.",
        ),
        "nivel_de_peligro": t(
            es="Nivel de peligro por focos de calor: posición relativa de la unidad entre las de "
            "su mismo nivel dentro de Cusco, según la densidad media, la recurrencia y el año más "
            "activo de focos de calor armonizados, clasificada en los cuatro niveles de CENEPRED "
            "(muy alto, alto, medio, bajo).",
            en="Hotspot hazard level: the unit's relative position among the units of the same "
            "level within Cusco, by mean density, recurrence and most active year of harmonized "
            "hotspots, classified into CENEPRED's four levels (very high, high, medium, low).",
        ),
    }


def metodo() -> dict:
    pesos, cr = pesos_ahp()
    return {
        "definiciones": definiciones(),
        "parametros": {
            "densidad": t(
                es="focos de calor armonizados por año (media 2003-2025) por 100 km²",
                en="harmonized hotspots per year (2003-2025 mean) per 100 km²",
            ),
            "recurrencia": t(
                es="lugares de ~1 km que ardieron en 4 o más de los 13 años con VIIRS "
                "(2013-2025), por 100 km²",
                en="~1 km places that burned in 4 or more of the 13 VIIRS years "
                "(2013-2025), per 100 km²",
            ),
            "extremo": t(
                es="focos de calor armonizados del año más activo por 100 km²",
                en="harmonized hotspots in the most active year per 100 km²",
            ),
        },
        "pesos": pesos,
        "matriz_saaty": SAATY,
        "razon_consistencia": cr,
        "consistente": cr < 0.10,
        "umbrales": {etiqueta(n): u for u, n in UMBRALES},
        "notas": [
            t(
                es="Nivel de peligro relativo: compara las unidades de un mismo nivel dentro de "
                "Cusco, en el "
                "formato de cuatro niveles de CENEPRED.",
                en="Relative hazard level: compares the units of one level within Cusco, in "
                "CENEPRED's "
                "four-level format.",
            ),
            t(
                es="No incluye vulnerabilidad (población, viviendas, cobertura, servicios): es un "
                "insumo para "
                "la evaluación de CENEPRED, no la reemplaza.",
                en="It does not include vulnerability (population, housing, land cover, services):"
                " it is an "
                "input to CENEPRED's assessment, not a replacement.",
            ),
            t(
                es="Describe lo que ya ocurrió según los satélites; no es un pronóstico. Un foco "
                "no es un "
                "incendio ni un área quemada.",
                en="It describes what satellites already observed; it is not a forecast. A hotspot"
                " is not "
                "a fire or a burned area.",
            ),
            t(
                es=f"No se clasifican las unidades con menos de {MIN_AREA_KM2:.0f} km² dentro de "
                f"Cusco "
                "(recortes en el borde), ni los niveles con menos de 4 unidades.",
                en=f"Units with less than {MIN_AREA_KM2:.0f} km² inside Cusco (edge slivers) and "
                f"levels "
                "with fewer than 4 units are not classified.",
            ),
            t(
                es="Los pesos son una propuesta inicial: deben validarse con especialistas y con "
                "CENEPRED.",
                en="The weights are an initial proposal: they must be validated with specialists "
                "and "
                "CENEPRED.",
            ),
        ],
    }


def _num(x, d: int = 2):
    return None if pd.isna(x) else round(float(x), d)


def _fila(codigo: str, r) -> dict:
    num = _num
    return {
        "codigo": codigo,
        "nombre": r.nombre,
        **({"provincia": r.provincia} if isinstance(r.provincia, str) else {}),
        "area_km2": num(r.area_km2, 1),
        "media_anual": num(r.media_anual, 1),
        "densidad": num(r.densidad, 3),
        "lugares_recurrentes": int(r.lugares_recurrentes),
        "recurrencia": num(r.recurrencia, 3),
        "anio_max": None if pd.isna(r.anio_max) else int(r.anio_max),
        "max_anual": num(r.max_anual, 1),
        "extremo": num(r.extremo, 3),
        f"total_{REF[1]}": num(r.ultimo_anio, 1),
        "indice": num(r.indice, 3),
        "con_focos": bool(r.media_anual > 0),
        "nivel_peligro": r.nivel_peligro,
        "etiqueta": etiqueta(r.nivel_peligro),
        "color": COLOR[r.nivel_peligro],
        "puesto": None if pd.isna(r.puesto) else int(r.puesto),
    }


def resumen_nivel(store: PlanStore, nivel: str) -> dict:
    df = tipificar(store, nivel)
    capa = _capa(nivel)
    unidades = [
        _fila(c, r) for c, r in df.sort_values(["indice", "densidad"], ascending=False).iterrows()
    ]
    conteo = df["nivel_peligro"].value_counts().to_dict()
    cur = store.cursor()
    total = cur.execute(
        "SELECT sum(eq_hotspots) FROM cd WHERE anio BETWEEN ? AND ?", list(REF)
    ).fetchall()[0][0]
    cur.close()
    cobertura = float(df["media_anual"].sum() * (REF[1] - REF[0] + 1) / total) if total else None
    return {
        "nivel": nivel,
        "titulo": titulo_nivel(nivel),
        "fuente": capa["fuente"],
        "n_unidades": len(df),
        # Parte de los focos de calor de Cusco 2003-2025 que cae dentro de las unidades del nivel
        # (las celdas del
        # borde pueden quedar fuera de los límites de INEI, que no coinciden con los de FAO GAUL).
        "cobertura": None if cobertura is None else round(cobertura, 4),
        "conteo": {etiqueta(k): int(v) for k, v in conteo.items()},
        "metodo": metodo(),
        "unidades": unidades,
    }


# ------------------------------------------------------------------ distribución por día del año
ORDEN_PELIGRO = ("muy_alto", "alto", "medio", "bajo", "sin_clasificar")
VENTANAS = (1, 7, 15, 31)  # días del promedio móvil (1 = sin suavizar)


def dia_del_anio(fechas) -> np.ndarray:
    """Día 1-365 en un calendario sin bisiestos: el 29 de febrero se suma al 28 (día 59)."""
    f = pd.to_datetime(pd.Series(fechas))
    d = f.dt.day_of_year.to_numpy()
    corre = f.dt.is_leap_year.to_numpy() & (
        (f.dt.month.to_numpy() > 2) | ((f.dt.month.to_numpy() == 2) & (f.dt.day.to_numpy() == 29))
    )
    return d - corre


def _fecha_dia(dia: int) -> str:
    f = pd.Timestamp(2001, 1, 1) + pd.Timedelta(days=int(dia) - 1)
    return t(es=f"{f.day} de {month_name(f.month)}", en=f"{month_name(f.month)} {f.day}")


def _suavizar(tabla: pd.DataFrame, ventana: int) -> pd.DataFrame:
    """Promedio móvil centrado y circular: diciembre empalma con enero, y la suma se conserva."""
    if ventana <= 1:
        return tabla
    h = ventana // 2
    ext = pd.concat([tabla.iloc[-h:], tabla, tabla.iloc[:h]])
    out = ext.rolling(ventana, center=True).mean().iloc[h : h + len(tabla)]
    out.index = tabla.index
    return out


def _percentil_dia(serie: pd.Series, q: float) -> int | None:
    total = float(serie.sum())
    if total <= 0:
        return None
    return int(serie.index[int(np.searchsorted(serie.cumsum().to_numpy(), q * total))])


def distribucion_diaria(
    store: PlanStore, nivel: str, desde: int = REF[0], hasta: int = REF[1], ventana: int = 7
) -> dict:
    """Focos armonizados por día del año, según el nivel de peligro de la unidad donde ocurren.

    Cálculo dinámico (nada precalculado): 1) se tipifican las unidades del nivel (``tipificar``);
    2) cada celda-día de la serie se asigna a su unidad y toma su nivel de peligro; 3) se suma por
    día del año (calendario sin bisiestos) en los años elegidos y se divide por el número de años
    (focos armonizados por año en ese día); 4) se suaviza con un promedio móvil circular.
    """
    _validar_dias(desde, hasta, ventana)
    tipos = tipificar(store, nivel)
    cur = store.cursor()
    df = cur.execute(
        "SELECT a.codigo, c.fecha_local, sum(c.eq_hotspots) AS n FROM cd c JOIN ambito_celdas a "
        "ON a.alat = c.cell_lat AND a.alon = c.cell_lon "
        "WHERE a.nivel = ? AND c.anio BETWEEN ? AND ? GROUP BY 1, 2",
        [nivel, desde, hasta],
    ).df()
    cur.close()
    n_anios = hasta - desde + 1
    presentes = [p for p in ORDEN_PELIGRO if (tipos["nivel_peligro"] == p).any()]
    df["peligro"] = df["codigo"].map(tipos["nivel_peligro"]).fillna("sin_clasificar")
    df["dia"] = dia_del_anio(df["fecha_local"]) if len(df) else []
    dias = pd.RangeIndex(1, 366, name="dia")
    bruto = (
        df.pivot_table(index="dia", columns="peligro", values="n", aggfunc="sum", fill_value=0.0)
        .reindex(index=dias, columns=presentes, fill_value=0.0)
        / n_anios
    )
    suave = _suavizar(bruto, ventana)
    total_dia = suave.sum(axis=1)
    total = float(bruto.to_numpy().sum())

    niveles = []
    for p in presentes:
        u = tipos[tipos["nivel_peligro"] == p]
        area = float(u["area_km2"].sum())
        por_anio = float(bruto[p].sum())
        pico = int(suave[p].idxmax()) if por_anio > 0 else None
        p10, p50, p90 = (_percentil_dia(bruto[p], q) for q in (0.1, 0.5, 0.9))
        niveles.append(
            {
                "nivel_peligro": p,
                "etiqueta": etiqueta(p),
                "color": COLOR[p],
                "unidades": len(u),
                "area_km2": round(area, 1),
                "focos_por_anio": round(por_anio, 2),
                "parte": round(por_anio / total, 4) if total else 0.0,
                "densidad": round(por_anio / area * 100, 3) if area else None,
                "dia_pico": pico,
                "fecha_pico": _fecha_dia(pico) if pico else None,
                "dia_p10": p10,
                "dia_p50": p50,
                "dia_p90": p90,
                "temporada_central": (
                    None
                    if not (p10 and p90)
                    else t(es=f"el {_fecha_dia(p10)}", en=f"on {_fecha_dia(p10)}")
                    if p10 == p90
                    else t(
                        es=f"del {_fecha_dia(p10)} al {_fecha_dia(p90)}",
                        en=f"{_fecha_dia(p10)} to {_fecha_dia(p90)}",
                    )
                ),
            }
        )

    filas = [
        {
            "dia": int(d),
            "fecha": (pd.Timestamp(2001, 1, 1) + pd.Timedelta(days=int(d) - 1)).strftime("%m-%d"),
            "total": round(float(total_dia.loc[d]), 4),
            **{p: round(float(suave.at[d, p]), 4) for p in presentes},
        }
        for d in dias
    ]
    con_focos = [n for n in niveles if n["focos_por_anio"] > 0]
    anios_txt = str(desde) if desde == hasta else f"{desde}-{hasta}"
    top = max(con_focos, key=lambda n: n["parte"], default=None)
    if top:
        en_simple = t(
            es=f"Las unidades de peligro {top['etiqueta'].lower()} "
            f"({top['unidades']} de {len(tipos)}) reúnen el {round(100 * top['parte'])} % de los "
            f"focos de calor de {anios_txt}. El 80 % de sus focos ocurre "
            f"{top['temporada_central']}, con el pico el {top['fecha_pico']}.",
            en=f"Units with {top['etiqueta'].lower()} hazard ({top['unidades']} of {len(tipos)}) "
            f"hold {round(100 * top['parte'])}% of the hotspots in {anios_txt}. 80% of their "
            f"hotspots occur from {top['temporada_central']}, peaking on {top['fecha_pico']}.",
        )
    else:
        en_simple = t(
            es="Sin focos de calor en los años elegidos.", en="No hotspots in the chosen years."
        )
    return {
        "nivel": nivel,
        "titulo": t(
            es="Focos de calor por día del año según el nivel de peligro "
            f"({titulo_nivel(nivel).lower()})",
            en=f"Hotspots by day of year by hazard level ({titulo_nivel(nivel).lower()})",
        ),
        "desde": desde,
        "hasta": hasta,
        "anios": n_anios,
        "ventana": ventana,
        "ventanas": list(VENTANAS),
        "unidad": t(
            es="focos armonizados por año en ese día (promedio de los años elegidos)",
            en="harmonized hotspots per year on that day (average of the chosen years)",
        ),
        "en_simple": en_simple,
        "como_leerlo": t(
            es="Cada día del año suma los focos de calor de todos los años elegidos, separados "
            "por el nivel de peligro de la provincia, distrito o cuenca donde ocurrieron, y se "
            "divide por el número de años. La curva se suaviza con un promedio móvil de la "
            "ventana elegida.",
            en="Each day of the year adds up the hotspots of all the chosen years, split by the "
            "hazard level of the province, district or basin where they occurred, divided by the "
            "number of years. The curve is smoothed with a moving average of the chosen window.",
        ),
        "niveles": niveles,
        "dias": filas,
        "metodo": metodo(),
    }


def _validar_dias(desde: int, hasta: int, ventana: int) -> None:
    if not (REF[0] <= desde <= hasta <= REF[1]):
        raise PlanError(
            t(
                es=f"Años no válidos: elige 'desde' y 'hasta' entre {REF[0]} y {REF[1]}, "
                "con desde ≤ hasta.",
                en=f"Invalid years: choose 'desde' and 'hasta' between {REF[0]} and {REF[1]}, "
                "with desde ≤ hasta.",
            )
        )
    if ventana not in VENTANAS:
        raise PlanError(
            t(
                es=f"Ventana no válida: usa {', '.join(map(str, VENTANAS))} días.",
                en=f"Invalid window: use {', '.join(map(str, VENTANAS))} days.",
            )
        )


# Día del año en SQL (DuckDB), con el mismo calendario sin bisiestos que dia_del_anio().
_DIA_SQL = (
    "dayofyear(CAST(c.fecha_local AS DATE)) - CASE WHEN (c.anio % 4 = 0 AND (c.anio % 100 <> 0 "
    "OR c.anio % 400 = 0)) AND (month(CAST(c.fecha_local AS DATE)) > 2 OR (month(CAST("
    "c.fecha_local AS DATE)) = 2 AND day(CAST(c.fecha_local AS DATE)) = 29)) THEN 1 ELSE 0 END"
)


def celdas_dia(
    store: PlanStore,
    nivel: str,
    dia: int,
    desde: int = REF[0],
    hasta: int = REF[1],
    ventana: int = 7,
) -> dict:
    """Celdas con focos en un día del año (± media ventana, circular), sumando los años elegidos.

    Es lo que el mapa muestra al elegir un día en el gráfico de ``distribucion_diaria``: cada celda
    lleva su unidad y el nivel de peligro de esa unidad; su valor son los focos armonizados por año
    en esos días (suma de los años / número de años).
    """
    _validar_dias(desde, hasta, ventana)
    if not 1 <= dia <= 365:
        raise PlanError(t(es="Día no válido: usa un número entre 1 y 365.",
                          en="Invalid day: use a number between 1 and 365."))
    tipos = tipificar(store, nivel)
    h = ventana // 2
    dias = sorted({(dia - 1 + k) % 365 + 1 for k in range(-h, h + 1)})
    cur = store.cursor()
    df = cur.execute(
        f"WITH x AS (SELECT c.cell_lat, c.cell_lon, c.eq_hotspots, a.codigo, {_DIA_SQL} AS dia "
        "FROM cd c JOIN ambito_celdas a ON a.alat = c.cell_lat AND a.alon = c.cell_lon "
        "WHERE a.nivel = ? AND c.anio BETWEEN ? AND ?) "
        "SELECT cell_lat, cell_lon, codigo, sum(eq_hotspots) AS n FROM x "
        "WHERE list_contains(?, dia) GROUP BY 1, 2, 3",
        [nivel, desde, hasta, dias],
    ).df()
    cur.close()
    n_anios = hasta - desde + 1
    df["n"] = df["n"] / n_anios
    df["peligro"] = df["codigo"].map(tipos["nivel_peligro"]).fillna("sin_clasificar")
    por_nivel = df.groupby("peligro")["n"].sum()
    ini, fin = dias[0] if h == 0 else (dia - 1 - h) % 365 + 1, (dia - 1 + h) % 365 + 1
    return {
        "nivel": nivel,
        "dia": dia,
        "fecha": _fecha_dia(dia),
        "desde": desde,
        "hasta": hasta,
        "ventana": ventana,
        "dias": t(es=f"del {_fecha_dia(ini)} al {_fecha_dia(fin)}",
                  en=f"{_fecha_dia(ini)} to {_fecha_dia(fin)}") if h else _fecha_dia(dia),
        "total": round(float(df["n"].sum()), 3),
        "por_nivel": [
            {"nivel_peligro": p, "etiqueta": etiqueta(p), "color": COLOR[p],
             "focos": round(float(por_nivel.get(p, 0.0)), 3)}
            for p in ORDEN_PELIGRO if p in por_nivel.index or (tipos["nivel_peligro"] == p).any()
        ],
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {"type": "Point",
                                 "coordinates": [round(r.cell_lon, 3), round(r.cell_lat, 3)]},
                    "properties": {"n": round(float(r.n), 3), "codigo": r.codigo,
                                   "nivel_peligro": r.peligro, "color": COLOR[r.peligro]},
                }
                for r in df.itertuples()
            ],
        },
        "unidad": t(es="focos armonizados por año en esos días",
                    en="harmonized hotspots per year on those days"),
    }


def geojson_nivel(store: PlanStore, nivel: str) -> dict:
    df = tipificar(store, nivel)
    capa = _capa(nivel)
    feats = [
        {
            "type": "Feature",
            "geometry": f["geometry"],
            "properties": _fila(f["properties"]["codigo"], df.loc[f["properties"]["codigo"]]),
        }
        for f in capa["features"]
    ]
    return {
        "type": "FeatureCollection",
        "nivel": nivel,
        "titulo": titulo_nivel(nivel),
        "fuente": capa["fuente"],
        "features": feats,
    }


def csv_nivel(store: PlanStore, nivel: str) -> str:
    filas = resumen_nivel(store, nivel)["unidades"]
    cols = [
        "puesto",
        "codigo",
        "nombre",
        "provincia",
        "area_km2",
        "media_anual",
        "densidad",
        "lugares_recurrentes",
        "recurrencia",
        "anio_max",
        "max_anual",
        "extremo",
        f"total_{REF[1]}",
        "indice",
        "nivel_peligro",
        "etiqueta",
    ]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore", lineterminator="\n")
    w.writeheader()
    w.writerows(filas)
    return "﻿" + buf.getvalue()


def aoi_unidad(store: PlanStore, nivel: str, codigo: str) -> AOI:
    df = tipificar(store, nivel)
    if codigo not in df.index:
        raise PlanNoData(
            t(
                es=f"No existe la unidad '{codigo}' en el ámbito '{nivel}'.",
                en=f"Unit '{codigo}' does not exist in scope '{nivel}'.",
            )
        )
    r = df.loc[codigo]
    return AOI(
        kind=nivel,
        label=str(r.nombre),
        area_km2=float(r.area_km2),
        params=(nivel, codigo),
        sql="EXISTS (SELECT 1 FROM ambito_celdas WHERE nivel = ? AND codigo = ? "
        "AND alat = cell_lat AND alon = cell_lon)",
    )


def detalle(store: PlanStore, nivel: str, codigo: str) -> dict:
    from firecal.plan import analitica

    aoi = aoi_unidad(store, nivel, codigo)
    df = tipificar(store, nivel)
    fila = _fila(codigo, df.loc[codigo])
    med = {p: round(float(df[p].median()), 3) for p in PARAMETROS}
    try:
        frases = analitica.resumen(store, aoi)["frases"]
    except (PlanNoData, PlanError):
        frases = []
    return {
        "nivel": nivel,
        "titulo_nivel": titulo_nivel(nivel),
        "unidad": fila,
        "n_unidades": len(df),
        "mediana_del_nivel": med,
        "frases": frases,
        "serie_anual": dict(zip(range(REF[0], REF[1] + 1), df.loc[codigo, "serie"], strict=True)),
        "metodo": metodo(),
        "aoi": aoi,
    }


# ------------------------------------------------------------------ informe (HTML imprimible)
def _svg_barras(
    valores: list[float],
    etiquetas: list[str],
    resaltar: int | None,
    alto=150,
    ancho=620,
    color="#31688e",
) -> str:
    if not valores or max(valores) <= 0:
        return ""
    m = max(valores)
    n = len(valores)
    bw = (ancho - 40) / n
    barras = []
    for i, (v, e) in enumerate(zip(valores, etiquetas, strict=True)):
        h = (alto - 30) * v / m
        x = 30 + i * bw
        c = "#c2410c" if i == resaltar else color
        barras.append(
            f'<rect x="{x + 1:.1f}" y="{alto - 20 - h:.1f}" width="{bw - 2:.1f}" '
            f'height="{h:.1f}" fill="{c}"><title>{html.escape(e)}: {v:,.1f}</title></rect>'
        )
        if n <= 12 or i % 5 == 0:
            barras.append(
                f'<text x="{x + bw / 2:.1f}" y="{alto - 6}" font-size="10" '
                f'text-anchor="middle">{html.escape(e)}</text>'
            )
    return (
        f'<svg viewBox="0 0 {ancho} {alto}" width="100%" role="img" '
        f'font-family="system-ui, sans-serif"><text x="2" y="12" font-size="10">{m:,.0f}</text>'
        f'<line x1="28" x2="{ancho}" y1="{alto - 20}" y2="{alto - 20}" stroke="#98a2b3"/>'
        + "".join(barras)
        + "</svg>"
    )


CATEGORIAS = {
    "muy por debajo": ("Muy por debajo de lo habitual", "Well below usual", "#2166ac"),
    "por debajo": ("Por debajo de lo habitual", "Below usual", "#67a9cf"),
    "normal": ("Dentro de lo habitual", "Within usual", "#98a2b3"),
    "por encima": ("Por encima de lo habitual", "Above usual", "#e66101"),
    "muy por encima": ("Muy por encima de lo habitual", "Well above usual", "#b2182b"),
    "incierta": ("Incierta (el margen de error cruza de categoría)", "Uncertain (the error margin "
                 "crosses categories)", "#98a2b3"),
}


def seccion_mes(store: PlanStore, aoi: AOI, mes: str) -> str:
    """Sección del informe para un mes: valor, mediana histórica, anomalía, puesto y días."""
    esc = html.escape
    a = store.anomaly(aoi, mes)
    y, m = (int(x) for x in a["mes"].split("-"))
    nombre_mes = t(es=["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
                       "septiembre", "octubre", "noviembre", "diciembre"][m - 1],
                   en=["January", "February", "March", "April", "May", "June", "July", "August",
                       "September", "October", "November", "December"][m - 1])
    valor = a["focos_armonizados"] or 0.0
    med = a["mediana_hist"]
    cat = a["categoria"]
    es_, en_, color = CATEGORIAS.get(cat, ("Sin categoría", "No category", "#98a2b3"))
    hist = sorted(a["historial"], key=lambda h: h["anio"])
    valores = [h["focos_armonizados"] or 0.0 for h in hist]
    puesto = 1 + sum(v > valor for v in valores)
    propio = 1 if any(h["anio"] == y for h in hist) else 0
    empates = sum(abs(v - valor) < 0.005 for v in valores) - propio
    svg_hist = _svg_barras(valores, [str(h["anio"]) for h in hist],
                           next((i for i, h in enumerate(hist) if h["anio"] == y), None))
    dias = a["dias"]
    n_dias = 31 if m in (1, 3, 5, 7, 8, 10, 12) else 30 if m != 2 else 29 if y % 4 == 0 else 28
    por_dia = {int(x["fecha_local"][8:10]): x["focos_armonizados"] or 0.0 for x in dias}
    svg_dias = _svg_barras([por_dia.get(i, 0.0) for i in range(1, n_dias + 1)],
                           [str(i) for i in range(1, n_dias + 1)],
                           max(por_dia, key=por_dia.get) - 1 if por_dia else None,
                           color="#5d6677")
    if valor <= 0:
        es_, en_, color = ("Sin focos de calor", "No hotspots", "#98a2b3")
        if not med:
            comparacion = t(
                es=f"Tampoco suele haberlos: la mediana de {nombre_mes} en otros años es 0.",
                en=f"There usually are none either: the {nombre_mes} median in other years is 0.")
        else:
            comparacion = t(
                es=f"Es poco común: la mediana de {nombre_mes} en otros años es {med:,.1f}.",
                en=f"This is unusual: the {nombre_mes} median in other years is {med:,.1f}.")
    elif med is None:
        comparacion = t(es="No hay historia suficiente para compararlo.",
                        en="There is not enough history to compare it.")
    elif med > 0:
        comparacion = t(es=f"La mediana de {nombre_mes} en otros años es {med:,.1f}: este mes tuvo "
                           f"{valor / med:.1f} veces lo habitual.",
                        en=f"The {nombre_mes} median in other years is {med:,.1f}: this month had "
                           f"{valor / med:.1f} times the usual.")
    else:
        comparacion = t(es=f"La mediana de {nombre_mes} en otros años es 0.",
                        en=f"The {nombre_mes} median in other years is 0.")
    dia_max = (max(por_dia, key=por_dia.get), max(por_dia.values())) if por_dia else None
    texto_dias = (t(es=f"{len(por_dia)} días con focos de calor; el más activo fue el "
                       f"{dia_max[0]} de {nombre_mes} ({dia_max[1]:,.1f}).",
                    en=f"{len(por_dia)} days with hotspots; the most active was {nombre_mes} "
                       f"{dia_max[0]} ({dia_max[1]:,.1f}).")
                  if dia_max else t(es="Ningún día con focos de calor.",
                                    en="No day with hotspots."))
    margen = ""
    if a.get("incertidumbre"):
        lo, hi = a["rango"]
        margen = t(es=f" Margen por datos extrapolados: entre {lo:,.1f} y {hi:,.1f}.",
                   en=f" Margin from extrapolated data: between {lo:,.1f} and {hi:,.1f}.")
    notas = "".join(f"<li>{esc(n)}</li>" for n in a["notes"])
    texto_puesto = ""
    if valor > 0 and hist:
        texto_puesto = esc(t(
            es=f"Puesto {puesto} de {len(hist)} entre los meses de {nombre_mes} con historia"
               + (f" (empatado con {empates})" if empates > 0 else "") + ".",
            en=f"Rank {puesto} of {len(hist)} among {nombre_mes} months with history"
               + (f" (tied with {empates})" if empates > 0 else "") + "."))
    anom_txt = ""
    if valor > 0 and a["anomalia"] is not None:
        anom_txt = t(es=f" (anomalía {a['anomalia']:+.2f})", en=f" (anomaly {a['anomalia']:+.2f})")
    return f"""
<h2>{esc(t(es=f"Situación de {nombre_mes} de {y}", en=f"{nombre_mes} {y} at a glance"))}</h2>
<div class="nivel"><span class="badge" style="background:{color}">{('0' if valor <= 0 else f'{valor:,.1f}')}</span>
<div>{esc(t(es="focos de calor armonizados", en="harmonized hotspots"))} ·
<b>{esc(t(es=es_, en=en_))}</b>{esc(anom_txt)}.
{esc(comparacion)}{esc(margen)}
{texto_puesto}</div></div>
<p class="nota">MODIS {a["focos_modis"]} · VIIRS {a["focos_viirs"]}
{esc(t(es="focos de calor detectados (sensores distintos: no se suman)",
       en="hotspots detected (different sensors: not added)"))}.</p>
{f'<h3>{esc(t(es=f"{nombre_mes.capitalize()} en cada año", en=f"{nombre_mes} in each year"))}</h3>' if svg_hist else ""}
{svg_hist}
{f'<h3>{esc(t(es="Día por día", en="Day by day"))}</h3>' if svg_dias else ""}
{svg_dias}<p>{esc(texto_dias)}</p>
{f"<ul class='nota'>{notas}</ul>" if notas else ""}
"""  # noqa: E501 - plantilla HTML


def informe_html(store: PlanStore, nivel: str, codigo: str, mes: str | None = None) -> str:
    d = detalle(store, nivel, codigo)
    bloque_mes = seccion_mes(store, d["aoi"], mes) if mes else ""
    u, med = d["unidad"], d["mediana_del_nivel"]
    esc = html.escape
    meses = ["E", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    from firecal.plan import analitica

    try:
        est = analitica.estacionalidad(store, d["aoi"])
        svg_mes = _svg_barras([m["mediana"] for m in est["meses"]], meses, est["mes_pico"] - 1)
    except (PlanNoData, PlanError):
        svg_mes = ""
    serie = d["serie_anual"]
    anios = list(serie)
    svg_anio = _svg_barras(
        list(serie.values()),
        [str(a) for a in anios],
        anios.index(u["anio_max"]) if u["anio_max"] in anios else None,
    )
    nombre_nivel = d["titulo_nivel"]
    # La frase ya está en "En simple": la sección solo se muestra si hay gráfico.
    bloque_estacional = (
        "<h2>" + esc(t(es="¿Cuándo hay más focos de calor?", en="When are there more hotspots?"))
        + "</h2>" + svg_mes
        if svg_mes
        else ""
    )
    aviso_pocos = ""
    if (u["media_anual"] or 0) < 1:
        aviso_pocos = "<br><b>" + esc(t(
            es="Muy pocos focos de calor (menos de 1 por año en promedio): el nivel, las frases y "
               "los gráficos son poco robustos.",
            en="Very few hotspots (less than 1 per year on average): the level, sentences and "
               "charts are not robust.")) + "</b>"
    puesto = (
        t(
            es=f"puesto {u['puesto']} de {d['n_unidades']}",
            en=f"rank {u['puesto']} of {d['n_unidades']}",
        )
        if u["puesto"]
        else ""
    )

    def fila_param(nom: str, val: float, mediana: float, unidad: str) -> str:
        return (
            f"<tr><td>{esc(nom)}</td><td class=n>{val:,.2f}</td><td class=n>{mediana:,.2f}</td>"
            f"<td>{esc(unidad)}</td></tr>"
        )

    m = d["metodo"]
    frases = "".join(
        f"<dt>{esc(f['pregunta'])}</dt><dd>{esc(f['respuesta'])}</dd>" for f in d["frases"]
    )
    hoy = datetime.now(UTC).strftime("%Y-%m-%d")
    nombres_def = {
        "foco_de_calor": t(es="Foco de calor", en="Hotspot"),
        "foco_armonizado": t(es="Foco de calor armonizado", en="Harmonized hotspot"),
        "nivel_de_peligro": t(es="Nivel de peligro por focos de calor", en="Hotspot hazard level"),
    }
    defs = "".join(
        f"<dt>{esc(nombres_def[k])}</dt><dd>{esc(v)}</dd>" for k, v in m["definiciones"].items()
    )
    version = store.meta.get("plan_version", "")
    return f"""<!doctype html><html lang="{t(es="es", en="en")}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(t(es="Informe de focos de calor", en="Hotspot report"))} · {esc(u["nombre"])}</title>
<style>
body{{font:14px/1.45 system-ui,sans-serif;color:#1d2330;max-width:820px;margin:24px auto;padding:0 16px}}
h1{{font-size:22px;margin:0}} h2{{font-size:16px;margin:22px 0 6px;border-bottom:1px solid #e4e7ec}}
.sub{{color:#5d6677;margin:2px 0 14px}} .nivel{{display:flex;gap:14px;align-items:center;border:1px solid #e4e7ec;
border-radius:10px;padding:12px 14px}} .badge{{font-weight:700;font-size:18px;padding:8px 14px;border-radius:8px;
color:#fff;background:{u["color"]}}} table{{border-collapse:collapse;width:100%;font-size:13px}}
td,th{{border-bottom:1px solid #eef0f3;padding:4px 6px;text-align:left}} .n{{text-align:right}}
dt{{font-weight:600;margin-top:8px}} .defs dd{{font-size:13px}} dd{{margin:2px 0 0}} .nota{{color:#5d6677;font-size:12px}}
@media print{{body{{margin:0}} a{{color:inherit}}}}
</style></head><body>
<p class="nota">Nikal Cusco · {esc(t(es="Informe automático", en="Automated report"))} · {hoy} ·
{esc(t(es="datos", en="data"))} {esc(version)}</p>
<h1>{esc(u["nombre"])}</h1>
<p class="sub">{esc(nombre_nivel)} · {esc(t(es="código", en="code"))} {esc(u["codigo"])}
{
        (" · " + esc(t(es="provincia", en="province")) + " " + esc(u["provincia"]))
        if u.get("provincia")
        else ""
    }
· {u["area_km2"]:,.1f} km² {esc(t(es="dentro de Cusco", en="within Cusco"))}</p>

<p class="nota">{esc(t(es="Foco de calor: anomalía térmica detectada por satélite (MODIS, VIIRS; NASA "
                        "FIRMS). No es un incendio ni un área quemada. Definiciones técnicas "
                        "completas al final.",
                     en="Hotspot: a thermal anomaly detected by satellite (MODIS, VIIRS; NASA "
                        "FIRMS). It is not a fire or a burned area. Full technical definitions at "
                        "the end."))}</p>

<h2>{
        esc(
            t(
                es="Nivel de peligro por focos de calor (formato CENEPRED)",
                en="Hotspot hazard level (CENEPRED format)",
            )
        )
    }</h2>
<div class="nivel"><span class="badge">{esc(u["etiqueta"])}</span>
<div>{esc(puesto)} {esc(t(es="en", en="among"))} {esc(nombre_nivel.lower())} {
        esc(t(es="de Cusco", en="of Cusco"))
    }.
{esc(t(es="Índice", en="Index"))} {
        ("—" if u["indice"] is None else f"{u['indice']:.2f}")
    } (0–1).{aviso_pocos}</div></div>
<table><tr><th>{esc(t(es="Parámetro", en="Parameter"))}</th><th class=n>{
        esc(t(es="Esta unidad", en="This unit"))
    }</th>
<th class=n>{esc(t(es="Mediana del nivel", en="Level median"))}</th><th>{
        esc(t(es="Unidad", en="Unit"))
    }</th></tr>
{
        fila_param(
            t(es="Densidad media de focos de calor", en="Mean hotspot density"),
            u["densidad"],
            med["densidad"],
            t(
                es="focos de calor armonizados / 100 km² / año",
                en="harmonized hotspots / 100 km² / year",
            ),
        )
    }
{
        fila_param(
            t(es="Lugares recurrentes", en="Recurrent places"),
            u["recurrencia"],
            med["recurrencia"],
            t(es="lugares / 100 km² (2013–2025)", en="places / 100 km² (2013–2025)"),
        )
    }
{
        fila_param(
            t(es="Año más activo", en="Most active year"),
            u["extremo"],
            med["extremo"],
            t(es="focos de calor armonizados / 100 km²", en="harmonized hotspots / 100 km²"),
        )
    }
</table>
<p class="nota">{esc(t(es="Pesos", en="Weights"))}: {
        ", ".join(f"{k} {v}" for k, v in m["pesos"].items())
    }
(Saaty, {esc(t(es="razón de consistencia", en="consistency ratio"))} {m["razon_consistencia"]}).
{esc(" ".join(m["notas"][:2]))}</p>

{bloque_mes}
<h2>{esc(t(es="En simple", en="In plain words"))}</h2>
<dl>{
        frases
        or "<dd>"
        + esc(
            t(
                es="No se detectaron focos en esta unidad.",
                en="No hotspots were detected in this unit.",
            )
        )
        + "</dd>"
    }</dl>

{bloque_estacional}

<h2>{
        esc(
            t(
                es="Focos de calor armonizados por año (2003–2025)",
                en="Harmonized hotspots per year (2003–2025)",
            )
        )
    }</h2>
{svg_anio}
<p class="nota">{esc(unidad()["definicion"])}</p>

<h2>{esc(t(es="Método y límites", en="Method and limits"))}</h2>
<ul>{"".join(f"<li>{esc(x)}</li>" for x in m["notas"])}
<li>{
        esc(
            t(
                es="Serie armonizada MODIS + VIIRS de Cusco (METHODOLOGY.md), 2003–2025; solo Cusco.",
                en="Harmonized MODIS + VIIRS series for Cusco (METHODOLOGY.md), 2003–2025; Cusco only.",
            )
        )
    }</li>
<li>{esc(t(es="Límites del ámbito", en="Scope boundaries"))}: {
        esc(_capa(nivel)["fuente"])
    }.</li></ul>
<h2>{esc(t(es="Anexo: definiciones técnicas", en="Annex: technical definitions"))}</h2>
<dl class="defs">{defs}</dl>
<p class="nota">We acknowledge the use of data and/or imagery from NASA's FIRMS
(https://earthdata.nasa.gov/firms).</p>
</body></html>"""  # noqa: E501 - plantilla HTML

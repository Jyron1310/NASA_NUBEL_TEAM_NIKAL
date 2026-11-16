"""Analíticas sencillas sobre la serie armonizada de Cusco (``PlanStore``).

Cinco cálculos de sumas y percentiles, pensados para un gestor que no es especialista. Cada
resultado trae ``en_simple`` (una frase que se entiende sin gráfico) y ``como_leerlo`` (cómo
interpretar los números), además de los datos para dibujar.

- ``estacionalidad``: en qué meses se concentran los focos de calor.
- ``ranking``: qué años tuvieron más y menos focos de calor.
- ``acumulado``: cómo fue avanzando un año frente a lo normal.
- ``altitud``: a qué altitud ocurren los focos de calor.
- ``recurrencia``: qué lugares arden año tras año.

Límites (METHODOLOGY.md): se describen focos armonizados, no incendios ni área quemada; nada de
esto es un pronóstico. La historia de referencia son los años completos sin focos
extrapolados (2003 en adelante).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from firecal.i18n import join_list, month_name, t
from firecal.plan.query import (
    AOI,
    REFERENCIA_FROM,
    PlanError,
    PlanNoData,
    PlanStore,
    no_fire,
    note_2025,
    unidad,
)

# Parte del total anual que define la "temporada de focos de calor".
PARTE_TEMPORADA = 0.80
# La recurrencia se mide solo con VIIRS (desde 2013): MODIS localiza peor y marca menos celdas.
RECURRENCIA_DESDE = 2013
BANDAS_ALTITUD = [(None, 1500), (1500, 2500), (2500, 3500), (3500, None)]


def _banda(lo: int | None, hi: int | None) -> str:
    if lo is None:
        return t(es=f"menos de {hi:,} m", en=f"below {hi:,} m")
    if hi is None:
        return t(es=f"más de {lo:,} m", en=f"above {lo:,} m")
    return t(es=f"{lo:,} a {hi:,} m", en=f"{lo:,} to {hi:,} m")


def _sin_datos(label: str) -> str:
    return t(es=f"Sin datos: no hay focos armonizados en {label}.",
             en=f"No data: there are no harmonized hotspots in {label}.")


def _no_es_pronostico() -> str:
    return t(es="Describe lo que ya ocurrió según los satélites. No es un pronóstico ni mide "
                "incendios o área quemada.",
             en="Describes what already happened according to the satellites. It is not a "
                "forecast and does not measure wildfires or burned area.")


def _n(x: float) -> str:
    """Número para una frase: entero con separador de miles."""
    return f"{round(float(x)):,}"


def _focos(x: float) -> str:
    """'1 foco armonizado' / '12 focos armonizados' (QA de Erik, 10: plurales)."""
    n = round(float(x))
    return (t(es="1 foco armonizado", en="1 harmonized hotspot") if n == 1
            else t(es=f"{n:,} focos armonizados", en=f"{n:,} harmonized hotspots"))


def _lugares(x: float) -> str:
    n = round(float(x))
    return t(es="1 lugar", en="1 place") if n == 1 else t(es=f"{n:,} lugares", en=f"{n:,} places")


def _anios(n: int) -> str:
    return t(es="1 año", en="1 year") if n == 1 else t(es=f"{n} años", en=f"{n} years")


def _pct(x: float) -> str:
    return f"{round(100 * float(x))} %"


def _veces(valor: float, base: float) -> str:
    """Comparación en palabras: 'casi el doble de', '30 % más que', 'parecido a'..."""
    if base <= 0:
        return t(es="muy por encima de", en="far above")
    r = valor / base
    if r >= 2.75:
        return t(es=f"unas {round(r)} veces", en=f"about {round(r)} times")
    if r >= 1.85:
        return (t(es="cerca del doble de", en="nearly double") if r < 2.25
                else t(es="más del doble de", en="more than double"))
    if r >= 1.15:
        return t(es=f"{round(100 * (r - 1))} % más que", en=f"{round(100 * (r - 1))} % more than")
    if r > 0.85:
        return t(es="parecido a", en="similar to")
    return t(es=f"{round(100 * (1 - r))} % menos que", en=f"{round(100 * (1 - r))} % less than")


def _envoltura(aoi: AOI, titulo: str, en_simple: str, como_leerlo: str, cuerpo: dict,
               notes: list[str] | None = None) -> dict:
    return {"aoi": aoi.info(), "titulo": titulo, "en_simple": en_simple,
            "como_leerlo": como_leerlo, "unidad": unidad(), **cuerpo,
            "notes": [_no_es_pronostico(), *(notes or [])]}


def _mensual(store: PlanStore, aoi: AOI) -> pd.DataFrame:
    full = store.monthly(aoi).rename(columns={"focos_armonizados": "n"})
    if full["n"].sum() == 0:
        raise PlanNoData(no_fire(aoi))
    return full


def _fuente(aoi: AOI) -> tuple[str, str, str, list]:
    """(tabla, columna de peso, condición WHERE, parámetros) según el AOI.

    Igual que ``PlanStore._monthly``: Cusco entero suma ``eq_hotspots`` de la tabla de celda-día;
    un área dibujada suma ``eq_foco`` de los focos que caen dentro.
    """
    if aoi.whole_region:
        return "cd", "eq_hotspots", "TRUE", []
    return "fo", "eq_foco", f"({aoi.sql}) AND en_serie = 1", list(aoi.params)


def _anios_referencia(full: pd.DataFrame) -> list[int]:
    """Años con sus 12 meses y sin focos extrapolados: la historia con la que se compara."""
    ok = full.assign(limpio=full["calidad"].isin(["referencia", "calibrado"])
                     & ~full["parcial"])
    g = ok.groupby("anio").agg(meses=("mes", "size"), limpio=("limpio", "all"))
    return sorted(int(a) for a in g.index[(g["meses"] == 12) & g["limpio"]])


# ------------------------------------------------------------------ 1. estacionalidad
def estacionalidad(store: PlanStore, aoi: AOI) -> dict:
    full = _mensual(store, aoi)
    ref = _anios_referencia(full)
    hist = full[full["anio"].isin(ref)]
    total = float(hist["n"].sum())
    por_mes = hist.groupby("mes")["n"]
    tabla = pd.DataFrame({"mediana": por_mes.median(), "p25": por_mes.quantile(0.25),
                          "p75": por_mes.quantile(0.75), "parte": por_mes.sum() / total})
    # Temporada: los meses de mayor actividad que juntos suman el 80 % del año.
    orden = tabla["parte"].sort_values(ascending=False)
    temporada = sorted(int(m) for m in orden.index[: int((orden.cumsum() < PARTE_TEMPORADA).sum())
                                                   + 1])
    parte_temporada = float(tabla.loc[temporada, "parte"].sum())
    pico = int(tabla["mediana"].idxmax())        # el mes más activo en un año típico
    seguidos = temporada == list(range(temporada[0], temporada[-1] + 1))
    ini, fin = month_name(temporada[0]), month_name(temporada[-1])
    if seguidos and len(temporada) > 1:
        cuando = t(es=f"va de {ini} a {fin}", en=f"runs from {ini} to {fin}")
    else:
        meses = join_list([month_name(m) for m in temporada])
        cuando = t(es=f"se concentra en {meses}", en=f"is concentrated in {meses}")
    parte = _pct(parte_temporada)
    if float(tabla["mediana"].max()) < 0.5:
        # QA de Erik (5): con todas las medianas en 0 el "mes pico" salía enero. En un año
        # típico no hay focos de calor: se dice eso y el mes con más focos acumulados.
        pico = int(tabla["parte"].idxmax())
        en_simple = t(
            es=f"En esta área hay muy pocos focos de calor para hablar de una temporada: en un año "
               f"típico "
               f"ningún mes tiene focos. Cuando hubo, fue sobre todo en {month_name(pico)} "
               f"({_pct(tabla.loc[pico, 'parte'])} del total).",
            en=f"This area has too few hotspots to describe a season: in a typical year no month "
               f"has hotspots. When there were some, it was mostly in {month_name(pico)} "
               f"({_pct(tabla.loc[pico, 'parte'])} of the total).")
    else:
        esos = (t(es="esos meses reúnen", en="those months hold") if len(temporada) > 1
                else t(es="ese mes reúne", en="that month holds"))
        en_simple = t(
            es=f"La temporada de focos de calor {cuando}: {esos} el {parte} de los focos de calor "
               f"del año. "
               f"El mes más activo es {month_name(pico)}, con unos "
               f"{_focos(tabla.loc[pico, 'mediana'])} en un año típico.",
            en=f"The hotspot season {cuando}: {esos} {parte} of the year's hotspots. "
               f"The most active month is {month_name(pico)}, with about "
               f"{_focos(tabla.loc[pico, 'mediana'])} in a typical year.")
    return _envoltura(
        aoi, t(es="¿Cuándo hay más focos de calor?", en="When are there more hotspots?"), en_simple,
        t(es="Cada barra es un mes. La altura es lo habitual (mediana) y el rango marca entre qué "
             "valores cae la mitad de los años.",
          en="Each bar is a month. The height is the usual value (median) and the range shows "
             "where half of the years fall."),
        {"anios_referencia": [ref[0], ref[-1]], "temporada": temporada, "mes_pico": pico,
         "parte_temporada": round(parte_temporada, 3),
         "meses": [{"mes": int(m), "nombre": month_name(m), "mediana": round(float(r.mediana), 1),
                    "p25": round(float(r.p25), 1), "p75": round(float(r.p75), 1),
                    "parte_del_anio": round(float(r.parte), 3), "en_temporada": m in temporada}
                   for m, r in tabla.iterrows()]})


# ------------------------------------------------------------------ 2. ranking de años
def ranking(store: PlanStore, aoi: AOI) -> dict:
    full = _mensual(store, aoi)
    ref = _anios_referencia(full)
    completos = full.groupby("anio").filter(lambda g: len(g) == 12)
    ext = completos["n"] * completos["fraccion_extrapolada"]
    anual = completos.assign(ext=ext).groupby("anio").agg(
        total=("n", "sum"), ext=("ext", "sum"), incertidumbre=("incertidumbre", "sum"))
    tipico = float(anual.loc[ref, "total"].median())
    anual = anual.sort_values("total", ascending=False)
    filas = []
    for puesto, (anio, r) in enumerate(anual.iterrows(), start=1):
        frac = float(r.ext / r.total) if r.total > 0 else 0.0
        calidad = "extrapolado" if frac > 0.5 else "mixto" if frac > 0 else "ok"
        if calidad == "ok" and (int(anio), 1) < REFERENCIA_FROM:
            # QA de Erik (6): 2001 o 2002 con 0 focos pasaban como "ok" y salían como el año
            # más tranquilo. Con solo Terra se ve ~5 veces menos, aunque el valor sea 0.
            calidad = "extrapolado"
        filas.append({"puesto": puesto, "anio": int(anio), "total": round(float(r.total), 1),
                      "respecto_al_tipico": round(float(r.total) / tipico, 2) if tipico else None,
                      "calidad": calidad, "incertidumbre": round(float(r.incertidumbre), 1)})
    firmes = [f for f in filas if f["calidad"] == "ok"] or filas
    mayor, menor = firmes[0], firmes[-1]
    veces = _veces(mayor["total"], tipico)
    en_simple = t(
        es=f"El año con más focos de calor fue {mayor['anio']}, con {_focos(mayor['total'])}: "
           f"{veces} un año típico ({_n(tipico)}). El más tranquilo fue "
           f"{menor['anio']}, con {_n(menor['total'])}.",
        en=f"The year with the most hotspots was {mayor['anio']}, with {_focos(mayor['total'])}: "
           f"{veces} a typical year ({_n(tipico)}). The quietest was "
           f"{menor['anio']}, with {_n(menor['total'])}.")
    notes = []
    if any(f["calidad"] != "ok" for f in filas):
        notes.append(t(es="Los años con focos extrapolados (antes de julio de 2002) aparecen en "
                          "la lista con su margen, pero no se usan para el año típico ni para el "
                          "primer y último puesto de la frase.",
                       en="Years with extrapolated hotspots (before July 2002) appear in the list "
                          "with their margin, but are not used for the typical year or for the "
                          "first and last place in the sentence."))
    if any(f["anio"] == 2025 for f in filas):
        notes.append(note_2025())
    return _envoltura(
        aoi, t(es="¿Qué años tuvieron más focos de calor?",
               en="Which years had the most hotspots?"),
        en_simple,
        t(es="Cada barra es un año. La línea punteada marca un año típico: las barras que la "
             "superan tuvieron más focos de calor de lo habitual. Las barras claras incluyen "
             "focos extrapolados.",
          en="Each bar is a year. The dashed line marks a typical year: bars above it had more "
             "hotspots than usual. Light bars include extrapolated hotspots."),
        {"anio_tipico": round(tipico, 1), "anios_referencia": [ref[0], ref[-1]], "anios": filas},
        notes)


# ------------------------------------------------------------------ 3. curva acumulada
def _diario(store: PlanStore, aoi: AOI) -> pd.DataFrame:
    tabla, peso, where, params = _fuente(aoi)
    cur = store.cursor()
    df = cur.execute(
        f"SELECT anio, dayofyear(CAST(fecha_local AS DATE)) AS dia, sum({peso}) AS n "
        f"FROM {tabla} WHERE {where} GROUP BY 1, 2", params).df()
    cur.close()
    df["dia"] = df["dia"].clip(upper=365)          # el 31-dic de un bisiesto cuenta como día 365
    dias = df.pivot_table(index="anio", columns="dia", values="n", aggfunc="sum", fill_value=0.0)
    return dias.reindex(columns=range(1, 366), fill_value=0.0).cumsum(axis=1)


def acumulado(store: PlanStore, aoi: AOI, anio: int | None) -> dict:
    full = _mensual(store, aoi)
    ref = _anios_referencia(full)
    completos = sorted(int(a) for a, g in full.groupby("anio") if len(g) == 12)
    anio = completos[-1] if anio is None else int(anio)
    if anio not in completos:
        raise PlanError(t(es=f"Año {anio} no disponible: elige uno entre {completos[0]} y "
                             f"{completos[-1]}.",
                          en=f"Year {anio} not available: choose one between {completos[0]} and "
                             f"{completos[-1]}."))
    curvas = _diario(store, aoi).reindex(completos, fill_value=0.0)
    # Misma historia de referencia que el ranking, para que 'un año típico' sea un solo número.
    base = curvas.loc[ref]
    mediana, p10, p90 = (base.quantile(q) for q in (0.5, 0.1, 0.9))
    curva = curvas.loc[anio]
    final, normal, bajo, alto = (float(s.iloc[-1]) for s in (curva, mediana, p10, p90))
    # `veredicto` es un código del contrato (no se traduce); la frase sí.
    if final > alto:
        veredicto = "muy por encima de lo normal"
        texto = t(es=veredicto, en="well above normal")
    elif final < bajo:
        veredicto = "muy por debajo de lo normal"
        texto = t(es=veredicto, en="well below normal")
    else:
        veredicto = "dentro de lo normal"
        texto = t(es=veredicto, en="within the normal range")
    en_simple = t(
        es=f"{anio} cerró con {_focos(final)}, {texto}: un año típico cierra con "
           f"{_n(normal)} (entre {_n(bajo)} y {_n(alto)}).",
        en=f"{anio} closed with {_focos(final)}, {texto}: a typical year closes "
           f"with {_n(normal)} (between {_n(bajo)} and {_n(alto)}).")
    cruce = np.flatnonzero(curva.to_numpy() >= normal)
    if final > normal and len(cruce) and cruce[0] < 364:
        # Fecha real del año consultado: con 2001 fijo, en los bisiestos salía un día después
        # (2020 cruzó el 24 de agosto, no el 25).
        fecha = pd.Timestamp(anio, 1, 1) + pd.Timedelta(days=int(cruce[0]))
        en_simple += t(es=f" El {fecha.day} de {month_name(fecha.month)} ya había alcanzado lo "
                          "que un año típico suma en doce meses.",
                       en=f" By {month_name(fecha.month)} {fecha.day} it had already reached "
                          "what a typical year adds up in twelve months.")
    dias = sorted({*range(7, 366, 7), 365})
    notes = []
    if anio not in ref:
        notes.append(t(es=f"{anio} tiene focos extrapolados: su curva es una referencia gruesa.",
                       en=f"{anio} has extrapolated hotspots: its curve is a rough reference."))
    if anio == 2025:
        notes.append(note_2025())               # METHODOLOGY.md: el 2025 bajo lleva su nota
    return _envoltura(
        aoi, t(es=f"¿Cómo avanzó {anio} frente a lo normal?",
               en=f"How did {anio} progress compared with normal?"), en_simple,
        t(es="La línea del año va sumando focos día a día. La banda es donde cae la mayoría de "
             "los años (8 de cada 10) y la línea central es lo habitual. Si el año sube por encima "
             "de la banda, fue excepcional.",
          en="The year's line adds up hotspots day by day. The band is where most years fall "
             "(8 out of 10) and the central line is the usual value. If the year rises above the "
             "band, it was exceptional."),
        {"anio": anio, "anios_referencia": [ref[0], ref[-1]], "veredicto": veredicto,
         "total": round(final, 1), "normal": round(normal, 1),
         "rango_normal": [round(bajo, 1), round(alto, 1)],
         "curva": [{"dia": d, "acumulado": round(float(curva[d]), 1),
                    "normal": round(float(mediana[d]), 1), "bajo": round(float(p10[d]), 1),
                    "alto": round(float(p90[d]), 1)} for d in dias]},
        notes)


# ------------------------------------------------------------------ 4. altitud
def altitud(store: PlanStore, aoi: AOI) -> dict:
    _mensual(store, aoi)
    casos = " ".join(
        f"WHEN alt_m {'<' if hi is not None else '>='} {hi if hi is not None else lo} THEN {i}"
        for i, (lo, hi) in enumerate(BANDAS_ALTITUD) if i < len(BANDAS_ALTITUD) - 1)
    tabla, peso, where, params = _fuente(aoi)
    cur = store.cursor()
    df = cur.execute(
        f"SELECT CASE WHEN alt_m IS NULL THEN -1 {casos} ELSE {len(BANDAS_ALTITUD) - 1} END "
        f"AS banda, sum({peso}) AS n, count(DISTINCT (cell_lat, cell_lon)) AS celdas "
        f"FROM {tabla} WHERE {where} GROUP BY 1", params).df()
    cur.close()
    total = float(df["n"].sum())
    por = df.set_index("banda")
    bandas = []
    for i, (lo, hi) in enumerate(BANDAS_ALTITUD):
        n = float(por["n"].get(i, 0.0))
        bandas.append({"banda": _banda(lo, hi), "desde_m": lo, "hasta_m": hi,
                       "focos_armonizados": round(n, 1), "parte": round(n / total, 3),
                       "celdas": int(por["celdas"].get(i, 0))})
    mayor = max(bandas, key=lambda b: b["parte"])
    alto = sum(b["parte"] for b in bandas if (b["desde_m"] or 0) >= 2500)
    en_simple = t(
        es=f"La franja con más focos de calor es la de {mayor['banda']}: reúne el "
           f"{_pct(mayor['parte'])} de los focos armonizados. En total, el {_pct(alto)} ocurre "
           f"sobre los 2,500 m y el {_pct(1 - alto)} por debajo.",
        en=f"The band with the most hotspots is {mayor['banda']}: it holds "
           f"{_pct(mayor['parte'])} of the harmonized hotspots. Overall, {_pct(alto)} occurs "
           f"above 2,500 m and {_pct(1 - alto)} below.")
    notes = []
    if -1 in por.index:
        notes.append(t(es=f"{_n(por['n'][-1])} focos armonizados no tienen altitud y no entran "
                          "en las franjas.",
                       en=f"{_n(por['n'][-1])} harmonized hotspots have no altitude and are not "
                          "in any band."))
    return _envoltura(
        aoi, t(es="¿A qué altitud ocurren los focos de calor?",
               en="At what altitude do hotspots occur?"),
        en_simple,
        t(es="Cada franja muestra qué parte de los focos de calor del periodo ocurrió a esa "
             "altitud.",
          en="Each band shows what share of all the hotspots in the period occurred at that "
             "altitude."),
        {"bandas": bandas}, notes)


# ------------------------------------------------------------------ 5. recurrencia
def recurrencia(store: PlanStore, aoi: AOI, limite: int = 5000) -> dict:
    _mensual(store, aoi)
    tabla, peso, where, params = _fuente(aoi)
    cur = store.cursor()
    df = cur.execute(
        f"SELECT cell_lat AS lat, cell_lon AS lon, count(DISTINCT anio) AS anios, "
        f"sum({peso}) AS n, max(anio) AS ultimo FROM {tabla} "
        f"WHERE {where} AND anio >= {RECURRENCIA_DESDE} GROUP BY 1, 2", params).df()
    ultimo_anio = cur.execute("SELECT max(anio) FROM cd").fetchall()[0][0]
    cur.close()
    if df.empty:
        raise PlanNoData(_sin_datos(t(es=f"{aoi.label} desde {RECURRENCIA_DESDE}",
                                      en=f"{aoi.label} since {RECURRENCIA_DESDE}")))
    posibles = int(ultimo_anio) - RECURRENCIA_DESDE + 1
    total = len(df)
    una_vez = int((df["anios"] == 1).sum())
    umbral = max(3, round(posibles / 3))            # "recurrente": arde 1 de cada 3 años o más
    frecuentes = int((df["anios"] >= umbral).sum())
    tope = int(df["anios"].max())
    df = df.sort_values(["anios", "n"], ascending=False)
    ardieron = (t(es="tuvo focos", en="had hotspots") if frecuentes == 1
                else t(es="tuvieron focos", en="had hotspots"))
    en_simple = t(
        es=f"Desde {RECURRENCIA_DESDE} se detectaron focos de calor en {_lugares(total)} de "
           f"~1 km. En el {_pct(una_vez / total)} hubo focos un solo año; "
           f"{_lugares(frecuentes)} {ardieron} "
           f"en {umbral} o más de los {posibles} años, y el más repetido los tuvo en "
           f"{_anios(tope)}.",
        en=f"Since {RECURRENCIA_DESDE}, hotspots were detected in {_lugares(total)} of ~1 km. "
           f"{_pct(una_vez / total)} had hotspots in a single year; {_lugares(frecuentes)} "
           f"{ardieron} "
           f"in {umbral} or more of the {posibles} years, and the most repeated one had them in "
           f"{_anios(tope)}.")
    return _envoltura(
        aoi, t(es="¿Dónde se repiten los focos de calor?", en="Where do hotspots recur?"),
        en_simple,
        t(es="Cada punto es una celda de ~1 km. El número es en cuántos años distintos tuvo "
             "focos de calor: cuanto más alto, más se repiten en ese lugar.",
          en="Each point is a ~1 km cell. The number is how many different years it had hotspots: "
             "the higher, the more often it repeats in that place."),
        {"desde": RECURRENCIA_DESDE, "anios_posibles": posibles, "lugares": total,
         "umbral_recurrente": umbral, "lugares_recurrentes": frecuentes,
         "por_numero_de_anios": [{"anios": int(k), "lugares": int(v)} for k, v in
                                 df["anios"].value_counts().sort_index().items()],
         "celdas_devueltas": min(total, limite),
         "celdas": [{"lat": round(float(r.lat), 3), "lon": round(float(r.lon), 3),
                     "anios": int(r.anios), "ultimo_anio": int(r.ultimo)}
                    for r in df.head(limite).itertuples(index=False)]},
        [t(es="Solo se usa VIIRS (desde 2013) para que todos los años se vean con el mismo "
              "detalle.",
           en="Only VIIRS (since 2013) is used so that every year is seen with the same "
              "detail.")])


# ------------------------------------------------------------------ resumen
def resumen(store: PlanStore, aoi: AOI, graficos: bool = False) -> dict:
    """Las cinco frases juntas: la respuesta corta para quien no va a mirar gráficos.

    Con ``graficos=True`` incluye también las respuestas completas de estacionalidad, ranking,
    acumulado y altitud: el panel "En simple" se arma con UNA llamada (antes eran 5, y
    /api/resumen recalculaba las mismas analíticas).
    """
    partes = [estacionalidad(store, aoi), ranking(store, aoi), acumulado(store, aoi, None),
              altitud(store, aoi), recurrencia(store, aoi, limite=0)]
    notes = [_no_es_pronostico()]
    if partes[2]["anio"] == 2025:               # la frase de la curva habla de 2025
        notes.append(note_2025())
    return {"aoi": aoi.info(),
            "titulo": t(es=f"Los focos de calor en {aoi.label}, en simple",
                        en=f"Hotspots in {aoi.label}, in plain words"),
            "unidad": unidad(),
            "frases": [{"pregunta": p["titulo"], "respuesta": p["en_simple"]} for p in partes],
            **({"graficos": dict(zip(["estacionalidad", "ranking", "acumulado", "altitud"],
                                     partes[:4], strict=True))} if graficos else {}),
            "notes": notes}

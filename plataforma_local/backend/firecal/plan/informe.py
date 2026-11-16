"""Informe técnico automático de focos de calor, solo con los datos que sirve la plataforma.

Área: Cusco entero (``departamento``), un rectángulo (``bbox``), un punto con radio o un ámbito
(``ambito=nivel:codigo``: provincia, distrito o cuenca Pfafstetter). Periodo: ``fecha_inicio`` y
``fecha_fin`` (AAAA-MM; por defecto toda la serie) y, opcionalmente, un ``mes`` para detallar.

Todo sale de lo mismo que muestra la app (calendario, anomalías, analíticas, ámbitos y metadatos):
no usa fuentes externas. Incluye la trazabilidad (versión de datos, sumas de control y las llamadas
a la API que reproducen cada cifra) para que el informe se pueda auditar.
"""

from __future__ import annotations

import html
from collections import defaultdict
from datetime import UTC, datetime
from urllib.parse import urlencode

from firecal.i18n import get_lang, t
from firecal.plan import ambitos
from firecal.plan.query import AOI, PlanError, PlanNoData, PlanStore, parse_month, unidad

# Rampa YlOrRd (ColorBrewer, apta para daltonismo) para la matriz; el 0 en gris neutro.
RAMPA = ["#ffffb2", "#fecc5c", "#fd8d3c", "#f03b20", "#bd0026"]
CERO = "#eef0f3"
MESES_C = {"es": ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"],
           "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]}
esc = html.escape


def _resolver(store: PlanStore, params: dict, ambito: str | None) -> tuple[AOI, str | None]:
    """AOI del informe y, si es un ámbito, su nivel."""
    dados = [k for k in ("departamento", "bbox", "lat") if params.get(k) not in (None, "")]
    if ambito:
        if dados:
            raise PlanError(t(es="Indica un solo tipo de área: 'ambito' o departamento, bbox o punto.",
                              en="Give a single area type: 'ambito' or departamento, bbox or point."))
        nivel, _, codigo = ambito.partition(":")
        if not codigo:
            raise PlanError(t(es="'ambito' va como nivel:codigo, p. ej. distrito:080910.",
                              en="'ambito' goes as level:code, e.g. distrito:080910."))
        return ambitos.aoi_unidad(store, nivel, codigo), nivel
    return store.resolve_aoi(params.get("departamento"), params.get("bbox"), params.get("lat"),
                             params.get("lon"), params.get("radio_km")), None


def _color(v: float | None, cortes: list[float]) -> str:
    if not v:
        return CERO
    i = sum(v > c for c in cortes)
    return RAMPA[min(i, len(RAMPA) - 1)]


def _tabla(cabecera: list[str], filas: list[list], clase: str = "") -> str:
    th = "".join(f"<th>{esc(str(c))}</th>" for c in cabecera)
    tr = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in f) + "</tr>" for f in filas)
    return f'<table class="{clase}"><thead><tr>{th}</tr></thead><tbody>{tr}</tbody></table>'


def _n(v, d: int = 1) -> str:
    return "—" if v is None else f"{v:,.{d}f}"


def _seguro(fn, *args, **kw):
    try:
        return fn(*args, **kw)
    except (PlanNoData, PlanError):
        return None


def informe_tecnico(store: PlanStore, params: dict, ambito: str | None = None,
                    inicio: str | None = None, fin: str | None = None,
                    mes: str | None = None) -> str:
    from firecal.plan import analitica

    if mes:
        parse_month(mes, "mes")                     # 422 antes de calcular nada
    aoi, nivel_amb = _resolver(store, params, ambito)
    cal = store.calendar(aoi, inicio, fin)          # 404 "sin datos" si el área no tiene focos
    lang = get_lang() if get_lang() in MESES_C else "es"
    meta = store.meta
    ahora = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    a0, a1 = cal["fecha_inicio"], cal["fecha_fin"]

    # ---- consultas a la API que reproducen el informe (trazabilidad)
    if ambito:
        q_area = {"ambito": ambito}
    else:
        q_area = {k: params[k] for k in ("departamento", "bbox", "lat", "lon", "radio_km")
                  if params.get(k) not in (None, "")}
    rango = {"fecha_inicio": a0, "fecha_fin": a1}
    llamadas = [f"/api/informe?{urlencode({**q_area, **rango, **({'mes': mes} if mes else {})})}"]
    if ambito:
        nv, cod = ambito.split(":", 1)
        llamadas += [f"/api/ambitos/{nv}/{cod}", f"/api/ambitos/{nv}.csv"]
    else:
        llamadas += [f"/api/calendario?{urlencode({**q_area, **rango})}"]
        llamadas += [f"/api/analitica/{x}?{urlencode(q_area)}"
                     for x in ("estacionalidad", "ranking", "acumulado", "altitud", "recurrencia")]
        llamadas += [f"/api/hotspots.csv?{urlencode({**q_area, **rango})}", "/api/metadatos"]

    # ---- 1. resumen
    celdas = [c for c in cal["celdas"] if not c.get("sin_dato")]
    total = cal["total_focos_armonizados"]
    por_anio = defaultdict(lambda: {"n": 0.0, "modis": 0, "viirs": 0, "calidad": set(), "pico": (0, 0.0)})
    for c in celdas:
        a = por_anio[c["anio"]]
        v = c["focos_armonizados"] or 0.0
        a["n"] += v
        a["modis"] += c.get("focos_modis", 0)
        a["viirs"] += c.get("focos_viirs", 0)
        a["calidad"].add(c["calidad"])
        if v > a["pico"][1]:
            a["pico"] = (c["mes"], v)
    resumen = _seguro(analitica.resumen, store, aoi)
    frases = resumen["frases"] if resumen else []
    bloque_nivel = ""
    if nivel_amb:
        df = ambitos.tipificar(store, nivel_amb)
        u = ambitos._fila(ambito.split(":", 1)[1], df.loc[ambito.split(":", 1)[1]])
        bloque_nivel = (
            f'<p><span class="badge" style="background:{u["color"]}">{esc(u["etiqueta"])}</span> '
            + esc(t(es=f"Nivel de peligro por focos de calor (formato CENEPRED): puesto {u['puesto']} de "
                       f"{len(df)} en {ambitos.titulo_nivel(nivel_amb).lower()} de Cusco; índice "
                       f"{_n(u['indice'], 2)}.",
                    en=f"Hotspot hazard level (CENEPRED format): rank {u['puesto']} of {len(df)} among "
                       f"{ambitos.titulo_nivel(nivel_amb).lower()} of Cusco; index {_n(u['indice'], 2)}."))
            + "</p>" + _tabla(
                [t(es="Parámetro (por 100 km²)", en="Parameter (per 100 km²)"),
                 t(es="Esta unidad", en="This unit"), t(es="Mediana del nivel", en="Level median")],
                [[esc(t(es="Densidad media (por año)", en="Mean density (per year)")),
                  _n(u["densidad"], 3), _n(float(df["densidad"].median()), 3)],
                 [esc(t(es="Lugares recurrentes (2013–2025)", en="Recurrent places (2013–2025)")),
                  _n(u["recurrencia"], 3), _n(float(df["recurrencia"].median()), 3)],
                 [esc(t(es="Año más activo", en="Most active year")),
                  _n(u["extremo"], 3), _n(float(df["extremo"].median()), 3)]], "num"))
    anio_max = max(por_anio, key=lambda y: por_anio[y]["n"]) if por_anio else None
    resumen_txt = t(
        es=f"Entre {a0} y {a1} se registraron {_n(total)} focos de calor armonizados en {aoi.label}"
           + (f"; el año con más fue {anio_max} ({_n(por_anio[anio_max]['n'])})." if anio_max else "."),
        en=f"Between {a0} and {a1}, {_n(total)} harmonized hotspots were recorded in {aoi.label}"
           + (f"; the year with the most was {anio_max} ({_n(por_anio[anio_max]['n'])})." if anio_max else "."))

    # ---- 2. matriz mes x año
    cortes = cal.get("cortes_color") or []
    meses_c = MESES_C[lang]
    filas_m = []
    por_clave = {(c["anio"], c["mes"]): c for c in cal["celdas"]}
    for y in cal["anios"]:
        fila = [f"<b>{y}</b>"]
        for m in range(1, 13):
            c = por_clave.get((y, m))
            if c is None or c.get("sin_dato"):
                fila.append('<span class="sd">—</span>')
                continue
            v = c["focos_armonizados"] or 0.0
            marca = ("†" if c["calidad"] in ("extrapolado", "mixto") else "") + (
                "‡" if c.get("categoria") == "incierta" else "")
            txt = f"{v:,.0f}" if v >= 10 else f"{v:.1f}"
            fila.append(f'<span class="cel" style="background:{_color(v, cortes)}">{txt}{marca}</span>')
        fila.append(f"<b>{_n(por_anio[y]['n']) if y in por_anio else '—'}</b>")
        filas_m.append(fila)
    tabla_matriz = _tabla(["", *meses_c, t(es="Total", en="Total")], filas_m, "matriz")

    filas_a = []
    for y in sorted(por_anio):
        a = por_anio[y]
        cal_txt = ", ".join(sorted(a["calidad"]))
        pico = f"{meses_c[a['pico'][0] - 1]} ({_n(a['pico'][1])})" if a["pico"][1] else "—"
        filas_a.append([y, _n(a["n"]), f"{a['modis']:,}", f"{a['viirs']:,}", pico, esc(cal_txt)])
    tabla_anual = _tabla([t(es="Año", en="Year"), t(es="Focos armonizados", en="Harmonized hotspots"),
                          t(es="Detecciones MODIS", en="MODIS detections"),
                          t(es="Detecciones VIIRS", en="VIIRS detections"),
                          t(es="Mes pico", en="Peak month"), t(es="Calidad", en="Quality")],
                         filas_a, "num")

    # ---- 3. analíticas (toda la historia del área como referencia)
    est = _seguro(analitica.estacionalidad, store, aoi)
    rk = _seguro(analitica.ranking, store, aoi)
    ultimo = min(int(a1[:4]), 2025)
    acu = _seguro(analitica.acumulado, store, aoi, ultimo)
    alt = _seguro(analitica.altitud, store, aoi)
    rec = _seguro(analitica.recurrencia, store, aoi, limite=0)
    bloques = []
    if est:
        bloques.append(f"<h3>{esc(est['titulo'])}</h3><p>{esc(est['en_simple'])}</p>" + _tabla(
            [t(es="Mes", en="Month"), t(es="Mediana", en="Median"), "P25", "P75",
             t(es="% del año", en="% of year"), t(es="Temporada", en="Season")],
            [[meses_c[x["mes"] - 1], _n(x["mediana"]), _n(x["p25"]), _n(x["p75"]),
              f"{100 * x['parte_del_anio']:.1f}", "✓" if x["en_temporada"] else ""] for x in est["meses"]],
            "num"))
    if rk:
        top = rk["anios"][:5]
        bloques.append(f"<h3>{esc(rk['titulo'])}</h3><p>{esc(rk['en_simple'])}</p>" + _tabla(
            [t(es="Puesto", en="Rank"), t(es="Año", en="Year"), t(es="Total", en="Total"),
             t(es="Respecto al típico", en="vs typical"), t(es="Calidad", en="Quality")],
            [[x["puesto"], x["anio"], _n(x["total"]), _n(x["respecto_al_tipico"], 2), x["calidad"]]
             for x in top], "num")
            + f"<p class='nota'>{esc(t(es='Año típico (mediana 2003–2025)', en='Typical year (2003–2025 median)'))}: "
              f"{_n(rk['anio_tipico'])}.</p>")
    if acu:
        bloques.append(f"<h3>{esc(acu['titulo'])}</h3><p>{esc(acu['en_simple'])}</p>")
    if alt:
        bloques.append(f"<h3>{esc(alt['titulo'])}</h3><p>{esc(alt['en_simple'])}</p>" + _tabla(
            [t(es="Franja", en="Band"), t(es="Focos armonizados", en="Harmonized hotspots"),
             t(es="Parte", en="Share"), t(es="Celdas", en="Cells")],
            [[esc(b["banda"]), _n(b["focos_armonizados"]), f"{100 * b['parte']:.1f} %", b["celdas"]]
             for b in alt["bandas"]], "num"))
    if rec:
        bloques.append(f"<h3>{esc(rec['titulo'])}</h3><p>{esc(rec['en_simple'])}</p>")
    svg_anual = ambitos._svg_barras([por_anio[y]["n"] for y in sorted(por_anio)],
                                    [str(y) for y in sorted(por_anio)],
                                    sorted(por_anio).index(anio_max) if anio_max else None)

    bloque_mes = ambitos.seccion_mes(store, aoi, mes) if mes else ""

    # ---- 4. método, limitaciones y trazabilidad
    f = meta.get("factores", {})
    metodo = [
        t(es="Unidad: focos de calor armonizados = celdas de 0,01° (~1,1 km) con al menos un foco de calor "
             "en un día local (UTC−5), en escala MODIS. Nunca se cuentan filas ni se suman MODIS y VIIRS.",
          en="Unit: harmonized hotspots = 0.01° (~1.1 km) cells with at least one hotspot on a local day "
             "(UTC−5), on the MODIS scale. Rows are never counted and MODIS and VIIRS are never added."),
        t(es=f"Factores por estrato de altitud (≥ 2500 m / < 2500 m): VIIRS S-NPP k = {f.get('VIIRS*k|alto')}"
             f" / {f.get('VIIRS*k|bajo')} (calibrado 2013–2019); NOAA-20 k20 = {f.get('VIIRS-N20*k|alto')}"
             f" / {f.get('VIIRS-N20*k|bajo')} (solo en días sin S-NPP); Terra kT = "
             f"{f.get('Terra*kT|alto')} / {f.get('Terra*kT|bajo')} (antes del 4-jul-2002).",
          en=f"Factors by altitude stratum (≥ 2500 m / < 2500 m): VIIRS S-NPP k = {f.get('VIIRS*k|alto')}"
             f" / {f.get('VIIRS*k|bajo')} (calibrated 2013–2019); NOAA-20 k20 = {f.get('VIIRS-N20*k|alto')}"
             f" / {f.get('VIIRS-N20*k|bajo')} (only on days without S-NPP); Terra kT = "
             f"{f.get('Terra*kT|alto')} / {f.get('Terra*kT|bajo')} (before 4 Jul 2002)."),
        t(es="Validación con años reservados: VIIRS×k / MODIS real = 0,90–1,09 por año (2020–2024); "
             "NOAA-20×k20 / S-NPP×k = 0,98–1,05 (2022–2025), error mensual mediano 7 %; meses "
             "extrapolados con Terra: error mensual 41–45 %.",
          en="Validation on held-out years: VIIRS×k / actual MODIS = 0.90–1.09 per year (2020–2024); "
             "NOAA-20×k20 / S-NPP×k = 0.98–1.05 (2022–2025), median monthly error 7 %; months "
             "extrapolated with Terra: monthly error 41–45 %."),
        t(es="Anomalía = (valor − mediana del mismo mes) / max(rango intercuartil, 1), con los meses "
             "completos de calidad referencia o calibrado; categorías en ±0,5 y ±1. Si el margen de un "
             "mes extrapolado cruza de categoría, la anomalía es «incierta».",
          en="Anomaly = (value − median of the same month) / max(interquartile range, 1), using complete "
             "months of reference or calibrated quality; categories at ±0.5 and ±1. If the margin of an "
             "extrapolated month crosses a category, the anomaly is 'uncertain'."),
        t(es="Filtros: type = 0 (vegetación); MODIS confidence ≥ 30; VIIRS nominal o alta. Las analíticas "
             "usan toda la historia del área (2003–2025) como referencia, aunque el periodo pedido sea menor.",
          en="Filters: type = 0 (vegetation); MODIS confidence ≥ 30; VIIRS nominal or high. The "
             "analytics use the area's whole history (2003–2025) as reference, even if the requested "
             "period is shorter."),
    ]
    if nivel_amb:
        pesos, cr = ambitos.pesos_ahp()
        metodo.append(t(
            es=f"Nivel de peligro: pesos de Saaty {pesos} (razón de consistencia {cr}); percentiles dentro "
               "del nivel; muy alto ≥ 0,75, alto ≥ 0,50, medio ≥ 0,25.",
            en=f"Hazard level: Saaty weights {pesos} (consistency ratio {cr}); percentiles within the "
               "level; very high ≥ 0.75, high ≥ 0.50, medium ≥ 0.25."))
    limites = [
        t(es="Solo Cusco: los factores no se validaron para otras regiones.",
          en="Cusco only: the factors were not validated for other regions."),
        t(es="La serie termina el 2025-12-31; no incluye 2026 ni detecciones en tiempo real.",
          en="The series ends on 2025-12-31; it does not include 2026 or near-real-time detections."),
        t(es="Un foco de calor no es un incendio ni un área quemada; no indica la causa.",
          en="A hotspot is not a fire or a burned area; it does not tell the cause."),
        t(es="Describe lo observado por los satélites; no es un pronóstico.",
          en="It describes what satellites observed; it is not a forecast."),
        t(es="La deriva orbital de MODIS (2025) no afecta a la serie porque desde 2013 se usa VIIRS.",
          en="MODIS orbital drift (2025) does not affect the series because VIIRS is used since 2013."),
    ]
    if nivel_amb:
        limites.append(t(es="El nivel de peligro es relativo dentro de Cusco y no incluye vulnerabilidad: "
                            "es un insumo para la evaluación de CENEPRED.",
                         en="The hazard level is relative within Cusco and does not include "
                            "vulnerability: it is an input to CENEPRED's assessment."))
    ctrl = meta.get("controles", {})
    filas_ctrl = [[esc(k), f"{v.get('filas', 0):,}", _n(v.get("suma"), 2), f"<code>{esc(v.get('sha256', '')[:16])}…</code>",
                   "✓" if v.get("coincide_maestro") else "✗"] for k, v in ctrl.items()]
    tabla_ctrl = _tabla([t(es="Archivo", en="File"), t(es="Filas", en="Rows"), t(es="Suma de pesos", en="Weight sum"),
                         "SHA-256", t(es="Coincide con METHODOLOGY.md §14", en="Matches METHODOLOGY.md §14")], filas_ctrl, "num")
    defs = "".join(f"<dt>{esc(k.replace('_', ' ').capitalize())}</dt><dd>{esc(v)}</dd>"
                   for k, v in ambitos.definiciones().items())
    notas = "".join(f"<li>{esc(n)}</li>" for n in cal.get("notes", []))
    area_txt = f" · {aoi.area_km2:,.0f} km²" if aoi.area_km2 else ""
    csv_link = ("" if ambito else
                f"<p><a href='{esc(llamadas[-2])}'>{esc(t(es='Descargar los focos de calor del periodo (CSV, 18 columnas)', en='Download the hotspots of the period (CSV, 18 columns)'))}</a></p>")

    return f"""<!doctype html><html lang="{lang}"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(t(es="Informe técnico de focos de calor", en="Technical hotspot report"))} · {esc(aoi.label)}</title>
<style>
body{{font:13.5px/1.45 system-ui,sans-serif;color:#1d2330;max-width:900px;margin:24px auto;padding:0 16px}}
h1{{font-size:21px;margin:0}} h2{{font-size:16px;margin:24px 0 6px;border-bottom:1px solid #d0d5dd;padding-bottom:3px}}
h3{{font-size:14px;margin:14px 0 4px}} .sub{{color:#5d6677;margin:2px 0 12px}} .nota{{color:#5d6677;font-size:12px}}
table{{border-collapse:collapse;width:100%;font-size:12.5px;margin:6px 0}} th,td{{border-bottom:1px solid #eef0f3;padding:3px 5px;text-align:left}}
table.num td:not(:first-child),table.num th:not(:first-child){{text-align:right}}
table.matriz td{{text-align:center;padding:2px}} table.matriz th{{text-align:center}}
.cel{{display:block;padding:2px 0;border-radius:3px;font-variant-numeric:tabular-nums}} .sd{{color:#98a2b3}}
.badge{{display:inline-block;color:#fff;font-weight:700;padding:3px 10px;border-radius:6px}}
.nivel{{display:flex;gap:14px;align-items:center;border:1px solid #e4e7ec;border-radius:10px;padding:10px 12px}}
.nivel .badge{{font-size:17px;padding:8px 14px}} dt{{font-weight:600;margin-top:6px}} dd{{margin:2px 0 0}}
code{{font-size:11.5px}} ol.api li{{font-family:ui-monospace,monospace;font-size:11.5px;word-break:break-all}}
@media print{{body{{margin:0;max-width:none}} h2{{break-after:avoid}} table{{break-inside:auto}}}}
</style></head><body>
<p class="nota">Nikal Cusco · {esc(t(es="Informe técnico automático", en="Automated technical report"))} · {ahora} · {esc(t(es="datos", en="data"))} {esc(meta.get("plan_version", ""))}</p>
<h1>{esc(t(es="Focos de calor en", en="Hotspots in"))} {esc(aoi.label)}</h1>
<p class="sub">{esc(t(es="Periodo", en="Period"))} {a0} – {a1}{area_txt}</p>
<p class="nota">{esc(unidad()["definicion"])}</p>

<h2>1. {esc(t(es="Resumen", en="Summary"))}</h2>
<p>{esc(resumen_txt)}</p>
{bloque_nivel}
<ul>{"".join(f"<li>{esc(x['respuesta'])}</li>" for x in frases)}</ul>
{bloque_mes}

<h2>2. {esc(t(es="Datos del periodo", en="Data for the period"))}</h2>
<h3>{esc(t(es="Calendario mes × año (focos de calor armonizados)", en="Month × year calendar (harmonized hotspots)"))}</h3>
{tabla_matriz}
<p class="nota">{esc(t(es="Colores: cortes en los cuantiles 50/75/90/99 de los meses con focos; gris = 0; — = sin dato. † mes con focos extrapolados (solo Terra); ‡ anomalía incierta.", en="Colours: breaks at the 50/75/90/99 quantiles of months with hotspots; grey = 0; — = no data. † month with extrapolated hotspots (Terra only); ‡ uncertain anomaly."))}</p>
<h3>{esc(t(es="Totales por año", en="Totals per year"))}</h3>
{svg_anual}
{tabla_anual}
<p class="nota">{esc(t(es="Las detecciones MODIS y VIIRS son de sensores distintos: se informan por separado y no se suman.", en="MODIS and VIIRS detections come from different sensors: reported separately, never added."))}</p>
{f"<ul class='nota'>{notas}</ul>" if notas else ""}
{csv_link}

<h2>3. {esc(t(es="Análisis", en="Analysis"))}</h2>
{"".join(bloques)}

<h2>4. {esc(t(es="Método", en="Method"))}</h2>
<ul>{"".join(f"<li>{esc(x)}</li>" for x in metodo)}</ul>

<h2>5. {esc(t(es="Limitaciones", en="Limitations"))}</h2>
<ul>{"".join(f"<li>{esc(x)}</li>" for x in limites)}</ul>

<h2>6. {esc(t(es="Trazabilidad", en="Traceability"))}</h2>
<p>{esc(t(es="Versión de los datos", en="Data version"))}: <b>{esc(meta.get("plan_version", ""))}</b> · {esc(t(es="cobertura", en="coverage"))} {esc(str(meta.get("primer_dia", "")))} – {esc(str(meta.get("ultimo_dia", "")))} · {esc(t(es="generado", en="generated"))} {ahora}.</p>
{tabla_ctrl}
<p>{esc(t(es="Llamadas a la API que reproducen las cifras de este informe:", en="API calls that reproduce the figures in this report:"))}</p>
<ol class="api">{"".join(f"<li>{esc(x)}</li>" for x in llamadas)}</ol>

<h2>{esc(t(es="Anexo: definiciones técnicas", en="Annex: technical definitions"))}</h2>
<dl>{defs}</dl>
<p class="nota">We acknowledge the use of data and/or imagery from NASA's FIRMS (https://earthdata.nasa.gov/firms).</p>
</body></html>"""

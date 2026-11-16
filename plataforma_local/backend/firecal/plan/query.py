"""Consultas sobre los datos armonizados de Cusco (Parquet + DuckDB).

Unidad (METHODOLOGY.md y §12): **focos armonizados** = celdas de ~1 km con focos de calor por día,
en escala equivalente a MODIS. En la API el campo es ``focos_armonizados`` (decisión del equipo):
la suma de ``eq_hotspots`` (celda-día) o de ``eq_foco`` (focos); nunca se cuentan filas ni se suma
``n_modis + n_viirs``. El FRP no se usa.

AOI:
- ``departamento=PE-CUS``: todo Cusco; el calendario suma ``eq_hotspots`` del CSV de celda-día.
- ``bbox`` o ``lat/lon/radio_km`` (dibujados): se filtran los focos por ``latitude/longitude`` y se
  suma ``eq_foco``. Así el total en pantalla es igual a la suma de la descarga CSV (P3).
- Otro departamento, o un área fuera de Cusco: **sin datos** (404), nunca ceros (METHODOLOGY.md).

Anomalía (alternativa C del PLAN): ``(valor - mediana del mismo mes) / max(IQR, 1)`` con los meses
completos de calidad ``referencia`` o ``calibrado`` (2002-08 a 2025-12) como historia.
"""

from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd
from shapely.geometry import Point, box, shape

from firecal.concurrency import SingleFlight
from firecal.i18n import t
from firecal.plan.events import meta_path, plan_dir, region_path
from firecal.plan.sources import COLS_FOCOS, REGION_CODE, REGION_NAME
from firecal.regions import buffer_km, geodesic_area_km2
from firecal.settings import Settings

MIN_YEARS = 5
COVER_FROM = (2000, 11)            # primer mes con datos (desde el 2000-11-04)
COVER_TO = (2025, 12)              # último mes (datos hasta 2025-12-31 UTC)
REFERENCIA_FROM = (2002, 7)        # Aqua desde 2002-07-04 (en Cusco, sus focos de julio son 19-27)
VIIRS_FROM = (2013, 1)             # desde aquí la serie usa VIIRS*k
FUENTE = {"extrapolado": "Terra*kT", "mixto": "Terra*kT + MODIS", "referencia": "MODIS",
          "calibrado": "VIIRS*k"}
CATEGORY_EDGES = [(-1.0, "muy por debajo"), (-0.5, "por debajo"), (0.5, "normal"),
                  (1.0, "por encima"), (math.inf, "muy por encima")]
EARTH_KM = 6371.0088
def unidad() -> dict:
    """Nombre y definición de la unidad, en el idioma de la solicitud."""
    return {"nombre": t(es="Focos armonizados", en="Harmonized hotspots"),
            "nombre_en": "Harmonized hotspots",
            "definicion": t(
                es="Focos de calor armonizados: celdas de ~1 km con al menos un foco de calor por "
                   "día, en escala equivalente a MODIS. Combina MODIS (2000–2012) y VIIRS (2013 en "
                   "adelante). Un foco de calor es un píxel con una anomalía térmica detectada por "
                   "el satélite: no es un incendio ni un área quemada.",
                en="Harmonized hotspots: ~1 km cells with at least one hotspot per day, on a "
                   "MODIS-equivalent scale. Combines MODIS (2000–2012) and VIIRS (2013 onwards). A "
                   "hotspot is a pixel with a thermal anomaly detected by the satellite: not a "
                   "fire or a burned area.")}
# Error mensual de kT (METHODOLOGY.md) por estrato: margen de los focos extrapolados.
ERROR_EXTRAPOLADO = {"alto": 0.41, "bajo": 0.45}
CATEGORIA_INCIERTA = "incierta"
def note_2025() -> str:
    return t(es="2025: el valor es el que registra VIIRS. MODIS cae más que VIIRS ese año (posible "
                "deriva orbital, no verificada), pero no afecta a la serie, que usa VIIRS desde "
                "2013. El último día (31-dic) puede estar incompleto.",
             en="2025: the value is what VIIRS recorded. MODIS drops more than VIIRS that year "
                "(possible orbital drift, not verified), but this does not affect the series, "
                "which uses VIIRS since 2013. The last day (Dec 31) may be incomplete.")


def note_extrapolado() -> str:
    return t(es="2000-11 a 2002-06: solo Terra, escalado con kT (calidad 'extrapolado', error "
                "mensual ~41–45 %). Se muestra atenuado y con su margen ('rango'); si el margen "
                "cruza de categoría, la anomalía se marca 'incierta'.",
             en="2000-11 to 2002-06: Terra only, scaled with kT (quality 'extrapolado', monthly "
                "error ~41–45 %). Shown faded and with its margin ('rango'); if the margin crosses "
                "a category, the anomaly is marked 'incierta' (uncertain).")


def note_custom() -> str:
    return t(es="Área dibujada: el total es la suma de eq_foco de los focos dentro del área "
                "(igual a la suma de la descarga CSV).",
             en="Drawn area: the total is the sum of eq_foco of the hotspots inside the area "
                "(equal to the sum of the CSV download).")


class PlanError(ValueError):
    """Error de la consulta con mensaje claro para el usuario (se responde 422)."""


class PlanNoData(LookupError):
    """La consulta es válida pero no hay datos (se responde 404 'sin datos')."""


class PlanNotReady(RuntimeError):
    """Todavía no se cargaron los datos (se responde 503)."""


@dataclass(frozen=True)
class AOI:
    kind: str                      # departamento | bbox | punto
    sql: str                       # condición WHERE sobre la tabla de focos (latitude/longitude)
    params: tuple
    label: str
    area_km2: float | None = None
    bbox: tuple[float, float, float, float] | None = None

    @property
    def whole_region(self) -> bool:
        return self.kind == "departamento"

    def info(self) -> dict:
        out = {"tipo": self.kind, "descripcion": self.label,
               "area_km2": None if self.area_km2 is None else round(self.area_km2, 1)}
        if self.bbox is not None:
            out["bbox"] = [round(v, 4) for v in self.bbox]
        return out


def parse_month(value: str | None, name: str) -> tuple[int, int] | None:
    if value in (None, ""):
        return None
    try:
        if not re.fullmatch(r"\d{4}-\d{2}", value.strip()):
            raise ValueError
        y, m = (int(v) for v in value.strip().split("-"))
        if not 1 <= m <= 12:
            raise ValueError
    except ValueError as exc:
        raise PlanError(t(es=f"Valor no válido para {name} ('{value}'): usa el formato "
                             "AAAA-MM, p. ej. 2020-08.",
                          en=f"Invalid {name} ('{value}'): use the YYYY-MM format, "
                             "e.g. 2020-08.")) from exc
    return y, m


def no_fire(aoi: AOI) -> str:
    """Área de Cusco donde los satélites nunca detectaron fuego (QA de Erik, 13)."""
    return t(es=f"No se detectaron focos en {aoi.label} entre {COVER_FROM[0]} y {COVER_TO[0]}.",
             en=f"No hotspots were detected in {aoi.label} between {COVER_FROM[0]} and "
                f"{COVER_TO[0]}.")


def month_quality(y: int, m: int, fraccion_extrapolada: float | None = None) -> tuple[str, str]:
    """(calidad, fuente_serie) del mes.

    Con focos manda la columna ``calidad`` de los datos (fracción del valor que es extrapolada);
    sin focos, la fecha. Idea de Antonio (rama antonio/backend-modelo): así julio de 2002, cuyos
    focos son todos Terra + Aqua, queda como ``referencia`` y no como mixto.
    """
    if fraccion_extrapolada is not None:
        if fraccion_extrapolada >= 1.0 - 1e-9:          # tolera el redondeo de la suma
            calidad = "extrapolado"
        elif fraccion_extrapolada > 1e-9:
            calidad = "mixto"
        else:
            calidad = "referencia" if (y, m) < VIIRS_FROM else "calibrado"
    elif (y, m) < REFERENCIA_FROM:
        calidad = "extrapolado"
    else:
        calidad = "referencia" if (y, m) < VIIRS_FROM else "calibrado"
    return calidad, FUENTE[calidad]


def category(anom: float | None) -> str | None:
    if anom is None:
        return None
    for edge, name in CATEGORY_EDGES:
        if anom < edge:
            return name
    return CATEGORY_EDGES[-1][1]


def _num(x, digits: int = 2):
    if x is None:
        return None
    f = float(x)
    return None if math.isnan(f) else round(f, digits)


def _month_range(a: tuple[int, int], b: tuple[int, int]) -> list[tuple[int, int]]:
    out, (y, m) = [], a
    while (y, m) <= b:
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def color_breaks(values: list[float]) -> list[float]:
    """Cortes de la rampa (METHODOLOGY.md): cuantiles 50/75/90/99 de los meses con fuego."""
    v = np.array([x for x in values if x and x > 0], dtype=float)
    if v.size == 0:
        return []
    qs = np.quantile(v, [0.5, 0.75, 0.9, 0.99])
    out = []
    for q in qs:
        r = round(float(q)) if q >= 10 else round(float(q), 1)
        if not out or r > out[-1]:
            out.append(r)
    return out


class PlanStore:
    """Datos de Cusco en tablas de DuckDB en memoria (cargadas del Parquet) y un cursor por
    consulta."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._lock = threading.Lock()
        self._con: duckdb.DuckDBPyConnection | None = None
        self._stamp: float | None = None
        self._meta: dict = {}
        self._region_geojson: dict = {}
        self._region = None
        self._monthly_cache: dict[tuple, pd.DataFrame] = {}
        self._flight = SingleFlight()

    # ---------------------------------------------------------------- carga
    @property
    def ready(self) -> bool:
        return meta_path(self.settings).is_file()

    def data_version(self) -> float | None:
        """Marca de los datos cargados en disco (fecha de ``plan_meta.json``); ``None`` si no hay.
        La usa la caché de respuestas (api.cache) para no repetir respuestas de datos viejos."""
        try:
            return meta_path(self.settings).stat().st_mtime
        except OSError:
            return None

    def _ensure(self) -> duckdb.DuckDBPyConnection:
        if not self.ready:
            raise PlanNotReady(t(es="Aún no se cargaron los datos de Cusco. Corre: "
                                    "firecal plan-events",
                                 en="Cusco data is not loaded yet. Run: firecal plan-events"))
        stamp = meta_path(self.settings).stat().st_mtime
        with self._lock:
            if self._con is None or stamp != self._stamp:
                if self._con is not None:
                    self._con.close()
                con = duckdb.connect()
                base = plan_dir(self.settings)
                # TABLAS en memoria, no vistas: una vista reabre los ~560 archivos Parquet en cada
                # consulta (~630 de los ~790 ms de focos.geojson de un año). Son ~95.000 filas:
                # cargarlas cuesta ~1,6 s una sola vez y ~20 MB (prueba de carga del 14-nov).
                for name, sub in (("cd", "celda_dia"), ("fo", "focos")):
                    glob = (base / sub / "**" / "*.parquet").as_posix()
                    con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{glob}', "
                                "hive_partitioning = true)")
                self._con, self._stamp = con, stamp
                self._monthly_cache.clear()
                self._flight.clear()
                self._meta = json.loads(meta_path(self.settings).read_text(encoding="utf-8"))
                self._region_geojson = json.loads(
                    region_path(self.settings).read_text(encoding="utf-8"))
                self._region = shape(self._region_geojson["features"][0]["geometry"])
            return self._con

    def cursor(self) -> duckdb.DuckDBPyConnection:
        return self._ensure().cursor()

    @property
    def meta(self) -> dict:
        self._ensure()
        return self._meta

    @property
    def region_geom(self):
        """Contorno de Cusco (shapely); lo usa la capa en tiempo real (firecal.nrt)."""
        self._ensure()
        return self._region

    @property
    def region_geojson(self) -> dict:
        self._ensure()
        return self._region_geojson

    # ---------------------------------------------------------------- AOI
    def resolve_aoi(self, departamento: str | None = None, bbox: str | None = None,
                    lat: float | None = None, lon: float | None = None,
                    radio_km: float | None = None) -> AOI:
        api = self.settings.params.api
        self._ensure()
        given = [departamento not in (None, ""), bbox not in (None, ""),
                 lat is not None or lon is not None]
        if sum(given) == 0:
            raise PlanError(t(es="AOI vacío: indica 'departamento' (PE-CUS), 'bbox' "
                                 "(oeste,sur,este,norte) o 'lat', 'lon' y 'radio_km'.",
                              en="Empty AOI: give 'departamento' (PE-CUS), 'bbox' "
                                 "(west,south,east,north) or 'lat', 'lon' and 'radio_km'."))
        if sum(given) > 1:
            raise PlanError(t(es="Indica un solo tipo de AOI: departamento, bbox o punto + "
                                 "radio.",
                              en="Give only one type of AOI: departamento, bbox or point + "
                                 "radius."))
        if departamento:
            code = departamento.strip().upper()
            if code not in (REGION_CODE, "CUSCO", "CUZCO"):
                raise PlanNoData(t(
                    es=f"Sin datos para '{departamento}': el prototipo solo tiene datos "
                       f"armonizados y validados de {REGION_NAME} ({REGION_CODE}).",
                    en=f"No data for '{departamento}': the prototype only has harmonized, "
                       f"validated data for {REGION_NAME} ({REGION_CODE})."))
            return AOI("departamento", "TRUE", (), REGION_NAME,
                       geodesic_area_km2(self._region))
        if bbox:
            try:
                w, s, e, n = (float(v) for v in bbox.split(","))
            except ValueError as exc:
                raise PlanError(t(es="bbox inválido: usa 'oeste,sur,este,norte' en grados, "
                                     "p. ej. -72.5,-14,-71.5,-13.",
                                  en="Invalid bbox: use 'west,south,east,north' in degrees, "
                                     "e.g. -72.5,-14,-71.5,-13.")) from exc
            if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
                raise PlanError(t(es="bbox inválido: se espera oeste < este y sur < norte "
                                     "(WGS84).",
                                  en="Invalid bbox: expected west < east and south < north "
                                     "(WGS84)."))
            geom = box(w, s, e, n)
            area = geodesic_area_km2(geom)
            if area > api.max_aoi_km2:
                raise PlanError(t(
                    es=f"Área demasiado grande: el bbox mide {area:,.0f} km² y el máximo es "
                       f"{api.max_aoi_km2:,.0f} km². Usa el departamento o un área menor.",
                    en=f"Area too large: the bbox covers {area:,.0f} km² and the maximum is "
                       f"{api.max_aoi_km2:,.0f} km². Use the department or a smaller area."))
            self._require_inside(geom)
            return AOI("bbox", "longitude BETWEEN ? AND ? AND latitude BETWEEN ? AND ?",
                       (w, e, s, n), t(es="el área seleccionada", en="the selected area"), area,
                       bbox=(w, s, e, n))
        if lat is None or lon is None or radio_km is None:
            raise PlanError(t(es="Para un punto indica 'lat', 'lon' y 'radio_km'.",
                              en="For a point give 'lat', 'lon' and 'radio_km'."))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise PlanError(t(es="lat/lon fuera de rango (WGS84).",
                              en="lat/lon out of range (WGS84)."))
        if not 0 < radio_km <= api.max_point_radius_km:
            raise PlanError(t(es=f"radio_km debe ser mayor que 0 y como máximo "
                                 f"{api.max_point_radius_km} km.",
                              en=f"radio_km must be greater than 0 and at most "
                                 f"{api.max_point_radius_km} km."))
        self._require_inside(buffer_km(Point(lon, lat), radio_km))
        dlat = radio_km / 111.0
        dlon = radio_km / (111.0 * max(math.cos(math.radians(lat)), 0.01))
        sql = ("latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ? AND "
               f"2 * {EARTH_KM} * asin(sqrt(pow(sin(radians(latitude - ?) / 2), 2) + "
               "cos(radians(?)) * cos(radians(latitude)) * "
               "pow(sin(radians(longitude - ?) / 2), 2))) <= ?")
        params = (lat - dlat, lat + dlat, lon - dlon, lon + dlon, lat, lat, lon, radio_km)
        label = t(es=f"{radio_km} km alrededor de ({lat}, {lon})",
                  en=f"{radio_km} km around ({lat}, {lon})")
        return AOI("punto", sql, params, label,
                   math.pi * radio_km ** 2)

    def _require_inside(self, geom) -> None:
        if not geom.intersects(self._region):
            raise PlanNoData(t(es=f"Sin datos: el área está fuera de {REGION_NAME}, la única "
                                  "región con datos armonizados y validados.",
                               en=f"No data: the area is outside {REGION_NAME}, the only region "
                                  "with harmonized, validated data."))

    # ---------------------------------------------------------------- series
    def monthly(self, aoi: AOI) -> pd.DataFrame:
        """Serie mensual 2000-11..2025-12 (ceros reales dentro de la cobertura) + anomalía.

        Se guarda en memoria por AOI; un candado por AOI (``SingleFlight``) evita calcular la
        misma serie varias veces a la vez.
        """
        key = (aoi.kind, aoi.sql, aoi.params)

        def compute() -> pd.DataFrame:
            df = self._monthly(aoi)
            if len(self._monthly_cache) > 256:
                self._monthly_cache.clear()
            self._monthly_cache[key] = df
            return df

        return self._flight.run(key, lambda: self._monthly_cache.get(key), compute)

    def _monthly(self, aoi: AOI) -> pd.DataFrame:
        """Σ focos armonizados por mes (con ceros), calidad, margen, mediana y anomalía.

        Margen de los meses con focos extrapolados (método de Antonio, antonio/backend-modelo):
        ``incertidumbre`` = error mensual del estrato (41 % sobre 2500 m y 45 % debajo, §7)
        x focos armonizados extrapolados; ``rango`` = valor ± incertidumbre (mínimo 0) y
        ``anomalia_rango`` su efecto en la anomalía. Si el rango cruza de categoría, la categoría
        es ``incierta``.
        """
        cur = self.cursor()
        if aoi.whole_region:
            df = cur.execute(
                "SELECT anio, mes, sum(eq_hotspots) AS focos_armonizados, count(*) AS celdas_dia, "
                "sum(n_modis) AS focos_modis, sum(n_viirs) AS focos_viirs, "
                "sum(CASE WHEN calidad = 'extrapolado' AND alt_m >= 2500 THEN eq_hotspots "
                "ELSE 0 END) AS ext_alto, "
                "sum(CASE WHEN calidad = 'extrapolado' AND NOT coalesce(alt_m >= 2500, false) "
                "THEN eq_hotspots ELSE 0 END) AS ext_bajo "
                "FROM cd GROUP BY 1, 2").df()
        else:
            df = cur.execute(
                "SELECT anio, mes, sum(eq_foco) AS focos_armonizados, "
                "count(DISTINCT CASE WHEN en_serie = 1 THEN fecha_local || '|' || cell_lat || '|' "
                "|| cell_lon END) AS celdas_dia, "
                "count(*) FILTER (WHERE sensor = 'MODIS') AS focos_modis, "
                "count(*) FILTER (WHERE sensor = 'VIIRS') AS focos_viirs, "
                "sum(CASE WHEN calidad = 'extrapolado' AND alt_m >= 2500 THEN eq_foco "
                "ELSE 0 END) AS ext_alto, "
                "sum(CASE WHEN calidad = 'extrapolado' AND NOT coalesce(alt_m >= 2500, false) "
                "THEN eq_foco ELSE 0 END) AS ext_bajo "
                f"FROM fo WHERE {aoi.sql} GROUP BY 1, 2", list(aoi.params)).df()
        cur.close()
        months = _month_range(COVER_FROM, COVER_TO)
        full = pd.DataFrame(months, columns=["anio", "mes"])
        full = full.merge(df.astype({"anio": int, "mes": int}), on=["anio", "mes"], how="left")
        for c in ("focos_armonizados", "celdas_dia", "focos_modis", "focos_viirs", "ext_alto",
                  "ext_bajo"):
            full[c] = full[c].fillna(0).astype(float)
        ext = full["ext_alto"] + full["ext_bajo"]
        con_focos = full["focos_armonizados"] > 0
        full["fraccion_extrapolada"] = (ext / full["focos_armonizados"].where(con_focos, 1.0)
                                        ).clip(0, 1)
        q = [month_quality(y, m, f if tiene else None) for (y, m), f, tiene
             in zip(months, full["fraccion_extrapolada"], con_focos, strict=True)]
        full["calidad"] = [c for c, _ in q]
        full["fuente_serie"] = [f for _, f in q]
        full["parcial"] = [(y, m) == COVER_FROM for y, m in months]   # empieza el 2000-11-04
        full["incertidumbre"] = (ERROR_EXTRAPOLADO["alto"] * full["ext_alto"]
                                 + ERROR_EXTRAPOLADO["bajo"] * full["ext_bajo"])
        full["n_min"] = (full["focos_armonizados"] - full["incertidumbre"]).clip(lower=0.0)
        full["n_max"] = full["focos_armonizados"] + full["incertidumbre"]

        # Historia de la mediana: solo meses completos sin focos extrapolados.
        base = full[full["calidad"].isin(["referencia", "calibrado"]) & ~full["parcial"]]
        stats = base.groupby("mes")["focos_armonizados"].agg(
            mediana_hist="median", p25=lambda s: s.quantile(0.25),
            p75=lambda s: s.quantile(0.75), n_anios="size").reset_index()
        full = full.merge(stats, on="mes", how="left")
        iqr = np.maximum(full["p75"] - full["p25"], 1.0)
        ok = (full["n_anios"] >= MIN_YEARS) & ~full["parcial"]
        for col, src in (("anomalia", "focos_armonizados"), ("anomalia_min", "n_min"),
                         ("anomalia_max", "n_max")):
            full[col] = ((full[src] - full["mediana_hist"]) / iqr).where(ok)
        return full

    @staticmethod
    def _row_category(r) -> str | None:
        """Categoría de la anomalía; ``incierta`` si el margen la hace cruzar de categoría."""
        cat = category(_num(r.anomalia))
        if cat is None or not r.incertidumbre:
            return cat
        lo, hi = category(_num(r.anomalia_min)), category(_num(r.anomalia_max))
        return cat if lo == hi else CATEGORIA_INCIERTA

    @staticmethod
    def _margin(r) -> dict:
        return {"incertidumbre": _num(r.incertidumbre, 1),
                "rango": [_num(r.n_min, 1), _num(r.n_max, 1)],
                "anomalia_rango": [_num(r.anomalia_min), _num(r.anomalia_max)]}

    def _range(self, inicio: str | None, fin: str | None) -> tuple[tuple, tuple]:
        a = parse_month(inicio, "fecha_inicio") or COVER_FROM
        b = parse_month(fin, "fecha_fin") or COVER_TO
        if a > b:
            raise PlanError(t(
                es=f"Rango invertido: fecha_inicio ({a[0]}-{a[1]:02d}) es posterior a "
                   f"fecha_fin ({b[0]}-{b[1]:02d}).",
                en=f"Inverted range: fecha_inicio ({a[0]}-{a[1]:02d}) is after "
                   f"fecha_fin ({b[0]}-{b[1]:02d})."))
        if b < COVER_FROM or a > COVER_TO:
            raise PlanNoData(t(
                es=f"Sin datos: la serie cubre de {COVER_FROM[0]}-{COVER_FROM[1]:02d} "
                   f"(desde el 2000-11-04) a {COVER_TO[0]}-{COVER_TO[1]:02d}.",
                en=f"No data: the series covers {COVER_FROM[0]}-{COVER_FROM[1]:02d} "
                   f"(from 2000-11-04) to {COVER_TO[0]}-{COVER_TO[1]:02d}."))
        # QA de Erik (3): 2020-01..9999-12 armaba 7 980 años vacíos (4,7 MB, 2 s). Se recorta a
        # los años de la cobertura; ene-oct de 2000 siguen saliendo como "sin dato".
        return max(a, (COVER_FROM[0], 1)), min(b, (COVER_TO[0], 12))

    def _row(self, aoi: AOI, ym: tuple[int, int]):
        full = self.monthly(aoi)
        return full, next(full[(full["anio"] == ym[0]) & (full["mes"] == ym[1])]
                          .itertuples(index=False))

    def calendar(self, aoi: AOI, inicio: str | None, fin: str | None) -> dict:
        a, b = self._range(inicio, fin)
        full = self.monthly(aoi)
        if full["focos_modis"].sum() + full["focos_viirs"].sum() == 0:
            raise PlanNoData(no_fire(aoi))
        by_key = {(int(r.anio), int(r.mes)): r for r in full.itertuples(index=False)}
        months = _month_range(a, b)
        years = sorted({y for y, _ in months})
        mat_v = [[None] * 12 for _ in years]
        mat_a = [[None] * 12 for _ in years]
        cells, values, total = [], [], 0.0
        for y, m in months:
            i, j = years.index(y), m - 1
            r = by_key.get((y, m))
            if r is None:                       # fuera de la cobertura: sin dato, no cero
                cells.append({"anio": y, "mes": m, "sin_dato": True})
                continue
            v, anom = _num(r.focos_armonizados, 2), _num(r.anomalia)
            mat_v[i][j], mat_a[i][j] = v, anom
            values.append(v)
            total += float(r.focos_armonizados)
            cells.append({"anio": y, "mes": m, "sin_dato": False, "focos_armonizados": v,
                          "celdas_dia": int(r.celdas_dia), "focos_modis": int(r.focos_modis),
                          "focos_viirs": int(r.focos_viirs), "mediana_hist": _num(r.mediana_hist),
                          "anomalia": anom, "categoria": self._row_category(r),
                          "calidad": r.calidad,
                          "fraccion_extrapolada": _num(r.fraccion_extrapolada, 3),
                          **self._margin(r),
                          "fuente_serie": r.fuente_serie, "parcial": bool(r.parcial)})
        notes = []
        if any(c.get("calidad") in ("extrapolado", "mixto") for c in cells):
            notes.append(note_extrapolado())
        if any(c["anio"] == 2025 and not c["sin_dato"] for c in cells):
            notes.append(note_2025())
        if any(c["sin_dato"] for c in cells):
            notes.append(t(es="Meses sin dato (fuera de 2000-11-04 a 2025-12-31) en gris: no son "
                              "cero.",
                           en="Months without data (outside 2000-11-04 to 2025-12-31) in grey: "
                              "they are not zero."))
        if not aoi.whole_region:
            notes.append(note_custom())
        return {"aoi": aoi.info(), "unidad": unidad(), "fecha_inicio": f"{a[0]}-{a[1]:02d}",
                "fecha_fin": f"{b[0]}-{b[1]:02d}", "anios": years, "meses": list(range(1, 13)),
                "matriz_focos_armonizados": mat_v, "matriz_anomalia": mat_a,
                "total_focos_armonizados": round(total, 2), "cortes_color": color_breaks(values),
                "celdas": cells, "notes": notes}

    def anomaly(self, aoi: AOI, mes: str) -> dict:
        ym = parse_month(mes, "mes")
        if ym is None:
            raise PlanError(t(es="Indica 'mes' con el formato AAAA-MM.",
                              en="Give 'mes' in the YYYY-MM format."))
        if not COVER_FROM <= ym <= COVER_TO:
            raise PlanNoData(t(es=f"Sin datos para {mes}: la serie cubre de 2000-11 a 2025-12.",
                               en=f"No data for {mes}: the series covers 2000-11 to 2025-12."))
        full, r = self._row(aoi, ym)
        hist = full[(full["mes"] == ym[1]) & full["calidad"].isin(["referencia", "calibrado"])
                    & ~full["parcial"]]
        cur = self.cursor()
        if aoi.whole_region:
            days = cur.execute("SELECT fecha_local, sum(eq_hotspots) FROM cd WHERE anio = ? AND "
                               "mes = ? GROUP BY 1 ORDER BY 1", [ym[0], ym[1]]).fetchall()
        else:
            days = cur.execute(f"SELECT fecha_local, sum(eq_foco) FROM fo WHERE {aoi.sql} AND "
                               "anio = ? AND mes = ? AND en_serie = 1 GROUP BY 1 ORDER BY 1",
                               [*aoi.params, ym[0], ym[1]]).fetchall()
        cur.close()
        anom = _num(r.anomalia)
        notes = []
        if r.calidad in ("extrapolado", "mixto"):
            notes.append(note_extrapolado())
        if ym[0] == 2025:
            notes.append(note_2025())
        if anom is None and not bool(r.parcial):
            notes.append(t(es=f"Sin anomalía: hay menos de {MIN_YEARS} años de historia.",
                           en=f"No anomaly: there are fewer than {MIN_YEARS} years of history."))
        if bool(r.parcial):
            notes.append(t(es="Mes parcial (la serie empieza el 2000-11-04): sin anomalía.",
                           en="Partial month (the series starts on 2000-11-04): no anomaly."))
        return {"aoi": aoi.info(), "unidad": unidad(), "mes": f"{ym[0]}-{ym[1]:02d}",
                "focos_armonizados": _num(r.focos_armonizados),
                "celdas_dia": int(r.celdas_dia),
                "focos_modis": int(r.focos_modis), "focos_viirs": int(r.focos_viirs),
                "calidad": r.calidad, "fuente_serie": r.fuente_serie,
                "fraccion_extrapolada": _num(r.fraccion_extrapolada, 3), **self._margin(r),
                "mediana_hist": _num(r.mediana_hist), "p25": _num(r.p25),
                "p75": _num(r.p75), "n_anios_hist": int(r.n_anios or 0),
                "anomalia": anom, "categoria": self._row_category(r),
                "parcial": bool(r.parcial),
                "historial": [{"anio": int(x.anio), "focos_armonizados": _num(x.focos_armonizados)}
                              for x in hist.itertuples(index=False)],
                "dias": [{"fecha_local": d, "focos_armonizados": _num(v, 3)} for d, v in days],
                "notes": notes}

    # ---------------------------------------------------------------- puntos para el mapa
    def focos_geojson(self, aoi: AOI, inicio: str | None, fin: str | None) -> dict:
        """Focos del rango como GeoJSON para el mapa. Peso = ``eq_foco`` (sin FRP)."""
        if inicio in (None, "") or fin in (None, ""):
            raise PlanError(t(es="Para el mapa indica 'fecha_inicio' y 'fecha_fin' (AAAA-MM).",
                              en="For the map give 'fecha_inicio' and 'fecha_fin' (YYYY-MM)."))
        a, b = self._range(inicio, fin)
        where = f"WHERE {aoi.sql} AND (anio * 100 + mes) BETWEEN ? AND ?"
        params = [*aoi.params, a[0] * 100 + a[1], b[0] * 100 + b[1]]
        limit = self.settings.params.api.max_geojson_features
        cur = self.cursor()
        n = cur.execute(f"SELECT count(*) FROM fo {where}", params).fetchall()[0][0]
        if n > limit:
            cur.close()
            raise PlanError(t(
                es=f"El mapa tendría {n:,} focos; el máximo es {limit:,}. Usa un rango de fechas "
                   "menor (la descarga CSV no tiene este límite).",
                en=f"The map would have {n:,} hotspots; the maximum is {limit:,}. Use a shorter "
                   "date range (the CSV download has no such limit)."))
        rows = cur.execute(
            "SELECT longitude, latitude, fecha_local, hora_utc, sensor, satelite, eq_foco, "
            f"en_serie, calidad FROM fo {where} ORDER BY fecha_local, hora_utc", params).fetchall()
        cur.close()
        feats = [{"type": "Feature",
                  "geometry": {"type": "Point", "coordinates": [round(x, 5), round(y, 5)]},
                  "properties": {"fecha_local": f, "hora_utc": h, "sensor": s, "satelite": sat,
                                 "eq_foco": round(float(w), 4), "en_serie": int(e),
                                 "calidad": c or ""}}
                 for x, y, f, h, s, sat, w, e, c in rows]
        total = round(sum(f["properties"]["eq_foco"] for f in feats), 2)
        return {"type": "FeatureCollection", "aoi": aoi.info(),
                "fecha_inicio": f"{a[0]}-{a[1]:02d}", "fecha_fin": f"{b[0]}-{b[1]:02d}",
                "n_focos": len(feats), "total_focos_armonizados": total,
                "features": feats, "notes": []}

    # ---------------------------------------------------------------- CSV
    def hotspots_query(self, aoi: AOI, inicio: str | None, fin: str | None
                       ) -> tuple[str, list, int, float]:
        """SQL de la descarga (18 columnas del contrato de focos), n.º de filas y Σ eq_foco."""
        if inicio in (None, "") or fin in (None, ""):
            raise PlanError(t(es="Para la descarga indica 'fecha_inicio' y 'fecha_fin' "
                                 "(AAAA-MM).",
                              en="For the download give 'fecha_inicio' and 'fecha_fin' "
                                 "(YYYY-MM)."))
        a, b = self._range(inicio, fin)
        where = f"WHERE {aoi.sql} AND (anio * 100 + mes) BETWEEN ? AND ?"
        params = [*aoi.params, a[0] * 100 + a[1], b[0] * 100 + b[1]]
        cur = self.cursor()
        n, total = cur.execute(f"SELECT count(*), coalesce(sum(eq_foco), 0) FROM fo {where}",
                               params).fetchall()[0]
        cur.close()
        max_rows = self.settings.params.api.max_csv_rows
        if n > max_rows:
            raise PlanError(t(es=f"La descarga tendría {n:,} filas; el máximo es "
                                 f"{max_rows:,}. Usa un rango de fechas o un área menor.",
                              en=f"The download would have {n:,} rows; the maximum is "
                                 f"{max_rows:,}. Use a shorter date range or a smaller area."))
        sql = (f"SELECT {', '.join(COLS_FOCOS)} FROM fo {where} "
               "ORDER BY fecha_utc, hora_utc, latitude, longitude")
        return sql, params, int(n), float(total)

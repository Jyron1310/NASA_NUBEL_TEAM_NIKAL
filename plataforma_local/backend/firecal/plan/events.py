"""Carga de los datos armonizados reales de Cusco (Antonio, METHODOLOGY.md) -> Parquet.

Fuente de verdad: los dos CSV de ``data/harmonized/`` (ver ``firecal.plan.sources``). Este paso:

1. Verifica el contrato: columnas y orden, filas, suma de pesos y SHA-256 (METHODOLOGY §14). Si algo
   no coincide, se detiene (los datos cambiaron: hay que investigar antes de servirlos).
2. Escribe Parquet por año y mes (docs/team/PLAN.md §3), que la API consulta con DuckDB:
   ``celda_dia/anio=/mes=`` (calendario) y ``focos/anio=/mes=`` (descarga y AOI dibujados).
3. Escribe el límite de Cusco (FAO GAUL, ``cusco_ref/limite.json``) en GeoJSON para el mapa.

No se recalcula ningún peso: ``eq_hotspots`` y ``eq_foco`` se usan tal cual (METHODOLOGY.md).
``hora_utc`` y ``confianza`` se leen como texto (METHODOLOGY.md).
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from shapely.geometry import MultiPolygon, Polygon, mapping

from firecal.plan.sources import (
    CELDA_DIA_CSV,
    COLS_CELDA_DIA,
    COLS_FOCOS,
    CONTROL,
    FOCOS_CSV,
    REGION_CODE,
    REGION_NAME,
    cusco_ref_dir,
    harmonized_dir,
)
from firecal.settings import Settings

log = logging.getLogger(__name__)

PLAN_DIRNAME = "plan"
META_FILENAME = "plan_meta.json"
REGION_FILENAME = "cusco_limite.geojson"
PLAN_VERSION = "cusco-v1.3"            # = versión de los datos (METHODOLOGY.md)

ALTO_M = 2500                          # estrato de altitud de los factores k y kT


class DataContractError(ValueError):
    """Los CSV no cumplen el contrato o las sumas de control de METHODOLOGY.md §14."""


def plan_dir(settings: Settings) -> Path:
    return settings.paths.processed_dir / PLAN_DIRNAME


def meta_path(settings: Settings) -> Path:
    return plan_dir(settings) / META_FILENAME


def region_path(settings: Settings) -> Path:
    return plan_dir(settings) / REGION_FILENAME


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _check(name: str, path: Path, df: pd.DataFrame, cols: list[str], weight: str,
           strict: bool) -> dict:
    expected = CONTROL[name]
    got = {"filas": len(df), "suma": round(float(df[weight].sum()), 2), "sha256": _sha256(path)}
    problems = []
    if list(df.columns) != cols:
        problems.append(f"columnas distintas al contrato: {list(df.columns)}")
    if got["filas"] != expected["filas"]:
        problems.append(f"filas {got['filas']} (esperadas {expected['filas']})")
    if abs(got["suma"] - expected["suma"]) > 0.01:
        problems.append(f"suma de {weight} {got['suma']} (esperada {expected['suma']})")
    if got["sha256"] != expected["sha256"]:
        problems.append("SHA-256 distinto al de METHODOLOGY.md seccion 14")
    if problems and strict:
        raise DataContractError(
            f"{path.name}: " + "; ".join(problems) + ". Los datos cambiaron: corre "
            "harmonizacion/verificar_datos.py, revisa METHODOLOGY.md seccion 14 y actualiza "
            "firecal/plan/sources.py::CONTROL solo si el cambio es intencional.")
    return {**got, "coincide_maestro": not problems, "problemas": problems}


def read_sources(strict: bool = True) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Lee y valida los dos CSV. Devuelve (celda_dia, focos, resultado de los controles)."""
    src = harmonized_dir()
    cd_path, fo_path = src / CELDA_DIA_CSV, src / FOCOS_CSV
    cd = pd.read_csv(cd_path, dtype={"fecha_local": str, "fuente_serie": str, "calidad": str})
    fo = pd.read_csv(fo_path, dtype={"fecha_local": str, "fecha_utc": str, "hora_utc": str,
                                     "confianza": str, "sensor": str, "satelite": str,
                                     "fuente_serie": str, "calidad": str})
    fo["calidad"] = fo["calidad"].fillna("")      # vacío = fuera de serie (contrato de focos)
    controls = {"celda_dia": _check("celda_dia", cd_path, cd, COLS_CELDA_DIA, "eq_hotspots",
                                    strict),
                "focos": _check("focos", fo_path, fo, COLS_FOCOS, "eq_foco", strict)}
    return cd, fo, controls


def cusco_geometry() -> MultiPolygon:
    """Límite de Cusco (FAO GAUL 2015 simplificado). Igual que los scripts de Antonio: solo los
    ``Polygon`` del GeometryCollection y su anillo exterior."""
    lim = json.loads((cusco_ref_dir() / "limite.json").read_text(encoding="utf-8"))
    geoms = lim["geometries"] if lim["type"] == "GeometryCollection" else [lim]
    polys = [Polygon(g["coordinates"][0]) for g in geoms if g["type"] == "Polygon"]
    if not polys:
        raise DataContractError("cusco_ref/limite.json no tiene poligonos.")
    polys = [p if p.is_valid else p.buffer(0) for p in polys]
    parts = [q for p in polys for q in (p.geoms if isinstance(p, MultiPolygon) else [p])]
    return MultiPolygon(parts)


def _add_partitions(df: pd.DataFrame) -> pd.DataFrame:
    return df.assign(anio=df["fecha_local"].str[:4].astype("int32"),
                     mes=df["fecha_local"].str[5:7].astype("int32"))


def _write_parquet(df: pd.DataFrame, out: Path) -> None:
    con = duckdb.connect()
    try:
        con.register("_t", df)
        con.execute("COPY (SELECT * FROM _t ORDER BY anio, mes, fecha_local) "
                    f"TO '{out.as_posix()}' "
                    "(FORMAT parquet, PARTITION_BY (anio, mes), COMPRESSION zstd)")
    finally:
        con.close()


def _factors(cd: pd.DataFrame) -> dict:
    """Factores tal como vienen en los datos (no se recalculan): un valor por fuente y estrato."""
    est = np.where(cd["alt_m"] >= ALTO_M, "alto", "bajo")
    g = cd.assign(estrato=est).groupby(["fuente_serie", "estrato"])["eq_hotspots"].first()
    return {f"{f}|{e}": round(float(v), 3) for (f, e), v in g.items()}


def build_events(settings: Settings, strict: bool = True) -> dict:
    """CSV armonizados de Cusco -> Parquet (celda_dia, focos) + límite + metadatos."""
    cd, fo, controls = read_sources(strict=strict)
    out = plan_dir(settings)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    _write_parquet(_add_partitions(cd), out / "celda_dia")
    _write_parquet(_add_partitions(fo), out / "focos")

    geom = cusco_geometry()
    simple = geom.simplify(0.002, preserve_topology=True)
    region_path(settings).write_text(json.dumps({
        "type": "FeatureCollection",
        "features": [{"type": "Feature", "geometry": mapping(simple),
                      "properties": {"code": REGION_CODE, "name": REGION_NAME,
                                     "fuente": "FAO GAUL 2015 nivel 1 (simplificado)"}}]},
        ensure_ascii=False), encoding="utf-8")

    fechas = cd["fecha_local"]
    meta = {
        "plan_version": PLAN_VERSION,
        "data_mode": "real",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "fuente": "NASA FIRMS (MODIS Terra/Aqua y VIIRS S-NPP), armonizado (METHODOLOGY.md)",
        "region": {"code": REGION_CODE, "name": REGION_NAME,
                   "bbox": [round(v, 4) for v in geom.bounds]},
        "primer_dia": str(fechas.min()), "ultimo_dia": str(fechas.max()),
        "cobertura_desde": "2000-11-04", "cobertura_hasta": "2025-12-31",
        "controles": controls,
        "factores": _factors(cd),
        "filas_por_fuente": cd["fuente_serie"].value_counts().to_dict(),
        "focos_por_sensor": fo["sensor"].value_counts().to_dict(),
    }
    meta_path(settings).write_text(json.dumps(meta, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
    log.info("Datos de Cusco: %d celdas-dia, %d focos (%s)", len(cd), len(fo), out)
    return meta

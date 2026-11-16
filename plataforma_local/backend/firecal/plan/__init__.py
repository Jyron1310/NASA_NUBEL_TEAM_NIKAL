"""Capa del plan (docs/team/PLAN.md): A (grilla común de 1 km) + C (anomalías normalizadas).

- ``events``: eventos armonizados MODIS+VIIRS deduplicados por celda de 1 km y día -> Parquet
  particionado por año y mes.
- ``query``: consultas por AOI (departamento, bbox o punto + radio) sobre ese Parquet con DuckDB:
  calendario mes x año, anomalía normalizada por era de sensores y descarga CSV.
"""

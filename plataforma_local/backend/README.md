# Nikal backend

FastAPI + DuckDB API that serves the harmonized Cusco data (`data/harmonized/`, method in [`METHODOLOGY.md`](../../METHODOLOGY.md))
and the compiled interface (`../frontend/dist`). The full guide (setup, endpoints, request limits, deployment) is in
[`../README.md`](../README.md).

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements-lock.txt
.\.venv\Scripts\python -m pip install -e . --no-deps
$env:PYTHONUTF8 = "1"
.\.venv\Scripts\firecal plan-events      # checks the CSVs against the published checksums and builds the Parquet (~2 s)
.\.venv\Scripts\firecal serve            # http://localhost:8000  (API under /api, docs at /docs)
.\.venv\Scripts\python -m pytest -q      # test suite
```

| Folder | Contents |
| --- | --- |
| `firecal/plan/` | `sources.py` (data contract and checksums), `events.py` (CSV → Parquet), `query.py` (calendar, anomaly, area of interest, downloads), `analitica.py` (plain-language analytics), `ambitos.py` (hazard level by province, district and basin), `informe.py` (technical report) |
| `firecal/i18n.py` | English and Spanish texts (`?lang=en|es`) |
| `firecal/nrt.py` | Near-real-time FIRMS layer (not harmonized) |
| `api/routers/` | `GET /api/...` routes |
| `api/limits.py` | Request protocol (429/503, locks) |
| `tests/` | Reference cases, analytics, languages and limits |

The CLI keeps the project's former name, `firecal`.

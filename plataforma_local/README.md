# Nikal platform guide

Web platform of Nikal (NASA Space Apps Challenge 2026): a FastAPI + DuckDB API and a React + Vite + MapLibre
interface over the harmonized MODIS + VIIRS hotspot series for Cusco. The method is described in
[`../METHODOLOGY.md`](../METHODOLOGY.md).

> **Scope: Cusco only.** It is the only region with a validated harmonization. Another region, an area outside
> Cusco or dates outside 2000-11-04 to 2025-12-31 return **"no data"** (never zeros). The series is
> **historical**: it does not include 2026 (only the separate near-real-time layer does).

---

## 1. What it shows

- **Unit: harmonized hotspots.** ~1 km cells with hotspots per day, on a MODIS-equivalent scale. In the API the
  field is **`focos_armonizados`**. It is the sum of `eq_hotspots` (cell-days) or `eq_foco` (individual hotspots):
  rows are never counted and `n_modis + n_viirs` is never summed.
- **No FRP** (not harmonized between sensors), **no burned area** and **no "events"**: the data are hotspots.
- **Interface:** full-screen MapLibre map with Cusco highlighted and a relief basemap.
  - **Welcome screen** and an optional **guided tour**.
  - **Left rail:** three chapters: **Look** (data panel with exact dates, metrics and CSV download),
    **Understand** (plain-language findings and charts) and **Act** (hazard level by province, district or basin,
    with reports).
  - **Right menu:** language EN/ES, map tools (layers, CENEPRED-format hazard layer, area selection), **Compare**
    (two maps side by side) and the month × year **calendar**.
  - **Top:** **Historical series | Live** switch. Live shows only NASA FIRMS near-real-time detections
    (`/api/tiempo-real`, not harmonized) and hides everything historical.
  - **Bottom:** season ribbon (year, month and day; ▶ plays the months) and the basemap and legend.
- **Month × year calendar:** YlOrRd ramp with breaks at the 50/75/90/99th percentiles of months with hotspots; zero
  in grey; "no data" hatched; **extrapolated** months (2000-11 to 2002-06, Terra only) faded and with their
  **margin**; anomaly flagged **"uncertain"** when the margin crosses a category. Anomaly mode:
  `(value − median of the same month) / max(IQR, 1)`.
- **Margin of extrapolated months:** `incertidumbre` = 41 % (≥ 2500 m) or 45 % (< 2500 m) of the extrapolated
  harmonized hotspots (monthly error of `kT`). `rango` and `anomalia_rango` derive from it.
- **CSV download** with the **18 contract columns**; the on-screen total equals Σ `eq_foco` of the file.

## 2. Languages

- **English by default**; Spanish with the **EN | ES** selector or `?lang=es` in the URL.
- **API:** `?lang=en|es` on every route (default `api.default_lang: en`). Free texts are translated (`detail` of
  errors, `notes`, `unidad`, `titulo`, `en_simple`, `como_leerlo` and the texts of `/api/metadatos`). Field names
  and codes (`categoria`, `calidad`, `veredicto`, `fuente_serie`) are **not** translated: they are the contract
  with the interface.
- **Code:** `backend/firecal/i18n.py` (`t(es=..., en=...)`, language per request) and `frontend/src/i18n.js`
  (`en`/`es` dictionaries, `tr` function). Missing strings fall back to English.

## 3. Structure

```
plataforma_local/
├── backend/                  API (Python 3.12, FastAPI, DuckDB)
│   ├── firecal/plan/         sources.py (contract), events.py (CSV -> Parquet + checks), query.py (queries),
│   │                         analitica.py, ambitos.py (hazard levels), informe.py (technical report)
│   ├── api/routers/          GET /api/...
│   ├── api/limits.py         request protocol (429/503, locks)
│   └── tests/
├── frontend/                 React + Vite + MapLibre interface
│   ├── src/FireMapApp.jsx    map, panels, calendar
│   ├── src/services/api.js   /api/* client
│   └── dist/                 build output (not committed; created by `npm run build`)
└── Dockerfile (+ Dockerfile.dockerignore), docker-compose.yml, cloudbuild.yaml   context = repository root
```

---

## 4. Running it

### Option A: Docker (recommended)

With Docker running, from `plataforma_local/`:
```bash
docker compose up --build          # ~2 min the first time; then open http://localhost:8000
```
Without compose, from the repository **root**:
`docker build -f plataforma_local/Dockerfile -t nikal .` and `docker run --rm -p 8000:8000 nikal`.

The image builds the interface (Node), installs the API and **checks the CSVs against the published checksums**
([`METHODOLOGY.md` §14](../METHODOLOGY.md#14-reproducibility)): if the data changed, the build fails.

### Option B: development (Python + Node)

1. **API** (PowerShell, from `plataforma_local/backend`):
   ```powershell
   py -3.12 -m venv .venv
   .\.venv\Scripts\python -m pip install -r requirements-lock.txt
   .\.venv\Scripts\python -m pip install -e . --no-deps
   $env:PYTHONUTF8 = "1"
   .\.venv\Scripts\firecal plan-events     # ~2 s: checks the CSVs and builds the Parquet
   .\.venv\Scripts\firecal serve           # API at http://localhost:8000 (docs at /docs)
   ```
2. **Interface** (another terminal, from `plataforma_local/frontend`; Node 20 or later):
   ```bash
   npm install
   npm run build          # builds dist/; the API serves it at http://localhost:8000
   npm run dev            # alternative: dev server with hot reload at http://localhost:5173 (proxies /api to 8000)
   ```
3. **Checks:** `ruff check .` and `pytest -q` in `backend/`; `npx eslint .` in `frontend/`.

Page options: `?lang=es` (Spanish), `?intro=0` (skip the brand animation), `?welcome=0` (skip the welcome screen),
`?tutorial=1` (start the guided tour).
Interface hosted on another domain (e.g. Vercel): build with `VITE_API_BASE_URL=https://<api>` and set
`FIRECAL_CORS_ORIGINS=https://<interface-domain>` on the API.

Data check, from the repository root:
```bash
python -I harmonizacion/verificar_datos.py data/harmonized/harmonizado_cusco_celda_dia.csv data/harmonized/focos_cusco_individuales.csv
```

### Deployment

The public demo runs on Google Cloud Run from the same Dockerfile (`cloudbuild.yaml`). The near-real-time layer
needs `FIRMS_MAP_KEY`, read from Secret Manager on the server and never sent to the browser.

---

## 5. Endpoints

Area of interest (AOI): `departamento=PE-CUS` **or** `bbox=west,south,east,north` **or** `lat=..&lon=..&radio_km=..`
(inside Cusco).

| Route | Parameters | Returns |
| --- | --- | --- |
| `GET /api/departamentos` | — | Cusco (the only region with data) and its boundary |
| `GET /api/departamentos.geojson` | — | Cusco outline only (FeatureCollection) |
| `GET /api/calendario` | AOI, `fecha_inicio`, `fecha_fin` (YYYY-MM, optional) | `matriz_focos_armonizados`, `matriz_anomalia`, `total_focos_armonizados`, `cortes_color`, `unidad`, `celdas[]` |
| `GET /api/anomalias` | AOI, `mes` | the month with its margin, median and IQR, anomaly, `historial[]` and `dias[]` |
| `GET /api/focos.geojson` | AOI, `fecha_inicio`, `fecha_fin` | hotspots as map points (`eq_foco`, sensor, date, quality; no FRP); max. 50,000 |
| `GET /api/hotspots.csv` | AOI, `fecha_inicio`, `fecha_fin` | hotspot CSV (18 contract columns); headers `X-Row-Count` and `X-Total-Eq-Foco` |
| `GET /api/analitica` | AOI, period | plain-language analytics: seasonality, ranking, cumulative curve, altitude, recurrence |
| `GET /api/ambitos/...` | see §6 | hazard level by province, district or Pfafstetter basin, GeoJSON, CSV, reports and day-of-year distribution |
| `GET /api/informe` | AOI or `ambito=level:code`, `fecha_inicio`, `fecha_fin`, `mes` | printable technical report (HTML) |
| `GET /api/metadatos` | — | unit, method (k, kT, margin), coverage, checksums and credits |
| `GET /api/tiempo-real` | `horas` = 24, 48 or 120 | **Separate, non-harmonized layer:** NASA FIRMS near-real-time detections over Cusco (VIIRS S-NPP, NOAA-20, NOAA-21 and MODIS) as GeoJSON, refreshed every 15 min. Needs `FIRMS_MAP_KEY`; without it, 503. |
| `GET /health`, `GET /health/limits` | — | data and request-protocol status |

Calendar cell:
```json
{"anio": 2001, "mes": 8, "sin_dato": false, "focos_armonizados": 176.02, "celdas_dia": 34,
 "focos_modis": 34, "focos_viirs": 0, "mediana_hist": 151.5, "anomalia": 0.21, "categoria": "incierta",
 "calidad": "extrapolado", "fraccion_extrapolada": 1.0, "incertidumbre": 77.4, "rango": [98.6, 253.4],
 "anomalia_rango": [-0.45, 0.87], "fuente_serie": "Terra*kT", "parcial": false}
```

Errors: **404 "no data"**; **422** with the reason (empty AOI, inverted range, malformed date, area too large,
too many hotspots for the map, unknown parameter); **429/503** from the request protocol, with `Retry-After`.

## 6. Hazard level by unit (CENEPRED format) and automatic reports

For decision-makers by jurisdiction (province, district) or for technical use by basin (Pfafstetter, levels 1 to
12 within Cusco).

- **In the app:** **Act** chapter and the CENEPRED hazard layer in the map tools: map coloured by hazard level,
  day-of-year distribution of hotspots by level, report per unit (view or PDF) and CSV table of the level.
- **API:** `GET /api/ambitos`, `/api/ambitos/{level}`, `/api/ambitos/{level}.geojson`, `/api/ambitos/{level}.csv`,
  `/api/ambitos/{level}/dias`, `/api/ambitos/{level}/dias/{day}`, `/api/ambitos/{level}/{code}` and
  `/api/ambitos/{level}/{code}/informe`. `level` = `provincia`, `distrito` or `pfaf_01` … `pfaf_12`; `code` =
  ubigeo or Pfafstetter code.
- **Batch reports:** `firecal informes --nivel distrito --salida informes` writes one HTML per unit, an
  `index.html` and the CSV table.

**Method** (`backend/firecal/plan/ambitos.py`): three parameters per unit, per 100 km² within Cusco, over the
complete years 2003–2025: mean density of harmonized hotspots, recurrent ~1 km places (4 or more of the 13 VIIRS
years) and most active year. Weights from Saaty pairwise comparison (the analytic hierarchy process of the CENEPRED
manual): 0.54 / 0.297 / 0.163, consistency ratio 0.008. Each parameter becomes its percentile within the level and
the index is classified as very high (≥ 0.75), high (≥ 0.50), medium (≥ 0.25) and low. A unit without hotspots is
"low"; units under 10 km² within Cusco and levels with fewer than 4 units are not classified.

**Limits:** it is a **relative hazard** within Cusco; it does not include vulnerability (population, housing, land
cover, services), so it is an input to a CENEPRED assessment and does not replace it. The weights are an initial
proposal to be validated by specialists. It describes what was observed; it is not a forecast.

**Unit data** (`backend/config/ambitos/`, built with `backend/scripts/build_ambitos.py`, which needs
`pip install pyshp`):
- Provinces and districts: INEI boundaries via https://github.com/juaneladio/peru-geojson (108 districts of Cusco;
  a recently created district may be missing). Not official boundaries for legal purposes.
- Basins: HydroBASINS v1c (HydroSHEDS; Lehner and Grill, 2013), Pfafstetter code `PFAF_ID`, clipped to the
  series' Cusco boundary (FAO GAUL). Not the official ANA hydrographic units.
- Coverage: districts hold 98.4 % of the harmonized hotspots of Cusco 2003–2025 (the INEI and FAO GAUL boundaries
  differ at the edge); basins, 99.3 %.

## 7. Reference cases (all pass in `backend/tests/`)

| Query | Expected |
| --- | --- |
| Whole period (data v1.3) | 15,818.39 harmonized hotspots · 36,568 cell-days · 59,211 hotspots in the download |
| 2005 / 2012 / 2013 / 2020 / 2022 / 2024 / 2025 | 1355 / 678 / 424 / 1206 / 850 / 640 / 387 (±1) |
| Before 2000-11-04, or outside Cusco | 404 "no data" (not zero) |
| Σ `eq_foco` of the download | = on-screen total, for department, rectangle and point |
| Margin of August 2001 | 176.02 · range 98.6–253.4 · "uncertain" |

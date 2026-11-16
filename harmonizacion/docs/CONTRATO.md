# Data contract: harmonized MODIS + VIIRS FIRMS hotspots (Cusco, 2000-2025)

File: `harmonizado_cusco_celda_dia.csv` (36,568 rows in v1.3, one per 0.01° cell and local day with at least one hotspot).

## Columns
| Column | Meaning |
|---|---|
| `fecha_local` | Date in Peru time (UTC−5), `YYYY-MM-DD`. Converted from `acq_date`+`acq_time` (UTC); a hotspot at 02:00 UTC falls on the previous day. |
| `cell_lat`, `cell_lon` | Centre of the 0.01° cell (~1.1 km), 3 decimals. |
| `alt_m` | Mean SRTM altitude of the cell (m). |
| `n_modis` | MODIS (Terra+Aqua) detections in that cell-day. 0 if none. |
| `n_viirs` | VIIRS S-NPP detections in that cell-day. 0 if none. |
| `frp_modis`, `frp_viirs` | Total FRP (MW) of each sensor in the cell-day. **Not comparable with each other** (VIIRS/MODIS ≈ ×1.2–2.0 depending on the environment). |
| `eq_hotspots` | Contribution of the cell-day to the harmonized series, in **MODIS-equivalent (Terra+Aqua) cell-days**. |
| `fuente_serie` | `MODIS`, `Terra*kT`, `VIIRS*k`, `VIIRS-N20*k` or `MODIS-hueco`: which sensor `eq_hotspots` comes from. In `VIIRS-N20*k` rows, `n_viirs` and `frp_viirs` are from NOAA-20. |
| `calidad` | `referencia` (reference), `calibrado` (calibrated) or `extrapolado` (extrapolated); see below. |

## How `eq_hotspots` is built (the source sensor no longer matters)
| Period | Rule | `fuente_serie` | `calidad` |
|---|---|---|---|
| 2000-11 to 2002-07-03 (Terra only) | 1 cell-day with Terra → `kT` | `Terra*kT` | `extrapolado` |
| 2002-07-04 to 2012-12-31 | 1 cell-day with MODIS → 1.0 | `MODIS` | `referencia` |
| 2013-01-01 onwards | 1 cell-day with VIIRS S-NPP → `k` | `VIIRS*k` | `calibrado` |
| Days without S-NPP over all of Peru (v1.3) | 1 cell-day with VIIRS NOAA-20 → `k20` (0.324 / 0.235) | `VIIRS-N20*k` | `calibrado` |
| Days without S-NPP or NOAA-20 (v1.3) | 1 cell-day with MODIS → 1.0 | `MODIS-hueco` | `referencia` |

From 2013 the series relies on VIIRS (continuity and finer detail) and is expressed on the MODIS scale.
Factors by altitude stratum (high ≥ 2500 m, low < 2500 m):
- `k` (VIIRS→MODIS), calibrated on 2013-2019 as MODIS cell-days / VIIRS cell-days: **high 0.330, low 0.247**.
- `kT` (Terra→Terra+Aqua), calibrated on 2003-2012: **high 2.62, low 7.74**.

**To aggregate:** sum `eq_hotspots` (by day, month or region). Do not sum `n_modis + n_viirs`: they are different sensors with a ~×4 difference.

## Validation (held-out window)
- The VIIRS/MODIS ratio goes from ×4.8 (detections) to ×3.9 per cell-day (Peru) and ×3.0 (Cusco ≥2500 m); it never reaches ×1. The bias is sensitivity, not only resolution, which is why it is calibrated.
- Calibrated on 2013-19, VIIRS×k reproduces the actual MODIS cell-days of 2020-24 with an annual ratio of 0.90-1.09. In 2013-19 the annual error reaches ±20 % (the method's precision floor).
- **2025:** VIIRS×k / MODIS = 1.50. MODIS drops more than VIIRS (consistent with Terra/Aqua orbital drift, not verified). The harmonized series is not affected because it uses VIIRS since 2013.
- `kT` is much less precise: median monthly error 41-45 %, annual −32 % to +45 % in the low stratum. That is why 2000-2002 is `extrapolado` and should be drawn faded.

## Filters applied to the raw hotspots
Source: FIRMS yearly per-country archives (`firms.modaps.eosdis.nasa.gov/data/country/{modis|viirs-snpp}/{year}/…_Peru.csv`), 2000-2025.
- Only `type == 0` (vegetation fire).
- MODIS: `confidence >= 30`. VIIRS: `confidence` in {`n`, `h`}.
- S-NPP only (NOAA-20 is used only for the v1.3 gap fill).
- Region: Cusco polygon (FAO GAUL 2015 level 1) and SRTM altitude at 0.01°.

## Limits to state in the app
- Scope: Cusco only. Another region requires recomputing `k` and `kT` with its own strata.
- "Cell-days" count presence of fire within 1 km, not burned area or intensity.
- FRP is not harmonized.

## Reproduce
1. `cusco_referencia.py` (needs Earth Engine) builds `cusco_ref/` (boundary and altitude).
2. Download the FIRMS CSVs into a `firms_raw/` folder, with FIRMS names (`modis_YYYY_Peru.csv`, `viirs-snpp_YYYY_Peru.csv`) or renamed (`modis_YYYY.csv`, `snpp_YYYY.csv`). One file per sensor and year; if there are two for the same year the scripts abort.
3. `python -I firms_csv.py firms_raw cusco_ref output` builds the CSV and the `kT` and continuity checks.
4. `firms_armoniza.py` (same arguments) **only prints** diagnostics (ratio, Terra/Aqua drift, calibration error). It writes no CSV.
5. `python -I focos_individuales.py firms_raw cusco_ref harmonizado_cusco_celda_dia.csv output` builds `focos_cusco_individuales.csv`.
6. **v1.3:** `python -I relleno_n20.py firms_raw cusco_ref <v1.2_folder> output` fills the days without S-NPP with NOAA-20. It also needs the `viirs-jpss1_YYYY_Peru.csv` (NOAA-20) files from 2018 on, and takes as input the two CSVs from steps 3 and 5. It prints the calibration and validation of `k20`. It aborts if the input is already filled.
7. `python -I verificar_datos.py harmonizado_cusco_celda_dia.csv focos_cusco_individuales.csv` validates both CSVs (exit code 1 if anything fails).

Environment variable `EE_PROJECT`: Earth Engine project for the scripts that use it.

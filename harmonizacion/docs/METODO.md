# MODIS + VIIRS harmonization method: Cusco (v1.3)

One-page summary of the method. The full methodology is in [`METHODOLOGY.md`](../../METHODOLOGY.md); the figures can be checked with `harmonizacion/verificar_datos.py` (`TODO OK` on both CSVs: 36,568 cell-days, sum 15,818.39; 59,211 hotspots, sum 15,818.36).

**What it is.** A daily series of Cusco hotspots (2000-11-04 to 2025-12-31) on a single scale, MODIS Terra+Aqua, even though from 2013 it comes from VIIRS. A hotspot is a pixel with a thermal anomaly detected by the satellite: it is not a fire or a burned area.

**Unit.** A 0.01° cell (~1.1 km) × local day (UTC−5) with at least one hotspot. Presence per cell-day is counted, not detections, because detections depend on pixel size (VIIRS 375 m, MODIS 1 km). Filters: `type = 0`; MODIS `confidence ≥ 30`; VIIRS `n` or `h`. Source: NASA FIRMS annual files; region: FAO GAUL level 1.

**Why calibration is needed.** Even per cell-day, VIIRS sees ×3.0 (≥ 2,500 m) to ×4.1 (< 1,500 m) more cells than MODIS. This is a sensitivity difference, not just resolution. Counts are therefore not mixed: each sensor is converted to the MODIS scale.

**Computation.** Each cell-day contributes a weight `eq_hotspots`; the series is the sum of weights. Factors are cell-day ratios by altitude stratum (high ≥ 2,500 m; low < 2,500 m):

| Period | Weight | Factor (high / low) | Calibration |
|---|---|---|---|
| 2000-11 to 2002-07-03 (Terra only) | `kT` | 2.62 / 7.74 | 2003–2012, Terra → Terra+Aqua |
| 2002-07-04 to 2012 | 1.0 (MODIS) | — | reference |
| 2013 onwards (VIIRS S-NPP) | `k` | 0.330 / 0.247 | 2013–2019, MODIS / VIIRS |
| Days without S-NPP over Peru (45 since 2013) | `k20` (NOAA-20) | 0.324 / 0.235 | 2018–2021, `k20 = k · S-NPP / NOAA-20` |

**Validation on held-out years** (not used for calibration):
- VIIRS×k against actual MODIS cell-days, 2020–2024: annual ratio 0.90–1.09.
- NOAA-20×k20 against S-NPP×k, 2022–2025: annual ratio 0.98–1.05; median monthly error 7 %.
- `kT` (Terra): median monthly error 41–45 %; annual −32 % to +45 % in the low stratum. Hence 2000–2002 is flagged "extrapolated" and shown with its margin.

**Uncertainty and stability of `k`** (`harmonizacion/validacion_k.py`, 5,000 bootstrap resamples by month or week blocks, fixed seed; results in `harmonizacion/validacion/`):
- 95 % confidence interval of `k` (2013–2019): high 0.330 (0.299–0.358); low 0.247 (0.224–0.269), i.e. ±9 % in both. It is a systematic error common to the whole series from 2013.
- Trend of `k` with year (2013–2024): slope +0.0013 per year in the high stratum (95 % CI −0.0055 to +0.0072) and +0.0006 in the low (−0.0044 to +0.0051). Neither is distinguishable from zero: no evidence of `k` drift over that period.
- Leave-one-year-out calibration (2013–2024): predicted / actual MODIS ratio has median 1.02 and range 0.81–1.20; median annual error 6.4 %. The most deviating years are 2019 (0.81) and 2018 (1.20).
- 2025 is left out of the calibration: the ratio is 1.51 (high 1.26; low 1.81) and low-stratum `k` falls to 0.134 because MODIS loses cell-days.
- By season, high-stratum `k` is stable (dry 0.331; wet 0.317). In the low stratum it differs (dry 0.251; wet 0.198): the single factor somewhat overestimates the wet season, which has few hotspots.

**Limits.**
- Inside the calibration window (2013–2019) the annual error reaches ±20 %: this is the method's precision floor. The resampling confirms it: yearly `k` ranges 0.25–0.39 in the high stratum, with overlapping intervals.
- Factors are constant per stratum: they do not model sensitivity changes across years (no detectable trend up to 2024) or across seasons (the low stratum differs between dry and wet season). In 2025 VIIRS×k / MODIS = 1.50 (MODIS drops more; consistent with orbital drift, not verified). The harmonized series is not affected because it uses VIIRS from 2013.
- There is no independent ground truth (e.g. measured burned areas) against which it was checked: validation is cross-sensor consistency, not accuracy against the ground.
- 2000–2002 is extrapolation with high error. A "day without S-NPP" means no S-NPP rows anywhere in Peru: a partial gap over Cusco is not detected. 4 days before NOAA-20 have no replacement data and are 0.
- The Cusco boundary is simplified to ~500 m: hotspots near the edge may be assigned wrongly.

**What it does not do.** It does not estimate burned area, intensity (harmonized FRP) or cause. It is not a forecast or a risk assessment; the hazard level by jurisdiction is relative within Cusco and excludes vulnerability. Valid for Cusco only: another region requires recomputing `k` and `kT`.

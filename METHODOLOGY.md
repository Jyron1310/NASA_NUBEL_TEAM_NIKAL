# Technical methodology: harmonized MODIS + VIIRS hotspot series (Cusco, Peru)

> Data version **v1.3** · Coverage **2000-11-04 to 2025-12-31** · Validated region: **department of Cusco** · NASA Space Apps Challenge 2026

**Abstract.** We build a 25-year daily series of satellite hotspots for Cusco (Peru) on a single, MODIS-equivalent scale, although the source sensor changes from MODIS (1 km) to VIIRS (375 m) in 2013. The counting unit is the presence of at least one hotspot in a 0.01° cell per local day. VIIRS is converted to the MODIS scale with ratio factors calibrated by altitude stratum (k = 0.330 above 2,500 m; 0.247 below; 95 % CI ±9 %), validated on held-out years (annual ratio 0.90–1.09 in 2020–2024; leave-one-year-out 0.81–1.20, median annual error 6.4 %), with no detectable drift of k in 2013–2024. Days without VIIRS S-NPP are filled with NOAA-20 (k20 = 0.324 / 0.235) and the Terra-only period (2000–2002) is extrapolated with a wide, explicit error margin. The series supports monthly anomalies, year rankings and a relative hotspot hazard level by province, district and Pfafstetter basin in the CENEPRED 4-level format. It does not estimate burned area, fire intensity or cause.

---

## Contents
1. [Objective and scope](#1-objective-and-scope)
2. [Input data](#2-input-data)
3. [Preprocessing](#3-preprocessing)
4. [Counting unit: cell-day](#4-counting-unit-cell-day)
5. [Why calibration is needed](#5-why-calibration-is-needed)
6. [Harmonization model](#6-harmonization-model)
7. [Validation](#7-validation)
8. [Uncertainty and stability of the k factor](#8-uncertainty-and-stability-of-the-k-factor)
9. [Derived products](#9-derived-products)
10. [Spatial resolution: what a point represents](#10-spatial-resolution-what-a-point-represents)
11. [Near-real-time layer (not harmonized)](#11-near-real-time-layer-not-harmonized)
12. [Limitations](#12-limitations)
13. [What it does not do](#13-what-it-does-not-do)
14. [Reproducibility](#14-reproducibility)
15. [Glossary](#15-glossary)
16. [References and credits](#16-references-and-credits)

---

## 1. Objective and scope

Build a **comparable 2000–2025** time series of satellite-detected hotspots in Cusco, to answer questions such as: *was this month or year above typical?*, *which years had the most hotspots?*, *which provinces, districts or basins concentrate the most hotspots per unit area?*

**Scope:** Cusco only. The factors were calibrated with Cusco data and must not be applied to other regions without recalibration (§12).

**Definition.** A **hotspot** (active thermal anomaly) is a pixel in which the sensor's detection algorithm finds, at overpass time, a mid-infrared (~4 µm) emission clearly higher than that of its surroundings. **It is not a confirmed fire nor a burned area**; it may be a vegetation fire, an agricultural or pasture burn, or another hot source.

## 2. Input data

| Source | Product | Pixel (nadir) | Period used | Role |
|---|---|---|---|---|
| NASA FIRMS | MODIS Collection 6.1 (MOD14/MYD14, Terra and Aqua) | 1 km | 2000-11 to 2025 | Reference scale (2002-07 to 2012) |
| NASA FIRMS | VIIRS 375 m S-NPP (VNP14IMG) | 375 m | 2012 to 2025 | Series source from 2013 |
| NASA FIRMS | VIIRS 375 m NOAA-20 (VJ114IMG) | 375 m | 2018 to 2025 | Fill for days without S-NPP (v1.3) |
| FAO GAUL 2015, level 1 | Boundary of the department of Cusco | — | — | Spatial clip (simplified to ~500 m) |
| SRTM | Digital elevation model, resampled to 0.01° | ~1 km | — | Altitude strata |
| INEI (via peru-geojson) | Provinces (13) and districts (108) | — | — | Administrative units |
| HydroBASINS v1c | Pfafstetter basins, levels 1 to 12 | — | — | Hydrographic units |

The FIRMS files are the yearly per-country archives (`…/data/country/{modis|viirs-snpp|viirs-jpss1}/{year}/…_Peru.csv`), downloaded up to 2025-12-31.

## 3. Preprocessing

1. **Quality filters**
   - `type = 0` (presumed vegetation fire; volcanoes, static sources and offshore detections are excluded).
   - MODIS: `confidence ≥ 30`.
   - VIIRS: `confidence ∈ {nominal, high}` (*low* is excluded).
2. **Spatial clip:** point (pixel centre) inside the Cusco polygon.
3. **Local date:** `local_date = date(acq_date + acq_time − 5 h)` (Peru time, UTC−5). A hotspot at 02:00 UTC falls on the previous day.
4. **Cell:** 0.01° grid. The cell centre is `c = ⌊x / 0.01⌋ · 0.01 + 0.005` for latitude and longitude.
5. **Altitude:** SRTM altitude of the cell. Stratum **high** if ≥ 2,500 m, **low** if < 2,500 m. Cells without altitude are assigned to *low*.
6. **FRP:** kept as a record but **not used** in the series; it is not comparable between sensors.

## 4. Counting unit: cell-day

The series **does not count detections**: it counts **cell-days with at least one hotspot**.

$$I_s(c,d) = \begin{cases} 1 & \text{if sensor } s \text{ has at least one hotspot in cell } c \text{ on local day } d \\ 0 & \text{otherwise} \end{cases}$$

**Rationale.** The number of detections depends on pixel size: the same hotspot may produce several 375 m VIIRS detections where MODIS produces one 1 km detection. Switching to presence per cell-day reduces this resolution effect. A 0.01° cell measures ~1.11 km × 1.08 km ≈ **1.2 km²** at the latitude of Cusco.

## 5. Why calibration is needed

Even at cell-day level, VIIRS records more cells than MODIS over the same place and period:

| Aggregation level | VIIRS / MODIS ratio |
|---|---|
| Detections (Peru) | ×4.8 |
| Cell-days (Peru) | ×3.9 |
| Cell-days (Cusco, ≥ 2,500 m) | ×3.0 |
| Cell-days (Cusco, < 1,500 m) | ×4.1 |

The ratio never reaches ×1: the difference is not only resolution but **sensitivity** (VIIRS detects smaller or cooler fires). If both series were joined without adjustment, 2013 would show a 3- to 4-fold "increase" that never happened. The ratio also depends on altitude, which is why calibration is done by stratum.

## 6. Harmonization model

### 6.1 Factors

Each factor is a **ratio of cell-days** summed over a calibration window and an altitude stratum $e$:

$$k_e = \frac{\sum_{d \in W} \sum_{c \in e} I_{\text{MODIS}}(c,d)}{\sum_{d \in W} \sum_{c \in e} I_{\text{VIIRS S-NPP}}(c,d)}, \qquad W = 2013\text{–}2019$$

$$kT_e = \frac{\sum_{d \in W_T} \sum_{c \in e} I_{\text{Terra+Aqua}}(c,d)}{\sum_{d \in W_T} \sum_{c \in e} I_{\text{Terra}}(c,d)}, \qquad W_T = 2003\text{–}2012$$

$$k20_e = k_e \cdot \frac{\sum I_{\text{S-NPP}}}{\sum I_{\text{NOAA-20}}}, \qquad \text{days with both satellites, } 2018\text{–}2021$$

| Factor | High (≥ 2,500 m) | Low (< 2,500 m) | Calibration window |
|---|---|---|---|
| `k` (VIIRS S-NPP → MODIS) | **0.330** | **0.247** | 2013–2019 |
| `kT` (Terra → Terra+Aqua) | **2.62** | **7.74** | 2003–2012 |
| `k20` (NOAA-20 → MODIS, via S-NPP) | **0.324** | **0.235** | 2018–2021 |

`kT` exists because before 2002-07-04 there is only Terra (10:30 overpass), which sees about 5 times less than Terra+Aqua (Aqua passes at 13:30, the hour of highest activity).

### 6.2 Weight of each cell-day

Each cell-day receives a weight `eq_hotspots` in **MODIS-equivalent (Terra+Aqua) cell-days**:

| Period | Source sensor | Weight | `fuente_serie` | `calidad` |
|---|---|---|---|---|
| 2000-11-04 to 2002-07-03 | Terra | $kT_e$ | `Terra*kT` | extrapolated |
| 2002-07-04 to 2012-12-31 | MODIS (Terra+Aqua) | 1.0 | `MODIS` | reference |
| 2013-01-01 to 2025-12-31 | VIIRS S-NPP | $k_e$ | `VIIRS*k` | calibrated |
| Days without S-NPP over all of Peru (45 since 2013) | VIIRS NOAA-20 | $k20_e$ | `VIIRS-N20*k` | calibrated |
| Days without S-NPP or NOAA-20 | MODIS | 1.0 | `MODIS-hueco` | reference |

From 2013 the series relies on VIIRS (continuity and finer detail), expressed on the MODIS scale. A "day without S-NPP" is a day with no S-NPP row anywhere in Peru.

### 6.3 Aggregation

$$F(R, T) = \sum_{c \in R} \sum_{d \in T} \text{eq\_hotspots}(c, d)$$

This is the value the platform calls **harmonized hotspots** (`focos_armonizados`). `n_modis + n_viirs` is never summed, because the sensors have different scales.

### 6.4 Allocation to individual hotspots

For the map and per-point downloads, the weight of each cell-day is split equally among the $n$ hotspots of the source sensor in that cell-day:

$$\text{eq\_foco} = \frac{\text{eq\_hotspots}(c,d)}{n}$$

Summing `eq_foco` over any region and period therefore reproduces `eq_hotspots`, with a maximum difference of 0.0006 per cell-day due to rounding. Example: 3 VIIRS detections in a high cell are worth 0.330 / 3 = 0.110 each. **The `eq_foco` of an isolated point is not interpretable on its own**: it is an accounting weight, not a size. Hotspots from sensors that are not the source for their period are kept with `en_serie = 0` and `eq_foco = 0`.

## 7. Validation

Validation uses **held-out years**, not used for calibration, and compares against the actual MODIS count.

| Test | Period | Result |
|---|---|---|
| VIIRS×k vs. actual MODIS cell-days | 2020–2024 | annual ratio **0.90–1.09** |
| VIIRS×k within the calibration window | 2013–2019 | annual error up to **±20 %** (precision floor) |
| NOAA-20×k20 vs. S-NPP×k | 2022–2025 | annual ratio **0.98–1.05**; median monthly error **7 %** |
| Terra×kT vs. Terra+Aqua | 2008–2012 (with kT from 2003–2007) | median monthly error **41–45 %**; annual −32 % to +45 % in the low stratum |
| VIIRS×k vs. MODIS | 2025 | ratio **1.50**: MODIS drops more than VIIRS (§12) |

Because of the `kT` error, the 2000–2002 segment is flagged as **extrapolated** and shown with a ±41 % (high stratum) or ±45 % (low stratum) margin.

## 8. Uncertainty and stability of the k factor

Script: `harmonizacion/validacion_k.py`. Results: `harmonizacion/validacion/validacion_k.{md,csv}`. A **block bootstrap** is used (5,000 resamples, fixed seed `20261115`). **Whole months or weeks** are resampled, not single days, because hotspots from the same episode repeat on neighbouring days and are not independent. The 45 days without S-NPP are excluded. The script reproduces `k` = 0.330 / 0.247 exactly.

### 8.1 Confidence interval of k (2013–2019)

| Stratum | k | 95 % CI (month blocks) | 95 % CI (week blocks) | MODIS / VIIRS cell-days |
|---|---|---|---|---|
| High | 0.330 | 0.299 – 0.358 | 0.299 – 0.359 | 1,605 / 4,867 |
| Low | 0.247 | 0.224 – 0.269 | 0.228 – 0.265 | 2,489 / 10,082 |

The uncertainty is **±9 %** in both strata. It is a **systematic** error: it shifts the whole series since 2013 in the same direction, so it does not affect comparisons between years after 2013, but it does affect comparisons between years before and after 2013.

### 8.2 Stability over time

- **Trend of k (2013–2024).** The slope is +0.0013 per year in the high stratum (95 % CI −0.0055 to +0.0072) and +0.0006 per year in the low stratum (−0.0044 to +0.0051). **Neither is distinguishable from zero**: there is no evidence of drift in relative sensitivity over that period.
- **Leave-one-year-out calibration (2013–2024).** `k` is computed with the other years and used to predict the MODIS total of the omitted year. The predicted / actual ratio has median **1.02** and range **0.81–1.20**; the median annual error is **6.4 %**. The most deviating years are 2019 (0.81) and 2018 (1.20).
- **k by year.** It ranges from 0.25 to 0.39 in the high stratum and from 0.21 to 0.30 in the low stratum, with overlapping intervals.
- **2025.** Out of range: the ratio is 1.51 and the low-stratum `k` drops to 0.134, due to the loss of MODIS detections (§12).

### 8.3 Seasonality

| Season (2013–2019) | k high | k low |
|---|---|---|
| Dry (Jun–Oct) | 0.331 | 0.251 |
| Wet (Nov–May) | 0.317 | 0.198 |

In the high stratum `k` is stable across seasons. In the low stratum the single factor **somewhat overestimates the wet season**, which has few hotspots; the effect on annual totals is small.

## 9. Derived products

### 9.1 Month × year calendar
Sum of `eq_hotspots` per month. Colours use breaks at the 50th, 75th, 90th and 99th percentiles of months with hotspots. A month outside the coverage returns **"no data"**, never 0.

### 9.2 Monthly anomaly

$$A_{y,m} = \frac{V_{y,m} - \operatorname{median}_m}{\max(Q75_m - Q25_m,\ 1)}$$

- The history of each month uses only complete months of *reference* or *calibrated* quality, with at least **5 years**.
- Categories: well below (< −1), below (−1 to −0.5), normal (−0.5 to 0.5), above (0.5 to 1) and well above (> 1).
- If the margin of an extrapolated month crosses a category boundary, the anomaly is flagged as **"uncertain"**.

### 9.3 Analytics
Seasonality (median, P25 and P75 per month), year ranking, cumulative curve, distribution by altitude and recurrence. Recurrence counts cells with hotspots in at least 4 of the 13 years since 2013 and uses VIIRS only. The **typical year** is the median of complete, non-extrapolated years (2003–2025).

### 9.4 Hotspot hazard level (CENEPRED format)
Computed by province, district and Pfafstetter basin (levels 1 to 12). Each 0.01° cell is assigned to a unit by point-in-polygon.

- **Parameters**, per 100 km² of the unit, over 2003–2025:
  - **Density**: mean annual harmonized hotspots.
  - **Recurrence**: recurrent places since 2013.
  - **Extreme**: total of the most active year.
- **Weights** by the analytic hierarchy process (Saaty), with matrix `[[1,2,3],[1/2,1,2],[1/3,1/2,1]]`: density **0.540**, recurrence **0.297**, extreme **0.163**. The consistency ratio is **0.008** (< 0.10).
- **Index:** weighted sum of the percentiles of each parameter within the level.
- **Classes:** very high ≥ 0.75; high ≥ 0.50; medium ≥ 0.25; low < 0.25.
- **Unclassified:** units smaller than 10 km² and levels with fewer than 4 units. A unit without hotspots is always "low".
- **It is a relative hazard within Cusco and does not include vulnerability.** It is an input to a CENEPRED risk assessment, not the assessment itself.

### 9.5 Automatic technical report
`GET /api/informe` produces a printable report for any area and period. It uses only the data above and includes method, limitations and traceability: data version, sums and SHA-256, and the API calls that reproduce each figure.

## 10. Spatial resolution: what a point represents

| Element | Size |
|---|---|
| MODIS pixel | ~1 km × 1 km at nadir (≈ 100 ha); up to ~2 × 4.8 km at the swath edge |
| VIIRS I-band pixel | ~375 m × 375 m at nadir (≈ 14 ha); up to ~0.8 × 0.8 km at the edge |
| Series cell | 0.01° ≈ 1.11 × 1.08 km ≈ 1.2 km² (120 ha) |
| Point on the map | Pixel centre; its on-screen size is symbolic |

- **Pixel area is not burned area.** The satellite flags the whole pixel even when the hot surface is much smaller. Under good conditions MODIS detects fires of about 100 m² and VIIRS smaller ones.
- **Location is approximate:** the hotspot lies within about 375 m (VIIRS) or 1 km (MODIS) of the point.
- The processed files do not keep `scan` or `track` (the actual size of each pixel), so the ranges of each sensor are reported instead.

## 11. Near-real-time layer (not harmonized)

`GET /api/tiempo-real?horas=24|48|120` queries the FIRMS *area* API (VIIRS S-NPP, NOAA-20, NOAA-21 and MODIS) for the Cusco bounding box and clips to the polygon. It refreshes every 15 minutes.

**These are raw, non-harmonized detections** and are not added to the historical series. The `FIRMS_MAP_KEY` lives only on the server.

## 12. Limitations

- **Cusco only.** Another region requires recomputing `k`, `kT` and `k20` with its own strata.
- **Constant factors per stratum.** They do not model variation between years (no detectable trend up to 2024) or between seasons (difference in the low stratum, §8.3).
- **Precision floor.** Annual error reaches ±20 % within the calibration window, and the systematic error of `k` is ±9 % (§8.1).
- **2000–2002 is an extrapolation**, with a monthly error of 41 to 45 %.
- **2025.** MODIS loses detections (ratio 1.50), consistent with the orbital drift of Terra and Aqua; not verified. The series is not affected because it uses VIIRS since 2013.
- **No ground truth.** There is no comparison with measured burned areas: validation is consistency between sensors, not accuracy against the ground.
- **S-NPP gaps.** A partial gap (S-NPP data elsewhere in Peru but not over Cusco) is not detected. Four days before NOAA-20 have no replacement and count as 0.
- **Cusco boundary.** The boundary is simplified to ~500 m, and hotspots near the edge may be misassigned.
- **Aqua.** The Aqua cut-off date is 2002-07-04, but its first hotspot in Cusco is on 2002-07-19: about 15 days weigh 1.0 instead of `kT`, a small effect in the low season.
- **Altitude.** Cells without SRTM altitude are treated as the low stratum.
- **End of the series.** It ends on 2025-12-31 UTC: the last local day may be incomplete.

## 13. What it does not do

- It does not estimate **burned area**, **intensity** (there is no harmonized FRP) or the **cause** of a hotspot.
- It is not a **forecast**: it describes what was observed.
- It is not a **risk assessment**: the hazard level does not include vulnerability.
- It is not valid outside **Cusco** without recalibration.
- It does not include **2026** in the historical series (only the near-real-time layer, not harmonized).

## 14. Reproducibility

### 14.1 Files and checksums

| File | Rows | Sum | SHA-256 |
|---|---|---|---|
| `data/harmonized/harmonizado_cusco_celda_dia.csv` | 36,568 | `eq_hotspots` = 15,818.39 | `D686C8FDA6259392730E416E40139B436311042C5081B9273CAC747778E639B1` |
| `data/harmonized/focos_cusco_individuales.csv` | 59,211 | `eq_foco` = 15,818.36 | `934C28D5F5FA8C4EEDD926719292AC08DDAF3BB6A8CFAD824BFFD25F7F334D26` |

The CSVs use CRLF line endings: the SHA-256 changes if they are regenerated with LF. The column contracts are in `harmonizacion/docs/CONTRATO.md` and `harmonizacion/docs/CONTRATO_focos.md`.

### 14.2 Scripts

| Script | What it does |
|---|---|
| `harmonizacion/cusco_referencia.py` | Builds the Cusco boundary and SRTM altitude at 0.01° (`cusco_ref/`, already included). Requires Google Earth Engine (`EE_PROJECT`) |
| `harmonizacion/firms_csv.py` | Filters, cell-days, calibration of `k` and `kT`, and the cell-day CSV |
| `harmonizacion/focos_individuales.py` | Hotspot CSV with `eq_foco` |
| `harmonizacion/relleno_n20.py` | NOAA-20 fill of days without S-NPP (v1.3) |
| `harmonizacion/firms_armoniza.py` | Diagnostics (prints only; writes no data) |
| `harmonizacion/validacion_k.py` | Bootstrap, trend, leave-one-year-out calibration and seasonality of `k` |
| `harmonizacion/verificar_datos.py` | Checks contracts, totals and weight allocation (exits with code 1 on failure) |

### 14.3 Commands

```bash
python -I harmonizacion/verificar_datos.py data/harmonized/harmonizado_cusco_celda_dia.csv data/harmonized/focos_cusco_individuales.csv
```

```bash
python -I harmonizacion/validacion_k.py <firms_raw_folder> harmonizacion/cusco_ref <output>
```

`<firms_raw_folder>` holds the yearly FIRMS per-country CSVs (`modis_YYYY_Peru.csv`, `viirs-snpp_YYYY_Peru.csv`, `viirs-jpss1_YYYY_Peru.csv`). They are not included in the repository because of their size; download them from FIRMS.

## 15. Glossary

| Term | Meaning |
|---|---|
| Hotspot | Pixel with a satellite-detected thermal anomaly. Not a confirmed fire. |
| Cell-day | A 0.01° cell (~1.2 km²) on a local day with at least one hotspot. |
| Harmonized hotspots | Cell-days on the MODIS (Terra+Aqua) scale; the unit of the series. |
| `k`, `kT`, `k20` | Conversion factors to the MODIS scale, by altitude stratum. |
| Quality | *reference* (actual MODIS), *calibrated* (VIIRS×k) or *extrapolated* (Terra×kT). |
| Anomaly | Distance of a month from the median of the same calendar month, in interquartile ranges. |
| Hazard level | Relative class (very high to low) from density, recurrence and extreme; no vulnerability. |

## 16. References and credits

- Giglio, L., Schroeder, W., & Justice, C. O. (2016). The collection 6 MODIS active fire detection algorithm and fire products. *Remote Sensing of Environment*, 178, 31–41.
- Schroeder, W., Oliva, P., Giglio, L., & Csiszar, I. A. (2014). The New VIIRS 375 m active fire detection data product: Algorithm description and initial assessment. *Remote Sensing of Environment*, 143, 85–96.
- Saaty, T. L. (1980). *The Analytic Hierarchy Process*. McGraw-Hill.
- Lehner, B., & Grill, G. (2013). Global river hydrography and network routing: baseline data and new approaches to study the world's large river systems. *Hydrological Processes*, 27(15), 2171–2186 (HydroBASINS).
- CENEPRED. *Manual para la evaluación de riesgos originados por fenómenos naturales*, 2nd edition. Lima, Peru.

We acknowledge the use of data and/or imagery from NASA's Fire Information for Resource Management System (FIRMS) (https://earthdata.nasa.gov/firms), part of NASA's Earth Science Data and Information System (ESDIS).

**Related documents:** [`harmonizacion/docs/METODO.md`](harmonizacion/docs/METODO.md) (one-page summary), [`harmonizacion/docs/CONTRATO.md`](harmonizacion/docs/CONTRATO.md) and [`CONTRATO_focos.md`](harmonizacion/docs/CONTRATO_focos.md) (data contracts), [`harmonizacion/validacion/validacion_k.md`](harmonizacion/validacion/validacion_k.md) (uncertainty of k).

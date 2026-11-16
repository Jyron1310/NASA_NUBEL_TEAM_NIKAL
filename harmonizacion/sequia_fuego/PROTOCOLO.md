# Drought–fire comparison protocol (Cusco pilot, 2003-2025)

**Status:** everything done in Cusco is **exploratory**. Those data were already examined in dozens of tests, so they cannot confirm anything. This protocol fixes the analysis before running it on new data (other regions or held-out years).

## 1. Question and hypotheses (fixed before looking)
- **Primary (H1, one-sided):** a drier preceding rainy season (lower June SPI-6) is associated with more fire in the following dry season (MODIS-equivalent cell-days in Jul-Oct), at the regional-annual level.
- **Secondary:** (H2) same-month effect (SPI-3/6 and deseasonalized monthly fire, Jul-Oct); (H3) spatial contrast: pixels relatively drier than their region in a given year have more fire; (H4) fuel: higher Mar-Apr NDVI is associated with more fire.
- Drought type: **meteorological** (SPI). No claim is made about agricultural or hydrological drought.

## 2. Data and comparable unit
- **Unit:** 0.05° pixel (~30 km²) × year, because the CHIRPS SPI has that resolution.
- **Fire:** `eq_hotspots` from the harmonized CSV, excluding `calidad = extrapolado` (years 2003-2025). Summed over Jul-Oct.
- **Rainfall:** pentadal CHIRPS summed to monthly. **Quality gate:** break test (Pettitt) and trend test (Mann-Kendall); the SPI is calibrated on a homogeneous period (≥2000). Triangulate with a second source (ERA5-Land or SENAMHI's PISCO).
- **NDVI:** MOD13A3 with `SummaryQA ≤ 1`.
- **Pixel inclusion criterion:** must depend on something unrelated to fire in the analysed period (altitude, land cover). Selecting pixels by their fire frequency in the same period conditions on the outcome.

## 3. How much comparable data there is (measured in Cusco)
| Item | Value |
|---|---|
| 0.05° pixels in Cusco | 2,409 |
| Pixels with fire in ≥8 of 23 years | 540 → 12,420 pixel-years |
| Variance of June SPI-6: common to the year / fixed difference between pixels / within-year contrast | 37 % / 25 % / 39 % |
| Correlation of raw SPI between pixels at 0-30 / 100-200 / 200-400 km | 0.94 / 0.52 / 0.36 |
| Decorrelation scale of the spatial contrast (L) | ≈ 103 km → ~1 independent patch per year |
| Fire variance common to the year (after removing the pixel level) | 7 % |
| **Effective sample** | **≈ 23 years** (between-year contrast); ≈ 25 for the spatial contrast |

The 12 thousand pixel-years are not 12 thousand observations: drought is regional. Many regions help less than it seems: with 6 regions and a correlation of 0.36 between them (an assumption taken from the 200-400 km band, to be verified), the effective sample rises from 23 to ≈ 49.

## 4. A priori power (simulation with real noise, 500 replicates per cell)
Type I error verified: 5-6 % with beta=0.
| beta (fire sd per SPI sd) | implied annual rho | E1 annual | E2 pixel+year fixed effects | E3 pixel fixed effect |
|---|---|---|---|---|
| 0.05 | −0.22 | 18 % | 37 % | 38 % |
| 0.10 | −0.34 | 51 % | 79 % | 80 % |
| 0.20 | −0.58 | 94 % | 100 % | 100 % |

- **Minimum detectable with 80 % power:** E1 ≈ |rho| 0.50; panels ≈ beta 0.10. With 6 regions (effective n ≈ 49) the minimum would drop to |rho| ≈ 0.37.
- **Decision rule:** if the plausible effect (~0.3) is below the minimum detectable, the analysis is declared exploratory and reported as an estimate with an interval, not as a confirmatory test.

## 5. Estimators and tests
- **E1 (primary):** annual regression of the regional mean of log1p(fire) on the mean June SPI-6. n = years. One-sided.
- **E2 / E3:** pixel × year panel with fixed effects (E2: pixel and year; E3: pixel), errors clustered by year (t with G−1 df). One-sided.
- **Monthly (H2):** z(log1p fire) by calendar month ~ standardized SPI; clustering by year; with and without a linear trend (sensitivity).
- **Multiplicity:** one primary test. Secondary family with Holm. Everything else is labelled exploratory.
- **Effect:** always with a confidence interval; null results are reported.

## 6. Rules against forking paths
- Outcome, index, window, lag, direction and inclusion criterion are frozen before running.
- Do not switch estimators after seeing the p-value. In the Cusco pilot the same contrast gave p=0.23-0.29 (ranks and terciles) and p=0.02 (E1, linear regression with pixels chosen by their fire): that difference is exactly the risk this rule tries to prevent.

## 7. Cusco pilot results (exploratory; do not cite as a finding)
- E1 regional annual: beta −0.133, p=0.020 (one-sided).
- E2 spatial contrast: beta +0.081, p=0.977 (opposite sign; no relative local effect).
- E3: beta −0.050, p=0.089.
- Monthly, same month: negative effect that does not survive Holm in the family of 8 tests. With a one-month lag there is no effect.
- The SPI with a 1981-2010 baseline is not calibrated for 2003-2025 (CHIRPS break in 1999-2000: +20 % high-Andean rainfall).

## 8. Reproduce
1. `clima_cusco_ee.py`: downloads CHIRPS and NDVI for Cusco (Earth Engine).
2. `sequia_fuego.py`: exploratory analysis, maps and figure.
3. `pruebas_hipotesis.py`: formal tests and Holm.
4. `n_efectivo_potencia.py`: effective sample and power simulation.
Inputs: `harmonizado_cusco_celda_dia.csv` and `cusco_ref/` from the main data package.

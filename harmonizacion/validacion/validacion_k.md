## 1. Confidence interval of k (calibration 2013-2019, bootstrap with 5000 resamples)

| stratum | k | 95 % CI (month blocks) | 95 % CI (week blocks) | relative width | MODIS / VIIRS cell-days |
|---|---|---|---|---|---|
| high | 0.330 | 0.299 – 0.358 | 0.299 – 0.359 | ±8.9 % | 1605 / 4867 |
| low | 0.247 | 0.224 – 0.269 | 0.228 – 0.265 | ±9.2 % | 2489 / 10082 |

## 2. Stability of k by year (all cell-days of that year)

| year | k high | 95 % CI | k low | 95 % CI |
|---|---|---|---|---|
| 2013 | 0.310 | 0.235 – 0.375 | 0.232 | 0.126 – 0.273 |
| 2014 | 0.247 | 0.154 – 0.299 | 0.233 | 0.210 – 0.267 |
| 2015 | 0.317 | 0.274 – 0.408 | 0.247 | 0.224 – 0.279 |
| 2016 | 0.356 | 0.304 – 0.420 | 0.247 | 0.168 – 0.275 |
| 2017 | 0.386 | 0.275 – 0.473 | 0.241 | 0.192 – 0.267 |
| 2018 | 0.254 | 0.108 – 0.368 | 0.212 | 0.149 – 0.259 |
| 2019 | 0.386 | 0.313 – 0.410 | 0.299 | 0.155 – 0.342 |
| 2020 | 0.310 | 0.258 – 0.378 | 0.229 | 0.198 – 0.259 |
| 2021 | 0.273 | 0.194 – 0.302 | 0.247 | 0.168 – 0.309 |
| 2022 | 0.351 | 0.296 – 0.385 | 0.258 | 0.200 – 0.294 |
| 2023 | 0.294 | 0.194 – 0.369 | 0.254 | 0.201 – 0.281 |
| 2024 | 0.331 | 0.241 – 0.414 | 0.220 | 0.138 – 0.262 |
| 2025 | 0.258 | 0.162 – 0.307 | 0.134 | 0.105 – 0.201 |

### Trend of k with year (2013-2024; 2025 apart because of the MODIS drop)

| stratum | slope (per year) | 95 % CI | includes 0? |
|---|---|---|---|
| high | +0.0013 | -0.0055 – +0.0072 | yes |
| low | +0.0006 | -0.0044 – +0.0051 | yes |

## 3. Leave-one-year-out calibration (2013-2025, 2025 never used for calibration)

k is computed with all the other years of 2013-2024 and used to predict the annual MODIS cell-day total of the omitted year (k × VIIRS). Ratio = predicted / actual MODIS.

| year | ratio high | ratio low | ratio total |
|---|---|---|---|
| 2013 | 1.05 | 1.05 | 1.05 |
| 2014 | 1.33 | 1.05 | 1.14 |
| 2015 | 1.02 | 0.98 | 1.00 |
| 2016 | 0.90 | 0.98 | 0.94 |
| 2017 | 0.83 | 1.01 | 0.95 |
| 2018 | 1.29 | 1.16 | 1.20 |
| 2019 | 0.82 | 0.79 | 0.81 |
| 2020 | 1.05 | 1.07 | 1.07 |
| 2021 | 1.20 | 0.98 | 1.07 |
| 2022 | 0.91 | 0.94 | 0.92 |
| 2023 | 1.11 | 0.95 | 1.00 |
| 2024 | 0.98 | 1.12 | 1.06 |
| 2025 | 1.26 | 1.81 | 1.51 |

2013-2024: median ratio 1.02, minimum 0.81, maximum 1.20; median annual relative error 6.4 %.

## 4. k by season (calibration 2013-2019)

| season | k high | k low |
|---|---|---|
| dry (Jun–Oct) | 0.331 | 0.251 |
| wet (Nov–May) | 0.317 | 0.198 |

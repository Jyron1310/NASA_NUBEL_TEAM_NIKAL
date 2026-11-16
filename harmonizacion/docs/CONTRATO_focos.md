# Individual FIRMS hotspots for Cusco with harmonized weight (2000-2025)

File: `focos_cusco_individuales.csv`. One row per hotspot (MODIS Terra/Aqua and VIIRS S-NPP) that passes the project filters, with the weight it contributes to the harmonized series.
Summing `eq_foco` over any region and dates reproduces `eq_hotspots` from `harmonizado_cusco_celda_dia.csv` (same computation, split among the hotspots of each cell-day).

## Columns
| Column | Meaning |
|---|---|
| `fecha_local`, `fecha_utc`, `hora_utc` | Peru date (UTC−5), and the original UTC date and time of the hotspot (`HHMM`). |
| `latitude`, `longitude` | Original hotspot position (FIRMS). |
| `cell_lat`, `cell_lon` | Centre of the 0.01° cell (~1.1 km) it is assigned to. |
| `alt_m` | SRTM altitude of the cell (m). |
| `sensor` | `MODIS` or `VIIRS`. |
| `satelite` | `Terra`, `Aqua`, `Suomi-NPP` or `NOAA-20` (the latter only on days without S-NPP, v1.3). |
| `frp` | Fire radiative power of the hotspot (MW), not harmonized. Not comparable between sensors (VIIRS/MODIS ≈ ×1.2-2.0). |
| `brillo_k` | Brightness temperature (K): band T21 for MODIS, I4 for VIIRS. |
| `confianza` | Original FIRMS confidence (0-100 for MODIS; `n`/`h` for VIIRS). |
| `diurno_nocturno` | `D` (day) or `N` (night). |
| `en_serie` | 1 if the hotspot carries weight in the harmonized series; 0 if it is kept only as a record. |
| `eq_foco` | Contribution of the hotspot in MODIS-equivalent cell-days (0 if `en_serie` = 0). |
| `fuente_serie` | `MODIS`, `Terra*kT`, `VIIRS*k`, `VIIRS-N20*k`, `MODIS-hueco` or `fuera_de_serie` (outside the series). |
| `calidad` | `referencia`, `calibrado`, `extrapolado` or empty (outside the series). |

## Weight rules
- 2002-07-04 to 2012: carried by the MODIS hotspots of the cell-day; together they sum to 1.0.
- 2013 onwards: carried by the VIIRS hotspots; together they sum to `k` (0.330 above 2500 m, 0.247 below). MODIS hotspots of those years get `en_serie` = 0.
- 2000 to 2002-07-03 (Terra only): carried by the Terra hotspots; they sum to `kT` (2.62 above 2500 m, 7.74 below). `calidad` = `extrapolado`.
- VIIRS hotspots of 2012 are outside the series (`en_serie` = 0), because the series uses MODIS until the end of 2012.

## Filters
Only `type == 0` (vegetation). MODIS with `confidence >= 30`; VIIRS with `n` or `h`. Region: Cusco polygon (FAO GAUL). Source: FIRMS yearly per-country archives.

## What it is not
A hotspot does not measure burned area or fire intensity: it is a pixel with a thermal anomaly at the time of the satellite overpass. To aggregate, sum `eq_foco`; do not count rows.

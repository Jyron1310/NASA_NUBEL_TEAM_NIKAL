"""Verificación de integridad de los CSV armonizados (celda-día y focos individuales).

Uso: python -I verificar_datos.py <harmonizado_cusco_celda_dia.csv> <focos_cusco_individuales.csv>
Sale con código 1 si falla alguna comprobación (apto para CI).
"""
import sys

import numpy as np
import pandas as pd

# En Windows la consola usa cp1252 y no puede imprimir símbolos como "Δ": print() lanzaba
# UnicodeEncodeError y el script se caía antes de terminar. Se fuerza UTF-8 aquí porque
# `python -I` (modo aislado, como se ejecuta en el CI) ignora la variable PYTHONUTF8.
for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        _flujo.reconfigure(encoding="utf-8", errors="replace")

COLS_CD = ["fecha_local", "cell_lat", "cell_lon", "alt_m", "n_modis", "n_viirs", "frp_modis", "frp_viirs",
           "eq_hotspots", "fuente_serie", "calidad"]
COLS_FO = ["fecha_local", "fecha_utc", "hora_utc", "latitude", "longitude", "cell_lat", "cell_lon", "alt_m",
           "sensor", "satelite", "frp", "brillo_k", "confianza", "diurno_nocturno", "fuente_serie", "calidad",
           "en_serie", "eq_foco"]
fallos = []


def chk(cond, msg):
    cond = bool(cond)
    print(("OK     " if cond else "FALLA  ") + msg)
    if not cond:
        fallos.append(msg)


if len(sys.argv) != 3:
    sys.exit(__doc__)
cd = pd.read_csv(sys.argv[1])
fo = pd.read_csv(sys.argv[2], dtype={"hora_utc": str, "confianza": str})

print("=== Celda-día: %d filas ===" % len(cd))
chk(list(cd.columns) == COLS_CD, "columnas y orden esperados")
chk(cd.drop(columns=["alt_m"]).isna().sum().sum() == 0, "sin nulos (salvo alt_m)")
f = pd.to_datetime(cd.fecha_local, format="%Y-%m-%d", errors="coerce")
chk(f.notna().all(), "fechas con formato YYYY-MM-DD")
chk(f.min() >= pd.Timestamp("2000-11-01") and f.max() <= pd.Timestamp("2025-12-31"),
    "rango de fechas %s a %s" % (f.min().date(), f.max().date()))
chk(not cd.duplicated(["fecha_local", "cell_lat", "cell_lon"]).any(), "clave (fecha, celda) única")
chk(cd.cell_lat.between(-15.5, -11.2).all() and cd.cell_lon.between(-74.0, -70.3).all(), "celdas dentro del bbox de Cusco")
chk((np.round(np.abs(cd.cell_lat) * 1000) % 10 == 5).all() and (np.round(np.abs(cd.cell_lon) * 1000) % 10 == 5).all(),
    "centros de celda sobre la malla de 0.01°")
chk(((cd.n_modis >= 0) & (cd.n_viirs >= 0) & ((cd.n_modis + cd.n_viirs) > 0)).all()
    and (cd.n_modis % 1 == 0).all() and (cd.n_viirs % 1 == 0).all(), "conteos enteros, no negativos y con al menos un foco")
chk(((cd.frp_modis >= 0) & (cd.frp_viirs >= 0)).all(), "FRP no negativo")
chk((cd.eq_hotspots > 0).all() and (cd.eq_hotspots < 10).all(), "eq_hotspots en (0, 10)")
v = cd.fuente_serie
VIIRS_SERIE = {"VIIRS*k", "VIIRS-N20*k"}            # v1.3: NOAA-20 en los días sin S-NPP
DESDE_2013 = VIIRS_SERIE | {"MODIS-hueco"}
chk(set(v.unique()) <= {"MODIS", "Terra*kT"} | DESDE_2013, "valores de fuente_serie válidos")
chk((v.isin(DESDE_2013) == (f >= pd.Timestamp("2013-01-01"))).all(),
    "desde 2013-01-01 la serie es VIIRS*k (o su relleno: VIIRS-N20*k, MODIS-hueco)")
dias_snpp = set(cd.fecha_local[v == "VIIRS*k"])
chk(not (set(cd.fecha_local[v.isin({"VIIRS-N20*k", "MODIS-hueco"})]) & dias_snpp),
    "el relleno (NOAA-20 o MODIS) solo está en días sin ninguna celda-día S-NPP")
chk(((v == "Terra*kT") == (f < pd.Timestamp("2002-07-04"))).all(), "Terra*kT exactamente antes de 2002-07-04")
chk((cd.calidad == v.map({"VIIRS*k": "calibrado", "VIIRS-N20*k": "calibrado", "Terra*kT": "extrapolado",
                          "MODIS": "referencia", "MODIS-hueco": "referencia"})).all(),
    "calidad coherente con fuente_serie")
chk(((~v.isin(VIIRS_SERIE)) | (cd.n_viirs > 0)).all() and ((v.isin(VIIRS_SERIE)) | (cd.n_modis > 0)).all(),
    "cada fila tiene focos del sensor que lleva su serie")
est = np.where(cd.alt_m >= 2500, "alto", "bajo")
g = cd.assign(est=est).groupby(["fuente_serie", "est"]).eq_hotspots.agg(["nunique", "min", "size"])
chk((g["nunique"] == 1).all(), "un único factor por (fuente, estrato)")
chk((cd[v.isin({"MODIS", "MODIS-hueco"})].eq_hotspots == 1.0).all(), "MODIS pesa exactamente 1.0")
print(g.rename(columns={"min": "factor", "size": "filas"}).to_string())
chk(set(range(2001, 2026)) <= set(f.dt.year), "hay datos en todos los años 2001-2025")

print("\n=== Focos individuales: %d filas ===" % len(fo))
chk(list(fo.columns) == COLS_FO, "columnas y orden esperados")
claves = ["fecha_local", "fecha_utc", "hora_utc", "latitude", "longitude", "cell_lat", "cell_lon", "sensor",
          "satelite", "frp", "confianza", "en_serie", "eq_foco", "fuente_serie"]
chk(fo[claves].notna().all().all(), "sin nulos en columnas clave")
chk(fo.hora_utc.str.fullmatch(r"\d{4}").all(), "hora_utc con 4 dígitos (leer como texto)")
chk(set(zip(fo.sensor, fo.satelite)) <= {("MODIS", "Terra"), ("MODIS", "Aqua"), ("VIIRS", "Suomi-NPP"),
                                           ("VIIRS", "NOAA-20")},
    "combinaciones sensor/satélite válidas")
chk(not fo.duplicated().any(), "sin filas totalmente idénticas")
nd = int(fo.duplicated(["fecha_utc", "hora_utc", "latitude", "longitude", "satelite"]).sum())
if nd:
    print("AVISO  %d foco(s) repiten fecha, hora, posición y satélite con otro y difieren en FRP "
          "(artefacto conocido de FIRMS, se conservan)" % nd)
chk(nd <= 5, "duplicados por posición/hora dentro de lo esperado (%d)" % nd)
chk((fo.frp >= 0).all(), "FRP no negativo")
chk(set(fo.en_serie.unique()) <= {0, 1}, "en_serie es 0/1")
chk(((fo.eq_foco > 0) == (fo.en_serie == 1)).all(), "eq_foco > 0 exactamente cuando en_serie = 1")
chk((fo[fo.fuente_serie == "fuera_de_serie"].en_serie == 0).all(), "fuera_de_serie no lleva peso")

print("\n=== Consistencia entre los dos archivos ===")
k = ["fecha_local", "cell_lat", "cell_lon"]
m = cd.set_index(k)
sf = fo[fo.en_serie == 1].groupby(k).eq_foco.sum().rename("eq_f")
m = m.join(sf, how="left")
chk(m.eq_f.notna().all(), "toda celda-día tiene focos que llevan su peso")
chk(len(sf.index.difference(cd.set_index(k).index)) == 0, "no hay focos con peso en celdas-día ausentes")
dif = (m.eq_f - m.eq_hotspots).abs()
chk(dif.max() <= 0.01, "reparto de pesos: máx |Δ| por celda-día = %.5f" % dif.max())
chk(abs(fo.eq_foco.sum() - cd.eq_hotspots.sum()) <= 0.5, "totales: %.2f (focos) vs %.2f (celda-día)" % (
    fo.eq_foco.sum(), cd.eq_hotspots.sum()))
cnt = fo.groupby(k + ["sensor"]).size().unstack(fill_value=0).reindex(m.index).fillna(0)
chk((cnt.get("MODIS", 0) == m.n_modis).all() and (cnt.get("VIIRS", 0) == m.n_viirs).all(),
    "conteos por sensor coinciden con n_modis y n_viirs")

print("\n%s" % ("TODO OK" if not fallos else "FALLARON %d COMPROBACIONES" % len(fallos)))
sys.exit(1 if fallos else 0)

"""CSV de focos individuales de Cusco con peso armonizado por foco.

Uso: python -I focos_individuales.py <firms_raw> <cusco_ref> <harmonizado_celda_dia.csv> <salida>
El peso por foco reparte el eq_hotspots de su celda-día entre los focos del sensor que lleva la serie.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.path import Path as Ruta

raw, ref, csvh, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
out.mkdir(parents=True, exist_ok=True)
PASO = 0.01
lim, meta, elev = json.load(open(ref / "limite.json")), json.load(open(ref / "meta.json")), np.load(ref / "elev.npy")
rutas = [Ruta(np.array(g["coordinates"][0])) for g in
         (lim["geometries"] if lim["type"] == "GeometryCollection" else [lim]) if g["type"] == "Polygon"]


def archivos_firms(raw, prefijo):
    """Acepta los nombres que entrega FIRMS (viirs-snpp_2023_Peru.csv) y los renombrados (snpp_2023.csv)."""
    pats = {"modis": ["modis_*.csv"], "snpp": ["snpp_*.csv", "viirs-snpp_*.csv"]}[prefijo]
    fs = sorted({f for p in pats for f in raw.glob(p)})
    if not fs:
        sys.exit("ERROR: no hay archivos %s en %s (se buscan %s)" % (prefijo, raw, pats))
    ms = [re.search(r"20\d\d", f.name) for f in fs]
    anios = [m.group(0) if m else f.name for m, f in zip(ms, fs)]
    if len(set(anios)) != len(anios):
        sys.exit("ERROR: hay más de un archivo %s para el mismo año: %s" % (prefijo, [f.name for f in fs]))
    return fs


def cargar(prefijo, viirs):
    d = pd.concat([pd.read_csv(f) for f in archivos_firms(raw, prefijo)], ignore_index=True)
    if viirs:
        d = d[(d["type"] == 0) & (d["confidence"].isin(["n", "h"]))].copy()
    else:
        d = d[(d["type"] == 0) & (pd.to_numeric(d["confidence"], errors="coerce") >= 30)].copy()
    pts = d[["longitude", "latitude"]].to_numpy()
    m = np.zeros(len(d), bool)
    for r in rutas:
        m |= r.contains_points(pts)
    d = d[m].copy()
    t = pd.to_numeric(d["acq_time"], errors="coerce").fillna(0).astype(int)
    ts = pd.to_datetime(d["acq_date"]) + pd.to_timedelta(t // 100, unit="h") + pd.to_timedelta(t % 100, unit="m")
    d["fecha_utc"] = d["acq_date"].astype(str)
    d["hora_utc"] = t.map("{:04d}".format)
    d["fecha_local"] = (ts - pd.Timedelta(hours=5)).dt.normalize().dt.strftime("%Y-%m-%d")
    d["cell_lat"] = (np.floor(d.latitude / PASO) * PASO + PASO / 2).round(3)
    d["cell_lon"] = (np.floor(d.longitude / PASO) * PASO + PASO / 2).round(3)
    j = np.floor((d.cell_lon - meta["lon0"]) / meta["paso"]).astype(int).clip(0, elev.shape[1] - 1)
    i = np.floor((meta["lat1"] - d.cell_lat) / meta["paso"]).astype(int).clip(0, elev.shape[0] - 1)
    e = elev[i, j].astype(float)
    d["alt_m"] = np.where(e > -9000, e, np.nan).round(0)
    d["sensor"] = "VIIRS" if viirs else "MODIS"
    d["satelite"] = "Suomi-NPP" if viirs else d["satellite"]
    d["brillo_k"] = d["bright_ti4"] if viirs else d["brightness"]
    d["confianza"] = d["confidence"].astype(str)
    d["diurno_nocturno"] = d["daynight"]
    return d[["fecha_local", "fecha_utc", "hora_utc", "latitude", "longitude", "cell_lat", "cell_lon", "alt_m",
              "sensor", "satelite", "frp", "brillo_k", "confianza", "diurno_nocturno"]]


if not rutas:
    sys.exit("ERROR: el límite de Cusco no tiene polígonos (¿cambió el formato de limite.json?)")
d = pd.concat([cargar("modis", False), cargar("snpp", True)], ignore_index=True)
if d.empty:
    sys.exit("ERROR: sin focos tras los filtros (¿cambió el formato de FIRMS?)")
H = pd.read_csv(csvh)[["fecha_local", "cell_lat", "cell_lon", "eq_hotspots", "fuente_serie", "calidad"]]
H["cell_lat"], H["cell_lon"] = H.cell_lat.round(3), H.cell_lon.round(3)
d = d.merge(H, on=["fecha_local", "cell_lat", "cell_lon"], how="left")
f = d.fuente_serie
carga = ((f == "VIIRS*k") & (d.sensor == "VIIRS")) | ((f == "MODIS") & (d.sensor == "MODIS")) | \
        ((f == "Terra*kT") & (d.satelite == "Terra"))
d["en_serie"] = carga.astype(int)
n = carga.groupby([d.fecha_local, d.cell_lat, d.cell_lon]).transform("sum")
d["eq_foco"] = np.where(carga & (n > 0), d.eq_hotspots / n.where(n > 0, 1), 0.0).round(4)
d["fuente_serie"] = d.fuente_serie.fillna("fuera_de_serie")
d["calidad"] = d.calidad.fillna("")
d = d.drop(columns="eq_hotspots").sort_values(["fecha_local", "latitude", "longitude"])
d.to_csv(out / "focos_cusco_individuales.csv", index=False)

print("filas: %d | MODIS %d | VIIRS %d | en_serie %d (%.0f %%)" % (
    len(d), (d.sensor == "MODIS").sum(), (d.sensor == "VIIRS").sum(), d.en_serie.sum(), 100 * d.en_serie.mean()))
print("verificación: suma eq_foco = %.1f | suma eq_hotspots del CSV celda-día = %.1f" % (d.eq_foco.sum(), H.eq_hotspots.sum()))
dia = d.groupby("fecha_local").eq_foco.sum()
dia = dia[dia > 0]
print("Cusco entero: %d días con fuego de %d posibles | eq por día, percentiles 50/75/90/95/99/máx: %s" % (
    len(dia), (pd.Timestamp("2025-12-31") - pd.Timestamp("2000-11-04")).days, np.round(dia.quantile([.5, .75, .9, .95, .99, 1]).to_numpy(), 1)))

"""CSV armonizado de Cusco (celda-día) con factor k único por estrato.

Uso: python -I firms_csv.py <firms_raw> <cusco_ref> <salida>
Calibra k = celda-días MODIS / celda-días VIIRS en 2013-2019, por estrato de altitud.
"""
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.path import Path as Ruta

raw, ref, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
out.mkdir(parents=True, exist_ok=True)
CAL = (pd.Timestamp("2013-01-01"), pd.Timestamp("2019-12-31"))
PASO = 0.01

lim = json.load(open(ref / "limite.json"))
meta = json.load(open(ref / "meta.json"))
elev = np.load(ref / "elev.npy")
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
    d = d[m].copy()                                   # solo Cusco
    t = pd.to_numeric(d["acq_time"], errors="coerce").fillna(0).astype(int)
    ts = pd.to_datetime(d["acq_date"]) + pd.to_timedelta(t // 100, unit="h") + pd.to_timedelta(t % 100, unit="m")
    d["loc"] = (ts - pd.Timedelta(hours=5)).dt.normalize()
    d["clat"] = np.floor(d.latitude / PASO) * PASO + PASO / 2
    d["clon"] = np.floor(d.longitude / PASO) * PASO + PASO / 2
    j = np.floor((d.clon - meta["lon0"]) / meta["paso"]).astype(int).clip(0, elev.shape[1] - 1)
    i = np.floor((meta["lat1"] - d.clat) / meta["paso"]).astype(int).clip(0, elev.shape[0] - 1)
    e = elev[i, j]
    d["alt"] = np.where(e > -9000, e, np.nan)
    d["terra"] = (d["satellite"] == "Terra").astype(int)
    return d


mod, vii = cargar("modis", False), cargar("snpp", True)
if not rutas or len(mod) == 0 or len(vii) == 0:
    sys.exit("ERROR: sin polígonos de Cusco o sin focos tras los filtros (¿cambió el formato de FIRMS o del límite?)")
print("Aqua en Cusco: primer foco", mod[mod.satellite == "Aqua"]["loc"].min().date(),
      "| Terra:", mod[mod.satellite == "Terra"]["loc"].min().date())
gm = mod.groupby(["loc", "clat", "clon"]).agg(n_modis=("frp", "size"), frp_modis=("frp", "sum"), alt=("alt", "first"),
                                              n_terra=("terra", "sum"))
gv = vii.groupby(["loc", "clat", "clon"]).agg(n_viirs=("frp", "size"), frp_viirs=("frp", "sum"), alt_v=("alt", "first"))
h = gm.join(gv, how="outer")
h["alt"] = h["alt"].fillna(h["alt_v"])
h = h.drop(columns="alt_v").reset_index()
for c in ("n_modis", "n_viirs", "frp_modis", "frp_viirs", "n_terra"):
    h[c] = h[c].fillna(0)
h["cm"], h["ct"] = h.n_modis > 0, h.n_terra > 0
h["estrato"] = np.where(h.alt >= 2500, "alto", "bajo")

k = {}
for est in ("alto", "bajo"):
    s = h[(h.estrato == est) & (h["loc"] >= CAL[0]) & (h["loc"] <= CAL[1])]
    k[est] = (s.n_modis > 0).sum() / (s.n_viirs > 0).sum()
print("k por estrato (celda-días MODIS por celda-día VIIRS, 2013-19):", {a: round(b, 3) for a, b in k.items()})

DESDE_V = pd.Timestamp("2013-01-01")
AQUA = pd.Timestamp("2002-07-04")                 # inicio de datos de Aqua
ent = lambda s, a, b: s[(s["loc"] >= pd.Timestamp(a)) & (s["loc"] <= pd.Timestamp(b))]


def razon_terra(s):                               # celda-días MODIS (Terra+Aqua) por celda-día Terra
    return s.cm.sum() / max(s.ct.sum(), 1)


# --- Paso 2: factor Terra -> Terra+Aqua (calibra 2003-12; valida calibrando 2003-07 y prediciendo 2008-12)
kT = {}
for est in ("alto", "bajo"):
    sub = h[h.estrato == est]
    kT[est] = razon_terra(ent(sub, "2003-01-01", "2012-12-31"))
    k5 = razon_terra(ent(sub, "2003-01-01", "2007-12-31"))
    v = ent(sub, "2008-01-01", "2012-12-31")
    mes = v.assign(m=v["loc"].dt.to_period("M")).groupby("m").agg(cm_=("cm", "sum"), ct_=("ct", "sum"))
    ok = mes.cm_ >= 15
    md = np.median(np.abs(mes.ct_ * k5 - mes.cm_)[ok] / mes.cm_[ok])
    anual = v.assign(a=v["loc"].dt.year).groupby("a").agg(cm_=("cm", "sum"), ct_=("ct", "sum"))
    print("kT %-4s = %.2f (calib 2003-12) | validación 2008-12 con k de 2003-07 = %.2f: MdAPE mensual %.0f %% (%d meses) | anual obs/pred: %s" % (
        est, kT[est], k5, 100 * md, ok.sum(), [(int(a), int(r.cm_), int(round(r.ct_ * k5))) for a, r in anual.iterrows()]))

loc = h["loc"]
w_v, w_t = h.estrato.map(k).to_numpy(), h.estrato.map(kT).to_numpy()
h["eq_hotspots"] = np.where((loc >= DESDE_V) & (h.n_viirs > 0), w_v,
                            np.where((loc < AQUA) & h.ct, w_t,
                                     np.where((loc < DESDE_V) & h.cm, 1.0, 0.0)))
h["fuente_serie"] = np.where(loc >= DESDE_V, "VIIRS*k", np.where(loc < AQUA, "Terra*kT", "MODIS"))
h["calidad"] = np.where(loc >= DESDE_V, "calibrado", np.where(loc < AQUA, "extrapolado", "referencia"))

# --- Paso 3: continuidad 2013-25: celda-días MODIS reales vs VIIRS*k (calibrado solo con 2013-19)
c3 = h[(loc >= DESDE_V)].assign(a=lambda x: x["loc"].dt.year)
t3 = c3.groupby("a").apply(lambda g: pd.Series({"MODIS_real": int(g.cm.sum()), "VIIRS*k": int(round(g.eq_hotspots.sum()))}))
t3["VIIRS*k/MODIS"] = (t3["VIIRS*k"] / t3["MODIS_real"]).round(2)
print("\nContinuidad (celda-días MODIS reales vs VIIRS*k):")
print(t3.T.to_string())
h = h[h.eq_hotspots > 0].rename(columns={"loc": "fecha_local", "clat": "cell_lat", "clon": "cell_lon", "alt": "alt_m"})
h["fecha_local"] = h["fecha_local"].dt.strftime("%Y-%m-%d")
h = h[["fecha_local", "cell_lat", "cell_lon", "alt_m", "n_modis", "n_viirs", "frp_modis", "frp_viirs",
       "eq_hotspots", "fuente_serie", "calidad"]].round({"cell_lat": 3, "cell_lon": 3, "alt_m": 0, "frp_modis": 1, "frp_viirs": 1, "eq_hotspots": 3})
h.to_csv(out / "harmonizado_cusco_celda_dia.csv", index=False)
print("CSV: %d filas -> %s" % (len(h), out / "harmonizado_cusco_celda_dia.csv"))

h["anio"] = h["fecha_local"].str[:4].astype(int)
print(h.groupby("anio")["eq_hotspots"].sum().round(0).astype(int).to_dict())

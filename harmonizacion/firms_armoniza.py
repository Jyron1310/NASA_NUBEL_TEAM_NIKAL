"""Armonización de focos MODIS y VIIRS a una malla común de ~1 km (celda-día).

Uso: python -I firms_armoniza.py <firms_raw> <cusco_ref> <salida>   (solo diagnostico; no escribe CSV)

Idea: VIIRS (375 m) ve varios píxeles donde MODIS (1 km) ve uno. Al contar CELDA-DÍA con
al menos un foco sobre una malla de 0.01° (~1.1 km) se compara la misma unidad física.
Calibración 2013-2019, validación reservada 2020-2025 (detecta deriva de MODIS).
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
HOLD = (pd.Timestamp("2020-01-01"), pd.Timestamp("2025-12-30"))
PASO = 0.01

lim = json.load(open(ref / "limite.json"))
meta = json.load(open(ref / "meta.json"))
elev = np.load(ref / "elev.npy")
anillos = []
for g in (lim["geometries"] if lim["type"] == "GeometryCollection" else [lim]):
    if g["type"] == "Polygon":
        anillos.append(g["coordinates"][0])
rutas = [Ruta(np.array(a)) for a in anillos]


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
    t = pd.to_numeric(d["acq_time"], errors="coerce").fillna(0).astype(int)
    ts = pd.to_datetime(d["acq_date"]) + pd.to_timedelta(t // 100, unit="h") + pd.to_timedelta(t % 100, unit="m")
    d["loc"] = (ts - pd.Timedelta(hours=5)).dt.normalize()          # fecha local de Perú (UTC-5)
    d["clat"] = np.floor(d.latitude / PASO) * PASO + PASO / 2
    d["clon"] = np.floor(d.longitude / PASO) * PASO + PASO / 2
    pts = d[["longitude", "latitude"]].to_numpy()
    m = np.zeros(len(d), bool)
    for r in rutas:
        m |= r.contains_points(pts)
    d["cusco"] = m
    j = np.floor((d.clon - meta["lon0"]) / meta["paso"]).astype(int).clip(0, elev.shape[1] - 1)
    i = np.floor((meta["lat1"] - d.clat) / meta["paso"]).astype(int).clip(0, elev.shape[0] - 1)
    e = elev[i, j]
    d["alt"] = np.where(m & (e > -9000), e, np.nan)
    return d


mod, vii = cargar("modis", False), cargar("snpp", True)
print("Cargado: MODIS %d | VIIRS %d detecciones filtradas" % (len(mod), len(vii)))

ALC = {"Perú": lambda d: d,
       "Cusco": lambda d: d[d.cusco],
       "Cusco >=2500 m": lambda d: d[d.cusco & (d.alt >= 2500)],
       "Cusco <1500 m": lambda d: d[d.cusco & (d.alt < 1500)]}


def ventana(d, w):
    return d[(d["loc"] >= w[0]) & (d["loc"] <= w[1])]


def n_mes(d):
    return d.groupby(d["loc"].dt.to_period("M")).size()


def cd_mes(d):
    u = d.drop_duplicates(["loc", "clat", "clon"])
    return u.groupby(u["loc"].dt.to_period("M")).size()


def tot(s):
    return float(s.sum())


print("\n=== 1. ¿Baja la razón VIIRS/MODIS al pasar de detecciones a celda-día? ===")
print("%-16s %8s %8s | %8s %8s | %6s" % ("alcance", "n(cal)", "cd(cal)", "n(hold)", "cd(hold)", "deriva"))
tabla = {}
for nom, f in ALC.items():
    mo, vo = f(mod), f(vii)
    r = {}
    for k, w in (("cal", CAL), ("hold", HOLD)):
        r["n_" + k] = tot(n_mes(ventana(vo, w))) / max(tot(n_mes(ventana(mo, w))), 1)
        r["cd_" + k] = tot(cd_mes(ventana(vo, w))) / max(tot(cd_mes(ventana(mo, w))), 1)
    tabla[nom] = r
    print("%-16s %8.2f %8.2f | %8.2f %8.2f | %5.2fx" % (
        nom, r["n_cal"], r["cd_cal"], r["n_hold"], r["cd_hold"], r["cd_hold"] / r["cd_cal"]))
print("(razones VIIRS/MODIS; 'deriva' = razón celda-día en 2020-25 dividida por la de 2013-19)")

print("\n=== 2. ¿Qué plataforma MODIS deriva? Celda-día por año, Perú ===")
ta, aq = mod[mod.satellite == "Terra"], mod[mod.satellite == "Aqua"]
fila = []
for y in range(2013, 2026):
    w = (pd.Timestamp("%d-01-01" % y), pd.Timestamp("%d-12-30" % y))
    t_, a_, v_ = (tot(cd_mes(ventana(x, w))) for x in (ta, aq, vii))
    fila.append((y, int(t_), int(a_), int(v_), round(v_ / t_, 2), round(v_ / a_, 2)))
print(pd.DataFrame(fila, columns=["año", "Terra", "Aqua", "VIIRS", "V/Terra", "V/Aqua"]).to_string(index=False))

print("\n=== 3. Predecir MODIS mensual 2020-25 desde VIIRS (calibrado en 2013-19) ===")
print("%-16s %12s %12s %14s %9s" % ("alcance", "MdAPE n·k", "MdAPE cd·k", "MdAPE cd·k(mes)", "Spearman"))
for nom, f in ALC.items():
    mo, vo = f(mod), f(vii)
    Mc, Vc = cd_mes(ventana(mo, CAL)), cd_mes(ventana(vo, CAL))
    Mh, Vh = cd_mes(ventana(mo, HOLD)), cd_mes(ventana(vo, HOLD))
    Mn, Vn = n_mes(ventana(mo, CAL)), n_mes(ventana(vo, CAL))
    Mnh, Vnh = n_mes(ventana(mo, HOLD)), n_mes(ventana(vo, HOLD))
    k_cd, k_n = tot(Mc) / tot(Vc), tot(Mn) / tot(Vn)
    # factor por mes calendario; si hay pocos datos usa el global
    km = {}
    for m in range(1, 13):
        a = Mc[Mc.index.month == m].sum()
        b = Vc[Vc.index.month == m].sum()
        km[m] = a / b if a >= 30 and b > 0 else k_cd
    idx = Mh.index.intersection(Vh.index)
    obs, v = Mh.loc[idx], Vh.loc[idx]
    ok = obs >= 20
    pred_cd = v * k_cd
    pred_m = pd.Series([v.loc[i] * km[i.month] for i in idx], index=idx)
    idn = Mnh.index.intersection(Vnh.index)
    obs_n, vn = Mnh.loc[idn], Vnh.loc[idn]
    okn = obs_n >= 20
    pred_n = vn * k_n
    md = lambda p, o, m_: float(np.median(np.abs(p[m_] - o[m_]) / o[m_]))
    print("%-16s %11.0f%% %11.0f%% %13.0f%% %9.2f" % (
        nom, 100 * md(pred_n, obs_n, okn), 100 * md(pred_cd, obs, ok), 100 * md(pred_m, obs, ok),
        obs[ok].corr(pred_cd[ok], method="spearman")))
print("(MdAPE: error relativo mediano por mes; n·k = detecciones con factor fijo; "
      "cd·k = celda-día con factor fijo; cd·k(mes) = factor por mes calendario)")

# (El CSV armonizado lo genera firms_csv.py; este script solo imprime diagnosticos.)

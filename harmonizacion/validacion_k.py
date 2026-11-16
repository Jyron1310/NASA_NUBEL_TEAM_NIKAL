"""Incertidumbre y estabilidad del factor k (VIIRS S-NPP -> MODIS), por estrato de altitud.

Uso: python -I validacion_k.py <firms_raw> <cusco_ref> <salida>

Hace dos cosas con las celdas-día de los archivos crudos de FIRMS (mismos filtros, celda y altitud que
firms_csv.py):
1. Intervalo de confianza de k (2013-2019) por remuestreo (bootstrap) de bloques de días: los focos de un
   mismo episodio se repiten en días vecinos, así que se remuestrean meses y semanas completos, no días sueltos.
2. Estabilidad de k: k por año (2013-2025), tendencia, k por temporada, y calibración dejando un año afuera
   (leave-one-year-out) para ver cuánto falla predecir las celdas-día MODIS de un año con k de los demás.
Semilla fija: el resultado es reproducible. No modifica ningún dato.
"""

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.path import Path as Ruta

if len(sys.argv) != 4:
    sys.exit(__doc__)
raw, ref, out = (Path(a) for a in sys.argv[1:])
out.mkdir(parents=True, exist_ok=True)
PASO, B, SEED = 0.01, 5000, 20261115
CAL = (2013, 2019)
EST = ("alto", "bajo")

lim = json.load(open(ref / "limite.json"))
meta = json.load(open(ref / "meta.json"))
elev = np.load(ref / "elev.npy")
rutas = [Ruta(np.array(g["coordinates"][0])) for g in
         (lim["geometries"] if lim["type"] == "GeometryCollection" else [lim]) if g["type"] == "Polygon"]


def celdas_dia(patron, viirs):
    fs = sorted(raw.glob(patron))
    if not fs:
        sys.exit("ERROR: no hay archivos %s en %s" % (patron, raw))
    d = pd.concat([pd.read_csv(f, dtype=str) for f in fs], ignore_index=True)
    conf = d["confidence"]
    ok = (d["type"] == "0") & (conf.isin(["n", "h"]) if viirs else pd.to_numeric(conf, errors="coerce") >= 30)
    d = d[ok].copy()
    lat, lon = d["latitude"].astype(float), d["longitude"].astype(float)
    m = np.zeros(len(d), bool)
    for r in rutas:
        m |= r.contains_points(np.column_stack([lon, lat]))
    d, lat, lon = d[m].copy(), lat[m], lon[m]
    t = pd.to_numeric(d["acq_time"], errors="coerce").fillna(0).astype(int)
    ts = pd.to_datetime(d["acq_date"]) + pd.to_timedelta(t // 100, unit="h") + pd.to_timedelta(t % 100, unit="m")
    d["dia"] = (ts - pd.Timedelta(hours=5)).dt.normalize()
    d["clat"] = (np.floor(lat / PASO) * PASO + PASO / 2).round(3)
    d["clon"] = (np.floor(lon / PASO) * PASO + PASO / 2).round(3)
    j = np.floor((d.clon - meta["lon0"]) / meta["paso"]).astype(int).clip(0, elev.shape[1] - 1)
    i = np.floor((meta["lat1"] - d.clat) / meta["paso"]).astype(int).clip(0, elev.shape[0] - 1)
    e = elev[i, j].astype(float)
    d["alt"] = np.where(e > -9000, e, np.nan)
    g = d.groupby(["dia", "clat", "clon"], as_index=False).agg(alt=("alt", "first"))
    g["est"] = np.where(g.alt >= 2500, "alto", "bajo")
    return g.groupby(["dia", "est"]).size().unstack(fill_value=0).reindex(columns=list(EST), fill_value=0)


mod = celdas_dia("modis_*.csv", False)
vii = celdas_dia("viirs-snpp_*.csv", True)
dias = pd.date_range("2013-01-01", "2025-12-31", freq="D")
M = mod.reindex(dias, fill_value=0)
V = vii.reindex(dias, fill_value=0)
# Días sin S-NPP en todo Perú (v1.3): no hay VIIRS que comparar; se excluyen de la calibración y del análisis.
sin_snpp = ~dias.isin(pd.read_csv(raw / "viirs-snpp_2013_Peru.csv", usecols=["acq_date"]).pipe(
    lambda x: pd.concat([x] + [pd.read_csv(f, usecols=["acq_date"]) for f in sorted(raw.glob("viirs-snpp_*.csv"))
                               if "2013" not in f.name])).acq_date.pipe(pd.to_datetime).unique())
M, V, dias_ok = M[~sin_snpp], V[~sin_snpp], dias[~sin_snpp]
print("Días analizados: %d (excluidos %d sin S-NPP)" % (len(dias_ok), int(sin_snpp.sum())))
yr = dias_ok.year.to_numpy()
mes = (dias_ok.year * 100 + dias_ok.month).to_numpy()
sem = (dias_ok.year * 100 + dias_ok.isocalendar().week.to_numpy())
rng = np.random.default_rng(SEED)


def k_de(m, v):
    return m.sum() / v.sum()


def boot_k(sel, bloque, est):
    """IC95 % de k por bootstrap de bloques dentro de la ventana `sel`."""
    m, v, b = M[est].to_numpy()[sel], V[est].to_numpy()[sel], bloque[sel]
    ub = np.unique(b)
    sm = np.array([m[b == u].sum() for u in ub], float)
    sv = np.array([v[b == u].sum() for u in ub], float)
    idx = rng.integers(0, len(ub), (B, len(ub)))
    ks = sm[idx].sum(1) / sv[idx].sum(1)
    return sm.sum() / sv.sum(), np.percentile(ks, [2.5, 97.5]), ks


filas, txt = [], []
EN = {"alto": "high", "bajo": "low"}       # nombre del estrato en el informe (inglés)
cal = (yr >= CAL[0]) & (yr <= CAL[1])
txt.append("## 1. Confidence interval of k (calibration %d-%d, bootstrap with %d resamples)\n" % (*CAL, B))
txt.append("| stratum | k | 95 % CI (month blocks) | 95 % CI (week blocks) | relative width | MODIS / VIIRS cell-days |")
txt.append("|---|---|---|---|---|---|")
KS = {}
for e in EST:
    k, ci_m, _ = boot_k(cal, mes, e)
    _, ci_s, _ = boot_k(cal, sem, e)
    KS[e] = k
    txt.append("| %s | %.3f | %.3f – %.3f | %.3f – %.3f | ±%.1f %% | %d / %d |" % (
        EN[e], k, *ci_m, *ci_s, 100 * (ci_m[1] - ci_m[0]) / 2 / k, M[e].to_numpy()[cal].sum(), V[e].to_numpy()[cal].sum()))
    filas.append(dict(analisis="k_calibracion", estrato=e, k=k, ic_lo=ci_m[0], ic_hi=ci_m[1]))

txt.append("\n## 2. Stability of k by year (all cell-days of that year)\n")
txt.append("| year | k high | 95 % CI | k low | 95 % CI |")
txt.append("|---|---|---|---|---|")
por_anio = {e: {} for e in EST}
for a in range(2013, 2026):
    sel = yr == a
    cel = []
    for e in EST:
        k, ci, _ = boot_k(sel, mes, e)
        por_anio[e][a] = (k, ci)
        cel += ["%.3f" % k, "%.3f – %.3f" % tuple(ci)]
        filas.append(dict(analisis="k_por_anio", estrato=e, anio=a, k=k, ic_lo=ci[0], ic_hi=ci[1]))
    txt.append("| %d | %s |" % (a, " | ".join(cel)))

txt.append("\n### Trend of k with year (2013-2024; 2025 apart because of the MODIS drop)\n")
txt.append("| stratum | slope (per year) | 95 % CI | includes 0? |")
txt.append("|---|---|---|---|")
for e in EST:
    anios = np.arange(2013, 2025)
    ys = np.array([por_anio[e][a][0] for a in anios])
    pend = np.polyfit(anios, ys, 1)[0]
    # bootstrap: remuestrear los años de k (con su propio bootstrap de bloques) y reajustar la recta
    sl = []
    for _ in range(2000):
        yb = []
        for a in anios:
            sel = yr == a
            ub = np.unique(mes[sel])
            pick = rng.choice(ub, len(ub))
            mm = sum(M[e].to_numpy()[sel & (mes == u)].sum() for u in pick)
            vv = sum(V[e].to_numpy()[sel & (mes == u)].sum() for u in pick)
            yb.append(mm / vv)
        sl.append(np.polyfit(anios, yb, 1)[0])
    lo, hi = np.percentile(sl, [2.5, 97.5])
    txt.append("| %s | %+.4f | %+.4f – %+.4f | %s |" % (EN[e], pend, lo, hi, "yes" if lo <= 0 <= hi else "NO"))
    filas.append(dict(analisis="tendencia_k", estrato=e, k=pend, ic_lo=lo, ic_hi=hi))

txt.append("\n## 3. Leave-one-year-out calibration (2013-2025, 2025 never used for calibration)\n")
txt.append("k is computed with all the other years of 2013-2024 and used to predict the annual MODIS cell-day total of the omitted year (k × VIIRS). Ratio = predicted / actual MODIS.\n")
txt.append("| year | ratio high | ratio low | ratio total |")
txt.append("|---|---|---|---|")
tot = {}
for a in range(2013, 2026):
    base = (yr >= 2013) & (yr <= 2024) & (yr != a)
    rr = {}
    for e in EST:
        k = k_de(M[e].to_numpy()[base], V[e].to_numpy()[base])
        rr[e] = k * V[e].to_numpy()[yr == a].sum() / M[e].to_numpy()[yr == a].sum()
        filas.append(dict(analisis="loyo", estrato=e, anio=a, k=rr[e]))
    pt = sum(KS_ * V[e].to_numpy()[yr == a].sum() for e, KS_ in
             ((e, k_de(M[e].to_numpy()[base], V[e].to_numpy()[base])) for e in EST))
    ob = sum(M[e].to_numpy()[yr == a].sum() for e in EST)
    tot[a] = pt / ob
    txt.append("| %d | %.2f | %.2f | %.2f |" % (a, rr["alto"], rr["bajo"], tot[a]))
v = np.array([tot[a] for a in range(2013, 2025)])
txt.append("\n2013-2024: median ratio %.2f, minimum %.2f, maximum %.2f; median annual relative error %.1f %%." % (
    np.median(v), v.min(), v.max(), 100 * np.median(np.abs(v - 1))))

txt.append("\n## 4. k by season (calibration 2013-2019)\n")
txt.append("| season | k high | k low |")
txt.append("|---|---|---|")
m_ = dias_ok.month.to_numpy()
for nombre, rotulo, sel_m in (("seca", "dry (Jun–Oct)", (m_ >= 6) & (m_ <= 10)), ("húmeda", "wet (Nov–May)", (m_ >= 11) | (m_ <= 5))):
    s = cal & sel_m
    ks = []
    for e in EST:
        k = k_de(M[e].to_numpy()[s], V[e].to_numpy()[s])
        ks.append(k)
        filas.append(dict(analisis="k_temporada_" + nombre, estrato=e, k=k))
    txt.append("| %s | %.3f | %.3f |" % (rotulo, *ks))

pd.DataFrame(filas).to_csv(out / "validacion_k.csv", index=False)
(out / "validacion_k.md").write_text("\n".join(txt) + "\n", encoding="utf-8")
print("\n".join(txt))

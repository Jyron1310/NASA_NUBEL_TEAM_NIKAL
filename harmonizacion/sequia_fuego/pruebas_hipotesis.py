"""Pruebas de hipótesis sobre el índice de sequía (SPI, CHIRPS) y su relación con el fuego en Cusco.

Uso: python -I pruebas_hipotesis.py <clima_cusco.npz> <cusco_ref> <csv_armonizado>
Parte A: validez del índice (homogeneidad, tendencia, quiebre, calibración).
Parte B: hipótesis sequía -> fuego (sentido unilateral: más sequía, más fuego), con Holm.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.path import Path as Ruta
from scipy import stats

npz, ref, csv = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
c = np.load(npz)
P_, N_, Y0, LON0, LAT1, PX = c["precip"], c["ndvi"], int(c["y0"]), float(c["lon0"]), float(c["lat1"]), float(c["paso"])
NY, NX = P_.shape[2:]
lim, meta, elev = json.load(open(ref / "limite.json")), json.load(open(ref / "meta.json")), np.load(ref / "elev.npy")
anillos = [np.array(g["coordinates"][0]) for g in
           (lim["geometries"] if lim["type"] == "GeometryCollection" else [lim]) if g["type"] == "Polygon"]
lon, lat = LON0 + PX * (np.arange(NX) + .5), LAT1 - PX * (np.arange(NY) + .5)
LO, LA = np.meshgrid(lon, lat)
dentro = np.zeros(LO.shape, bool)
for a in anillos:
    dentro |= Ruta(a).contains_points(np.c_[LO.ravel(), LA.ravel()]).reshape(LO.shape)
mu = []
for dy in range(-2, 3):
    for dx in range(-2, 3):
        j = np.clip(np.floor((LO + dx * .01 - meta["lon0"]) / meta["paso"]).astype(int), 0, elev.shape[1] - 1)
        i = np.clip(np.floor((meta["lat1"] - (LA + dy * .01)) / meta["paso"]).astype(int), 0, elev.shape[0] - 1)
        e = elev[i, j].astype(float)
        e[e < -9000] = np.nan
        mu.append(e)
alt_px = np.nanmean(mu, axis=0)
S = {"alto": dentro & (alt_px >= 2500), "bajo": dentro & (alt_px < 2500)}
NT = P_.shape[0] * 12
anio_t, mes_t = Y0 + np.arange(NT) // 12, np.arange(NT) % 12 + 1


def spi(x, k, base=(1981, 2010)):
    s = pd.Series(x).rolling(k, min_periods=k).sum().to_numpy()
    o = np.full(len(s), np.nan)
    for m in range(1, 13):
        idx = np.where(mes_t == m)[0]
        v = s[idx]
        b = (anio_t[idx] >= base[0]) & (anio_t[idx] <= base[1]) & np.isfinite(v)
        vb = v[b]
        pos = vb[vb > 0]
        if len(vb) < 20 or len(pos) < 10:
            continue
        q = 1 - len(pos) / len(vb)
        a, _, sc = stats.gamma.fit(pos, floc=0)
        H = q + (1 - q) * stats.gamma.cdf(np.where(np.isfinite(v), v, 0), a, 0, sc)
        r = stats.norm.ppf(np.clip(H, 1e-4, 1 - 1e-4))
        r[~np.isfinite(v)] = np.nan
        o[idx] = r
    return o


def zmes(x, y_ini, y_fin):
    z = np.full(len(x), np.nan)
    for m in range(1, 13):
        idx = np.where(mes_t == m)[0]
        r = x[idx][(anio_t[idx] >= y_ini) & (anio_t[idx] <= y_fin)]
        r = r[np.isfinite(r)]
        if len(r) > 5 and r.std() > 0:
            z[idx] = (x[idx] - r.mean()) / r.std()
    return z


rain, reg = {}, {}
for s, mk in S.items():
    rain[s] = np.nanmean(P_[..., mk], axis=-1).reshape(-1)
    nd = np.nanmean(N_[..., mk], axis=-1).reshape(-1)
    reg[s] = {"SPI3": spi(rain[s], 3), "SPI6": spi(rain[s], 6), "SPI12": spi(rain[s], 12), "NDVIz": zmes(nd, 2001, 2025)}

# ===================== PARTE A: el índice ==================================================
print("=== A. Pruebas sobre el índice (CHIRPS regional, año hidrológico sep-ago) ===")
print("A1-A3: lluvia anual 1982-2026. A1 compara 1982-2010 (base del SPI) vs 2011-2026.")
print("%-5s %8s %8s %6s | %7s %7s | %6s %6s %9s | %-12s" % (
    "estr", "mm base", "mm 11-26", "d%", "Welch p", "MW p", "tau MK", "p MK", "Sen mm/a", "Pettitt (p)"))
for s in ("alto", "bajo"):
    ys = np.arange(1982, 2027)
    ann = np.array([rain[s][(y - 1 - Y0) * 12 + 8:(y - 1 - Y0) * 12 + 20].sum() for y in ys])
    b1, b2 = ann[ys <= 2010], ann[ys >= 2011]
    tau, pmk = stats.kendalltau(ys, ann)
    sen = stats.theilslopes(ann, ys)[0]
    n = len(ann)
    r = stats.rankdata(ann)
    U = np.array([2 * r[:k].sum() - k * (n + 1) for k in range(1, n)])
    K = np.abs(U).max()
    pp = min(1.0, 2 * np.exp(-6 * K ** 2 / (n ** 3 + n ** 2)))
    print("%-5s %8.0f %8.0f %5.0f%% | %7.3f %7.3f | %+6.2f %6.3f %+9.1f | %d (%.3f)" % (
        s, b1.mean(), b2.mean(), 100 * (b2.mean() / b1.mean() - 1), stats.ttest_ind(b2, b1, equal_var=False)[1],
        stats.mannwhitneyu(b2, b1)[1], tau, pmk, sen, ys[1:][np.argmax(np.abs(U))], pp))

print("\nA4. Calibración del SPI-6 (todos los meses): bajo H0 es N(0,1) y P(SPI<=-1)=15.9 %")
print("%-5s %-10s %5s %6s %5s %8s %8s %8s" % ("estr", "ventana", "n", "media", "sd", "%<=-1", "p binom", "p KS"))
for s in ("alto", "bajo"):
    for nom, a0, a1 in (("1981-2010", 1981, 2010), ("2011-2026", 2011, 2026), ("2003-2025", 2003, 2025)):
        x = reg[s]["SPI6"][(anio_t >= a0) & (anio_t <= a1)]
        x = x[np.isfinite(x)]
        k = int((x <= -1).sum())
        print("%-5s %-10s %5d %+6.2f %5.2f %7.1f%% %8.3f %8.3f" % (
            s, nom, len(x), x.mean(), x.std(), 100 * k / len(x),
            stats.binomtest(k, len(x), 0.1587).pvalue, stats.kstest(x, "norm").pvalue))
print("(meses consecutivos autocorrelacionados: p binomial/KS son optimistas; leer como diagnóstico)")

# ===================== PARTE B: sequía -> fuego ============================================
f = pd.read_csv(csv)
f = f[f.calidad != "extrapolado"].copy()
f["y"], f["m"] = f.fecha_local.str[:4].astype(int), f.fecha_local.str[5:7].astype(int)
f = f[(f.y >= 2003) & (f.y <= 2025) & f.alt_m.notna()]
fuego = {}
for s, cond in (("alto", f.alt_m >= 2500), ("bajo", f.alt_m < 2500)):
    g = f[cond].groupby(["y", "m"]).eq_hotspots.sum()
    a = np.full(NT, np.nan)
    for y in range(2003, 2026):
        for m in range(1, 13):
            a[(y - Y0) * 12 + m - 1] = g.get((y, m), 0.0)
    fuego[s] = a
FS = [7, 8, 9, 10]
yrs = np.arange(2003, 2026)
tf = np.array([t for t in range(NT) if mes_t[t] in FS and 2003 <= anio_t[t] <= 2025])
ix = lambda mm: np.array([(y - Y0) * 12 + mm - 1 for y in yrs])
fa = {s: np.array([fuego[s][[(y - Y0) * 12 + m - 1 for m in FS]].sum() for y in yrs]) for s in ("alto", "bajo")}


def ols_cl(y, X, cl):                                   # OLS con errores robustos por conglomerado (año)
    ok = np.isfinite(y) & np.all(np.isfinite(X), 1)
    y, X, cl = y[ok], X[ok], cl[ok]
    XtXi = np.linalg.inv(X.T @ X)
    b = XtXi @ X.T @ y
    u = y - X @ b
    gs = np.unique(cl)
    meat = sum(np.outer(X[cl == g].T @ u[cl == g], X[cl == g].T @ u[cl == g]) for g in gs)
    G, (N, K) = len(gs), X.shape
    V = G / (G - 1) * (N - 1) / (N - K) * XtXi @ meat @ XtXi
    se = np.sqrt(np.diag(V))
    return b, se, 2 * stats.t.sf(np.abs(b / se), G - 1)


uni = lambda b, p2: p2 / 2 if b < 0 else 1 - p2 / 2        # H1: pendiente negativa (más sequía, más fuego)
fam = []                                                    # familia confirmatoria para Holm

print("\n=== B1. Anual: años secos vs húmedos (terciles de SPI-6 jun), fuego jul-oct; Mann-Whitney 1 cola ===")
print("H1: el fuego es mayor en el tercil seco que en el húmedo")
print("%-5s %5s %12s %12s %6s %8s" % ("estr", "n", "mediana seco", "mediana hum.", "AUC", "p"))
for s in ("alto", "bajo"):
    sp = reg[s]["SPI6"][ix(6)]
    r = stats.rankdata(sp)
    seco, hum = fa[s][r <= 8], fa[s][r >= 16]
    u = stats.mannwhitneyu(seco, hum, alternative="greater")
    fam.append(("B1 anual terciles " + s, u.pvalue))
    print("%-5s %5s %12.0f %12.0f %6.2f %8.3f" % (s, "8v8", np.median(seco), np.median(hum), u.statistic / (8 * 8), u.pvalue))

print("\n=== B2. Mensual jul-oct (n=92): z(log1p fuego) ~ SPI std., errores robustos por año (22 gl) ===")
print("H1: pendiente < 0. 'tend' = control por tendencia lineal. beta = cambio en z-fuego por 1 sd de SPI")
print("%-5s %-6s %2s | %7s %6s %8s | %7s %8s" % ("estr", "pred", "L", "beta", "ee", "p(1c)", "b tend", "p tend"))
cl = anio_t[tf]
tend = (anio_t[tf] - 2014) / 10.0
for s in ("alto", "bajo"):
    zf = zmes(np.log1p(fuego[s]), 2003, 2025)
    for p in ("SPI3", "SPI6", "SPI12", "NDVIz"):
        for L in (0, 1):
            x = reg[s][p][tf - L]
            xs = (x - np.nanmean(x)) / np.nanstd(x)
            b, se, p2 = ols_cl(zf[tf], np.c_[np.ones(len(tf)), xs], cl)
            b2, se2, p22 = ols_cl(zf[tf], np.c_[np.ones(len(tf)), xs, tend], cl)
            if p == "SPI6":
                fam.append(("B2 mensual SPI6 L=%d %s" % (L, s), uni(b[1], p2[1])))
            print("%-5s %-6s %2d | %+7.2f %6.2f %8.3f | %+7.2f %8.3f" % (
                s, p, L, b[1], se[1], uni(b[1], p2[1]), b2[1], uni(b2[1], p22[1])))

print("\n=== B3. Año de fuego alto (top 25 % = 6 años) vs año seco (SPI-6 jun bajo la mediana); Fisher 1 cola ===")
for s in ("alto", "bajo"):
    sp = reg[s]["SPI6"][ix(6)]
    seco = sp <= np.median(sp)
    alto = fa[s] >= np.sort(fa[s])[-6]
    a, b_, c_, d = (seco & alto).sum(), (~seco & alto).sum(), (seco & ~alto).sum(), (~seco & ~alto).sum()
    p = stats.fisher_exact([[a, b_], [c_, d]], alternative="greater")[1]
    fam.append(("B3 Fisher " + s, p))
    print("%-5s fuego alto & seco %d | alto & no seco %d | no alto & seco %d | ninguno %d | POD %.2f | FAR %.2f | p=%.3f" % (
        s, a, b_, c_, d, a / (a + b_), c_ / (a + c_), p))

print("\n=== B4. Exploratoria (hipótesis surgida de mirar los datos; no entra en Holm): combustible ===")
for s in ("alto", "bajo"):
    sp, nd = reg[s]["SPI6"][ix(6)], (reg[s]["NDVIz"][ix(3)] + reg[s]["NDVIz"][ix(4)]) / 2
    Z = lambda v: (stats.rankdata(v) - stats.rankdata(v).mean()) / stats.rankdata(v).std()
    X = np.c_[np.ones(23), Z(sp), Z(nd)]
    y = Z(fa[s])
    b = np.linalg.lstsq(X, y, rcond=None)[0]
    res = y - X @ b
    se = np.sqrt(np.diag(res @ res / 20 * np.linalg.inv(X.T @ X)))
    pv = 2 * stats.t.sf(np.abs(b / se), 20)
    print("%-5s rangos: fuego ~ SPI6 jun [%+.2f, p=%.2f] + NDVI mar-abr [%+.2f, p=%.2f]" % (s, b[1], pv[1], b[2], pv[2]))

print("\n=== Corrección de Holm sobre la familia confirmatoria (%d pruebas) ===" % len(fam))
fam.sort(key=lambda t: t[1])
m_, run = len(fam), 0.0
print("%-32s %8s %9s" % ("prueba", "p cruda", "p Holm"))
for k, (nom, p) in enumerate(fam):
    run = max(run, min(1.0, (m_ - k) * p))
    print("%-32s %8.3f %9.3f" % (nom, p, run))
n = 23
for al, nom in ((0.05, "2 colas"), (0.10, "1 cola")):
    z = (stats.norm.ppf(1 - al / (2 if nom == "2 colas" else 1)) + stats.norm.ppf(0.8)) / np.sqrt(n - 3)
    print("Potencia 80%% con n=23 (%s, alfa .05): detecta |rho| >= %.2f" % (nom, np.tanh(z))) if al == 0.05 else None
z = (stats.norm.ppf(0.95) + stats.norm.ppf(0.8)) / np.sqrt(n - 3)
print("Potencia 80%% con n=23 (1 cola, alfa .05): detecta |rho| >= %.2f" % np.tanh(z))

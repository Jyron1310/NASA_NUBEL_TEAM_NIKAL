"""Relación sequía-fuego en Cusco: SPI (CHIRPS) y NDVI (MOD13A3) vs focos armonizados (eq_hotspots).

Uso: python -I sequia_fuego.py <clima_cusco.npz> <cusco_ref> <csv_armonizado> <salida>
Fuego: 2003-2025 (MODIS referencia + VIIRS*k; sin los años extrapolados). SPI: base gamma 1981-2010.
"""
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.path import Path as Ruta
from scipy import stats

npz, ref, csv, out = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])
out.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(7)

c = np.load(npz)
P_, N_, Y0, LON0, LAT1, PX = c["precip"], c["ndvi"], int(c["y0"]), float(c["lon0"]), float(c["lat1"]), float(c["paso"])
NY, NX = P_.shape[2:]
lim = json.load(open(ref / "limite.json"))
meta = json.load(open(ref / "meta.json"))
elev = np.load(ref / "elev.npy")
anillos = [np.array(g["coordinates"][0]) for g in
           (lim["geometries"] if lim["type"] == "GeometryCollection" else [lim]) if g["type"] == "Polygon"]

# --- píxeles de 0.05°: dentro de Cusco y altitud media --------------------------------
lon = LON0 + PX * (np.arange(NX) + .5)
lat = LAT1 - PX * (np.arange(NY) + .5)
LO, LA = np.meshgrid(lon, lat)
dentro = np.zeros(LO.shape, bool)
for a in anillos:
    dentro |= Ruta(a).contains_points(np.c_[LO.ravel(), LA.ravel()]).reshape(LO.shape)
muestras = []
for dy in range(-2, 3):
    for dx in range(-2, 3):
        j = np.clip(np.floor((LO + dx * .01 - meta["lon0"]) / meta["paso"]).astype(int), 0, elev.shape[1] - 1)
        i = np.clip(np.floor((meta["lat1"] - (LA + dy * .01)) / meta["paso"]).astype(int), 0, elev.shape[0] - 1)
        e = elev[i, j].astype(float)
        e[e < -9000] = np.nan
        muestras.append(e)
alt_px = np.nanmean(muestras, axis=0)
S = {"alto": dentro & (alt_px >= 2500), "bajo": dentro & (alt_px < 2500)}
print("píxeles 0.05° en Cusco: %d | alto (>=2500 m): %d | bajo: %d" % (dentro.sum(), S["alto"].sum(), S["bajo"].sum()))

NT = P_.shape[0] * 12
anio_t = Y0 + np.arange(NT) // 12
mes_t = np.arange(NT) % 12 + 1


def spi(x, k, base=(1981, 2010), solo=None):
    s = pd.Series(x).rolling(k, min_periods=k).sum().to_numpy()
    o = np.full(len(s), np.nan)
    for m in (range(1, 13) if solo is None else solo):
        idx = np.where(mes_t[:len(s)] == m)[0]
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


def zmes(x, y_ini, y_fin):                         # anomalía estandarizada por mes calendario
    z = np.full(len(x), np.nan)
    for m in range(1, 13):
        idx = np.where(mes_t == m)[0]
        ref_ = x[idx][(anio_t[idx] >= y_ini) & (anio_t[idx] <= y_fin)]
        ref_ = ref_[np.isfinite(ref_)]
        if len(ref_) > 5 and ref_.std() > 0:
            z[idx] = (x[idx] - ref_.mean()) / ref_.std()
    return z


# --- series regionales por estrato -------------------------------------------------------
reg = {}
for s, mk in S.items():
    rain = np.nanmean(P_[..., mk], axis=-1).reshape(-1)
    nd = np.nanmean(N_[..., mk], axis=-1).reshape(-1)
    reg[s] = {"SPI3": spi(rain, 3), "SPI6": spi(rain, 6), "SPI12": spi(rain, 12), "NDVIz": zmes(nd, 2001, 2025)}

# --- fuego mensual por estrato ---------------------------------------------------------
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
print("fuego 2003-25 (eq. celda-días): alto %.0f | bajo %.0f | %% del alto en jul-oct: %.0f" % (
    np.nansum(fuego["alto"]), np.nansum(fuego["bajo"]),
    100 * np.nansum(fuego["alto"][np.isin(mes_t, [7, 8, 9, 10])]) / np.nansum(fuego["alto"])))

FS = [7, 8, 9, 10]
tf = np.array([t for t in range(NT) if mes_t[t] in FS and 2003 <= anio_t[t] <= 2025])


def spear(x, y):
    ok = np.isfinite(x) & np.isfinite(y)
    return stats.spearmanr(x[ok], y[ok])[0] if ok.sum() > 8 else np.nan


# --- Test A: mensual, jul-oct, anomalía desestacionalizada, bootstrap por año -------------
print("\n=== A. Mensual jul-oct 2003-25 (n=%d): rho Spearman [IC95%% bootstrap por año] ===" % len(tf))
print("fuego = z(log1p) por mes; predictor medido L meses antes del mes de fuego (L=0: mismo mes)")
anios = np.unique(anio_t[tf])
print("%-5s %-6s %s" % ("estr", "pred", "".join("%-21s" % ("L=%d" % L) for L in range(4))))
nsig = 0
for s in ("alto", "bajo"):
    zf = zmes(np.log1p(fuego[s]), 2003, 2025)
    for p in ("SPI3", "SPI6", "SPI12", "NDVIz"):
        fila = ""
        for L in range(4):
            x, y = reg[s][p][tf - L], zf[tf]
            r0 = spear(x, y)
            bs = []
            for _ in range(600):
                ys = rng.choice(anios, len(anios))
                ix = np.concatenate([np.where(anio_t[tf] == a)[0] for a in ys])
                bs.append(spear(x[ix], y[ix]))
            lo, hi = np.nanpercentile(bs, [2.5, 97.5])
            sig = lo > 0 or hi < 0
            nsig += sig
            fila += "%+.2f[%+.2f,%+.2f]%s " % (r0, lo, hi, "*" if sig else " ")
        print("%-5s %-6s %s" % (s, p, fila))
print("* = IC95%% excluye 0. Hay 32 pruebas: por azar se esperan ~1.6 marcadas; marcadas: %d" % nsig)

# --- Test B: anual (fuego jul-oct del año) vs sequía acumulada previa --------------------
print("\n=== B. Anual 2003-25 (n=23): fuego jul-oct vs predictores; rho y p de permutación ===")
yrs = np.arange(2003, 2026)
ix = lambda mm: np.array([(y - Y0) * 12 + mm - 1 for y in yrs])
fa = {s: np.array([fuego[s][[(y - Y0) * 12 + m - 1 for m in FS]].sum() for y in yrs]) for s in ("alto", "bajo")}
pred = lambda s: {
    "SPI-3 mar (ene-mar)": reg[s]["SPI3"][ix(3)], "SPI-6 jun (ene-jun)": reg[s]["SPI6"][ix(6)],
    "SPI-12 jun (jul ant.-jun)": reg[s]["SPI12"][ix(6)], "SPI-12 sep": reg[s]["SPI12"][ix(9)],
    "NDVI z mar-abr": (reg[s]["NDVIz"][ix(3)] + reg[s]["NDVIz"][ix(4)]) / 2,
    "NDVI z jun-jul": (reg[s]["NDVIz"][ix(6)] + reg[s]["NDVIz"][ix(7)]) / 2}
res = {}
for s in ("alto", "bajo"):
    print("-- estrato %s" % s)
    for nom, x in pred(s).items():
        r0 = spear(x, fa[s])
        pp = np.mean([abs(spear(x, rng.permutation(fa[s]))) >= abs(r0) for _ in range(3000)])
        res[(s, nom)] = (r0, pp)
        print("   %-26s rho %+.2f  p=%.3f" % (nom, r0, pp))
print("(12 pruebas; con 23 años y 12 pruebas, p<0.05 aislado no es evidencia fuerte)")

a = pred("alto")
print("\nAño | fuego alto JASO | fuego bajo JASO | SPI-12 jun | SPI-6 jun | NDVI z mar-abr")
for k_, y in enumerate(yrs):
    print("%d | %7.0f | %7.0f | %+5.2f | %+5.2f | %+5.2f" % (
        y, fa["alto"][k_], fa["bajo"][k_], a["SPI-12 jun (jul ant.-jun)"][k_], a["SPI-6 jun (ene-jun)"][k_], a["NDVI z mar-abr"][k_]))

# --- Mapa: dónde hay fuego y dónde coincide con sequía --------------------------------------
fj = f[f.m.isin(FS)].copy()
fj["i"] = np.floor((LAT1 - fj.cell_lat) / PX).astype(int)
fj["j"] = np.floor((fj.cell_lon - LON0) / PX).astype(int)
fj = fj[(fj.i >= 0) & (fj.i < NY) & (fj.j >= 0) & (fj.j < NX)]
FP = np.zeros((23, NY, NX))
g = fj.groupby(["y", "i", "j"]).eq_hotspots.sum()
for (y, i, j), v in g.items():
    FP[y - 2003, i, j] = v
media = FP.mean(axis=0)
rho = np.full((NY, NX), np.nan)
for i in range(NY):
    for j in range(NX):
        if dentro[i, j] and (FP[:, i, j] > 0).sum() >= 8:
            sp6 = spi(P_[:, :, i, j].reshape(-1), 6, solo=[6])
            rho[i, j] = spear(sp6[ix(6)], FP[:, i, j])
ok = np.isfinite(rho)
print("\nMapa: píxeles con fuego en >=8 de 23 años: %d | rho(fuego jul-oct, SPI-6 jun) mediana %+.2f | %% píxeles con rho<0: %.0f" % (
    ok.sum(), np.nanmedian(rho), 100 * (rho[ok] < 0).mean()))

fig, ax = plt.subplots(1, 3, figsize=(14, 4.6), constrained_layout=True)
ext = [LON0, LON0 + NX * PX, LAT1 - NY * PX, LAT1]
m1 = np.where(dentro, media, np.nan)
im = ax[0].imshow(np.log10(m1 + 0.01), extent=ext, cmap="YlOrRd", vmin=-1.5, vmax=1)
fig.colorbar(im, ax=ax[0], shrink=.8, label="log10(celda-días eq. por año, jul-oct)")
im = ax[1].imshow(np.where(ok, rho, np.nan), extent=ext, cmap="PuOr", vmin=-.8, vmax=.8)
fig.colorbar(im, ax=ax[1], shrink=.8, label="rho fuego vs SPI-6 jun (neg = más fuego con sequía)")
for k_ in (0, 1):
    for an in anillos:
        ax[k_].plot(an[:, 0], an[:, 1], color="#444", lw=.6)
    ax[k_].set_xlim(ext[0], ext[1]); ax[k_].set_ylim(ext[2], ext[3]); ax[k_].set_aspect("equal")
ax[0].set_title("Dónde hay fuego (media 2003-25)"); ax[1].set_title("Dónde fuego y sequía se acompañan")
ax[2].bar(yrs, fa["alto"], color="#c0504d", alpha=.8)
ax[2].set_ylabel("celda-días eq. jul-oct (≥2500 m)"); ax[2].set_title("Altoandino: fuego y SPI-12 de junio")
t2 = ax[2].twinx()
t2.plot(yrs, a["SPI-12 jun (jul ant.-jun)"], color="#1f4e79", marker="o", lw=1.2)
t2.axhline(0, color="#999", lw=.6); t2.set_ylabel("SPI-12 jun", color="#1f4e79")
fig.savefig(out / "sequia_fuego.png", dpi=130)
print("figura:", out / "sequia_fuego.png")

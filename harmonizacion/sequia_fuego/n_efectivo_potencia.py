"""Muestra efectiva y potencia a priori para la relación sequía-fuego (piloto Cusco, píxeles 0.05° x año).

Uso: python -I n_efectivo_potencia.py <clima_cusco.npz> <cusco_ref> <csv_armonizado>
Predictor: SPI-6 de junio por píxel (base 1981-2010). Resultado: log1p(celda-días eq. jul-oct) por píxel-año.
Estimadores:  E1 regional anual (n=23) | E2 panel con efectos fijos de píxel y año (contraste espacial)
              | E3 panel con efecto fijo de píxel, errores por año.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.path import Path as Ruta
from scipy import stats

npz, ref, csv = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
rng = np.random.default_rng(11)
c = np.load(npz)
P_, Y0, LON0, LAT1, PX = c["precip"], int(c["y0"]), float(c["lon0"]), float(c["lat1"]), float(c["paso"])
NY, NX = P_.shape[2:]
lim = json.load(open(ref / "limite.json"))
anillos = [np.array(g["coordinates"][0]) for g in
           (lim["geometries"] if lim["type"] == "GeometryCollection" else [lim]) if g["type"] == "Polygon"]
lon, lat = LON0 + PX * (np.arange(NX) + .5), LAT1 - PX * (np.arange(NY) + .5)
LO, LA = np.meshgrid(lon, lat)
dentro = np.zeros(LO.shape, bool)
for a in anillos:
    dentro |= Ruta(a).contains_points(np.c_[LO.ravel(), LA.ravel()]).reshape(LO.shape)
NT = P_.shape[0] * 12
anio_t, mes_t = Y0 + np.arange(NT) // 12, np.arange(NT) % 12 + 1
YRS = np.arange(2003, 2026)
G = len(YRS)


def spi6_jun(x):                                  # SPI-6 de junio, base gamma 1981-2010, devuelve dict año -> SPI
    s = pd.Series(x).rolling(6, min_periods=6).sum().to_numpy()
    idx = np.where(mes_t == 6)[0]
    v = s[idx]
    b = (anio_t[idx] >= 1981) & (anio_t[idx] <= 2010) & np.isfinite(v)
    vb = v[b]
    pos = vb[vb > 0]
    if len(pos) < 10:
        return None
    q = 1 - len(pos) / len(vb)
    a, _, sc = stats.gamma.fit(pos, floc=0)
    H = q + (1 - q) * stats.gamma.cdf(np.where(np.isfinite(v), v, 0), a, 0, sc)
    return dict(zip(anio_t[idx], stats.norm.ppf(np.clip(H, 1e-4, 1 - 1e-4))))


ii, jj = np.where(dentro)
cols, keep = [], []
for k, (i, j) in enumerate(zip(ii, jj)):
    d = spi6_jun(P_[:, :, i, j].reshape(-1))
    if d is not None and all(y in d for y in YRS):
        cols.append([d[y] for y in YRS])
        keep.append(k)
X_all = np.array(cols).T                            # [23, npix]
ii, jj = ii[keep], jj[keep]
npix = X_all.shape[1]
area_px = (PX * 111.32 * np.cos(np.deg2rad(-13))) * (PX * 110.57)
print("píxeles de 0.05° en Cusco con SPI-6 jun 2003-25: %d (área píxel ~%.0f km², total ~%.0f km²)" % (npix, area_px, npix * area_px))

# --- 1. ¿Cuánto del SPI es común a toda la región? -----------------------------------------
gm = X_all.mean()
v_tot = ((X_all - gm) ** 2).mean()
v_year = ((X_all.mean(1) - gm) ** 2).mean()
v_pix = ((X_all.mean(0) - gm) ** 2).mean()
print("\n=== 1. Descomposición de la varianza del SPI-6 jun (píxel-año) ===")
print("común del año (toda la región): %.0f %% | diferencia fija entre píxeles: %.0f %% | contraste espacial dentro del año: %.0f %%" % (
    100 * v_year / v_tot, 100 * v_pix / v_tot, 100 * (v_tot - v_year - v_pix) / v_tot))

R = X_all - X_all.mean(0) - X_all.mean(1)[:, None] + gm      # residual: sin efecto de año ni de píxel
xk = (lon[jj] - LON0) * 111.32 * np.cos(np.deg2rad(-13))
yk = (lat[ii] - LAT1) * 110.57
D = np.hypot(xk[:, None] - xk[None, :], yk[:, None] - yk[None, :])
iu = np.triu_indices(npix, 1)
print("\n=== 2. Correlación entre píxeles (a lo largo de los 23 años) según distancia ===")
print("%-10s %10s %14s" % ("dist (km)", "r SPI crudo", "r sin año/píxel"))
Rc, Xc = np.corrcoef(R.T)[iu], np.corrcoef(X_all.T)[iu]
d = D[iu]
bins = [0, 30, 60, 100, 200, 400]
Ls = []
for a, b in zip(bins[:-1], bins[1:]):
    m = (d >= a) & (d < b)
    rr, rx = np.nanmean(Rc[m]), np.nanmean(Xc[m])
    if rr > 0.05:
        Ls.append(-((a + b) / 2) / np.log(rr))
    print("%3d-%-6d %10.2f %14.2f" % (a, b, rx, rr))
L = float(np.median(Ls)) if Ls else 5.0
Ns = min(npix, (npix * area_px) / (2 * np.pi * L ** 2))
print("Escala de decorrelación del contraste espacial L ≈ %.0f km -> parches independientes por año ≈ %.0f" % (L, Ns))

# --- 3. Fuego por píxel-año ------------------------------------------------------------------
f = pd.read_csv(csv)
f = f[f.calidad != "extrapolado"].copy()
f["y"], f["m"] = f.fecha_local.str[:4].astype(int), f.fecha_local.str[5:7].astype(int)
f = f[(f.y >= 2003) & (f.y <= 2025) & f.m.isin([7, 8, 9, 10])]
f["i"] = np.floor((LAT1 - f.cell_lat) / PX).astype(int)
f["j"] = np.floor((f.cell_lon - LON0) / PX).astype(int)
FP = np.zeros((G, NY, NX))
for (y, i, j), v in f.groupby(["y", "i", "j"]).eq_hotspots.sum().items():
    if 0 <= i < NY and 0 <= j < NX:
        FP[y - 2003, i, j] = v
Fm = FP[:, ii, jj]
sel = (Fm > 0).sum(0) >= 8
Yl = np.log1p(Fm[:, sel])
X = X_all[:, sel]
print("\n=== 3. Unidades comparables ===")
print("píxeles totales %d | con fuego en >=8 de 23 años: %d -> %d píxel-años" % (npix, sel.sum(), sel.sum() * G))
Yc = Yl - Yl.mean(0)
print("fuego: %.0f %% de la varianza (tras quitar el nivel de cada píxel) es común del año; SPI: %.0f %%" % (
    100 * (Yc.mean(1) ** 2).mean() / (Yc ** 2).mean(), 100 * v_year / v_tot))
print("muestra efectiva: contraste entre años = %d años | contraste espacial dentro del año ≈ %d años x %.0f parches = %.0f" % (
    G, G, Ns, G * Ns))
print("(pero solo el %.0f %% de la varianza del SPI es contraste espacial: poca señal por observación)" % (100 * (v_tot - v_year - v_pix) / v_tot))

Y = (Yl - Yl.mean()) / Yl.std()
X = (X - X.mean()) / X.std()


def cluster(xd, yd):
    sxx = (xd ** 2).sum()
    b = (xd * yd).sum() / sxx
    u = yd - b * xd
    s = (xd * u).sum(1)
    n = xd.size
    V = G / (G - 1) * (n - 1) / (n - 2) * (s ** 2).sum() / sxx ** 2
    return b, stats.t.cdf(b / np.sqrt(V), G - 1)           # p unilateral: pendiente < 0 (más sequía, más fuego)


def estima(Y, X):
    r = stats.linregress(X.mean(1), Y.mean(1))
    e1 = (r.slope, stats.t.cdf(r.slope / r.stderr, G - 2))
    e3 = cluster(X - X.mean(0), Y - Y.mean(0))
    xx = X - X.mean(0) - X.mean(1)[:, None] + X.mean()
    yy = Y - Y.mean(0) - Y.mean(1)[:, None] + Y.mean()
    return e1, cluster(xx, yy), e3


print("\n=== 4. Piloto real Cusco (exploratorio: ya vimos estos datos). beta en sd de fuego por sd de SPI; p unilateral ===")
for nom, e in zip(("E1 regional anual", "E2 panel FE pixel+año", "E3 panel FE píxel"), estima(Y, X)):
    print("%-24s beta %+.3f  p=%.3f" % (nom, e[0], e[1]))

# --- 5. Potencia: ruido real remuestreando años, efecto conocido sumado --------------------------
Xp = X - X.mean(0)
b_pool = (Xp * (Y - Y.mean(0))).sum() / (Xp ** 2).sum()
Y0r = Y - b_pool * X                                      # se quita la asociación observada: queda ruido realista
Y0r = (Y0r - Y0r.mean()) / Y0r.std()
print("\n=== 5. Potencia (alfa .05 unilateral, %d simulaciones por celda; ruido = residuos reales con años remuestreados) ===" % 500)
print("beta = sd de fuego por cada sd de SPI (negativo en la realidad: más sequía, más fuego). 'rho anual' = correlación implícita a nivel regional-anual")
print("%6s %9s | %10s %10s %10s" % ("beta", "rho anual", "E1 anual", "E2 FE p+a", "E3 FE píxel"))
for beta in (0.0, 0.05, 0.1, 0.2, 0.3, 0.5):
    hit, rhos = np.zeros(3), []
    for _ in range(500):
        yr = rng.integers(0, G, G)
        Ys = Y0r[yr] - beta * X
        for k, e in enumerate(estima(Ys, X)):
            hit[k] += e[1] < 0.05
        rhos.append(np.corrcoef(Ys.mean(1), X.mean(1))[0, 1])
    print("%6.2f %9.2f | %9.0f%% %9.0f%% %9.0f%%" % (beta, -np.mean(np.abs(rhos)) if beta else 0.0, *(100 * hit / 500)))
print("beta=0 es el error tipo I: debe rondar 5 %")

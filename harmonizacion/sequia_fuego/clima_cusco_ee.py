"""Lluvia mensual CHIRPS (1981-) y NDVI mensual MOD13A3 (2000-) de Cusco en una grilla de 0.05°.

Uso: python clima_cusco_ee.py <salida>     (necesita Earth Engine; define la variable EE_PROJECT)
Salida: clima_cusco.npz con precip[año, mes, fila, col], ndvi[...] (NaN donde no hay dato).
"""
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import os

import ee
import numpy as np

ee.Initialize(project=os.environ.get("EE_PROJECT"))      # define EE_PROJECT con tu proyecto de Earth Engine
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
LON0, LAT1, LON1, LAT0, P = -74.0, -11.2, -70.3, -15.5, 0.05
NX, NY = int(round((LON1 - LON0) / P)), int(round((LAT1 - LAT0) / P))
TR = [P, 0, LON0, 0, -P, LAT1]
reg = ee.Geometry.Rectangle([LON0, LAT0, LON1, LAT1], proj="EPSG:4326", geodesic=False)

chirps = ee.ImageCollection("UCSB-CHG/CHIRPS/PENTAD").select("precipitation")
mod = (ee.ImageCollection("MODIS/061/MOD13A3"))


def rango(col):
    a = ee.Date(col.aggregate_min("system:time_start")).getInfo()["value"]
    b = ee.Date(col.aggregate_max("system:time_start")).getInfo()["value"]
    f = lambda ms: np.datetime64(int(ms), "ms").astype("datetime64[M]")
    return f(a), f(b)


c0, c1 = rango(chirps)
m0, m1 = rango(mod)
print("CHIRPS pentad: %s -> %s | MOD13A3: %s -> %s | grilla %d x %d" % (c0, c1, m0, m1, NY, NX))


def mes_ok(ini, fin, y, m):
    t = np.datetime64("%04d-%02d" % (y, m))
    return ini <= t <= fin


def pedir(tipo, y):
    bandas, ms = [], []
    for m in range(1, 13):
        a = ee.Date.fromYMD(y, m, 1)
        b = a.advance(1, "month")
        if tipo == "p":
            if not mes_ok(c0, c1 - 1, y, m):          # el último mes puede estar incompleto: se descarta
                continue
            img = chirps.filterDate(a, b).sum()
        else:
            if not mes_ok(m0, m1, y, m):
                continue
            im = mod.filterDate(a, b).first()
            img = im.select("NDVI").updateMask(im.select("SummaryQA").lte(1)).toFloat().multiply(0.0001) \
                .reduceResolution(ee.Reducer.mean(), maxPixels=1024)
        bandas.append(img.rename("m%02d" % m))
        ms.append(m)
    if not bandas:
        return y, tipo, {}
    im = ee.Image.cat(bandas).reproject(crs="EPSG:4326", crsTransform=TR)
    for intento in range(4):
        try:
            prop = im.sampleRectangle(region=reg, defaultValue=-9999).getInfo()["properties"]
            return y, tipo, {m: np.array(prop["m%02d" % m], dtype="float32")[:NY, :NX] for m in ms}   # EE puede dar una fila de más en el borde
        except Exception as e:                      # reintento ante timeouts de EE
            err = e
    raise RuntimeError("falló %s %d: %s" % (tipo, y, err))


Y0 = 1981
P_ = np.full((46, 12, NY, NX), np.nan, "float32")
N_ = np.full((46, 12, NY, NX), np.nan, "float32")
fp = out / "precip_parcial.npy"
if fp.exists():
    P_ = np.load(fp)
    print("lluvia cargada de", fp)
for tipo, anios in (("p", range(1981, 2027)), ("n", range(2000, 2027))):
    if tipo == "p" and fp.exists():
        continue
    with ThreadPoolExecutor(4) as ex:
        for y, t, d in ex.map(lambda a: pedir(tipo, a), anios):
            for m, arr in d.items():
                arr[arr < -9000] = np.nan
                (P_ if t == "p" else N_)[y - Y0, m - 1] = arr
    if tipo == "p":
        np.save(fp, P_)
np.savez_compressed(out / "clima_cusco.npz", precip=P_, ndvi=N_, y0=Y0, lon0=LON0, lat1=LAT1, paso=P)
print("meses con lluvia: %d | con NDVI: %d" % (np.isfinite(P_[..., 0, 0]).sum() + 0, np.isfinite(N_).any(axis=(2, 3)).sum()))
print("guardado:", out / "clima_cusco.npz")

"""Relleno de los días sin VIIRS S-NPP con VIIRS NOAA-20 (versión 1.3 de los datos).

Uso: python -I relleno_n20.py <firms_raw> <cusco_ref> <entrada_v1.2> <salida>

- <firms_raw>: archivos anuales de FIRMS por país (modis_*, viirs-snpp_* y viirs-jpss1_* de Perú).
- <cusco_ref>: límite y altitud de Cusco (cusco_ref/).
- <entrada_v1.2>: carpeta con los dos CSV de la v1.2 (salida de firms_csv.py y focos_individuales.py).
- <salida>: carpeta donde se escriben los dos CSV de la v1.3.

Problema (docs/team/revisar_antonio.md): desde 2013 la serie usa solo VIIRS S-NPP (`VIIRS*k`). Hay días en que S-NPP no
entregó ningún dato de Perú (por ejemplo, del 27-jul al 10-ago de 2022). En la v1.2 esos días valen 0 aunque haya
fuego, porque no hay ninguna celda-día S-NPP.

Método:
1. Día sin S-NPP = día local (UTC-5), desde 2013, sin ninguna fila S-NPP en el archivo de todo Perú (sin filtros):
   el satélite no entregó datos, no es que no hubiera fuego.
2. Factor k20 (NOAA-20 -> escala MODIS), encadenado por S-NPP para que NOAA-20 reemplace a S-NPP:
   k20[estrato] = k[estrato] x (celda-días S-NPP / celda-días NOAA-20), con los mismos filtros y la misma celda que
   firms_csv.py, en los días en que los dos satélites entregaron datos. Se calibra con 2018-2021 y se valida con
   2022-2025 (años reservados), igual que k (METHODOLOGY.md: no recalibrar con los años de validación).
3. Cada día sin S-NPP se rellena con las celdas-día NOAA-20 de Cusco, peso k20 (fuente_serie `VIIRS-N20*k`,
   calidad `calibrado`). Si NOAA-20 tampoco tiene datos de Perú ese día (antes de 2018-01-05 o por otro hueco), se
   usan las celdas-día MODIS con peso 1.0 (fuente_serie `MODIS-hueco`, calidad `referencia`), como en 2002-2012.
4. Las demás filas de la v1.2 no cambian (se copian tal cual, mismo formato y fin de línea).
"""

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.path import Path as Ruta

if len(sys.argv) != 5:
    sys.exit(__doc__)
raw, ref, ent, out = (Path(a) for a in sys.argv[1:])
out.mkdir(parents=True, exist_ok=True)
PASO = 0.01
DESDE_V = pd.Timestamp("2013-01-01")
FIN = pd.Timestamp("2025-12-31")
CAL = ("2018-01-01", "2021-12-31")      # calibración de k20
VAL = ("2022-01-01", "2025-12-31")      # validación (reservada)
K = {"alto": 0.330, "bajo": 0.247}      # k de S-NPP de la v1.2 (METHODOLOGY.md); se comprueba contra el CSV
CD_CSV, FO_CSV = "harmonizado_cusco_celda_dia.csv", "focos_cusco_individuales.csv"
FUENTE_N20, FUENTE_MOD = "VIIRS-N20*k", "MODIS-hueco"

lim = json.load(open(ref / "limite.json"))
meta = json.load(open(ref / "meta.json"))
elev = np.load(ref / "elev.npy")
rutas = [Ruta(np.array(g["coordinates"][0])) for g in
         (lim["geometries"] if lim["type"] == "GeometryCollection" else [lim]) if g["type"] == "Polygon"]
if not rutas:
    sys.exit("ERROR: el límite de Cusco no tiene polígonos (¿cambió el formato de limite.json?)")


def archivos(patron):
    fs = sorted(raw.glob(patron))
    if not fs:
        sys.exit("ERROR: no hay archivos %s en %s" % (patron, raw))
    return fs


def leer(patron):
    """Archivos de FIRMS como texto (para conservar los valores tal como vienen) + fecha local."""
    d = pd.concat([pd.read_csv(f, dtype=str) for f in archivos(patron)], ignore_index=True)
    t = pd.to_numeric(d["acq_time"], errors="coerce").fillna(0).astype(int)
    ts = pd.to_datetime(d["acq_date"]) + pd.to_timedelta(t // 100, unit="h") + pd.to_timedelta(t % 100, unit="m")
    d["loc"] = (ts - pd.Timedelta(hours=5)).dt.normalize()
    d["hora_utc"] = t.map("{:04d}".format)
    return d


def cusco(d, viirs):
    """Mismos filtros, celda y altitud que firms_csv.py y focos_individuales.py."""
    conf = d["confidence"]
    ok = (d["type"] == "0") & (conf.isin(["n", "h"]) if viirs else pd.to_numeric(conf, errors="coerce") >= 30)
    d = d[ok].copy()
    lat, lon = d["latitude"].astype(float), d["longitude"].astype(float)
    m = np.zeros(len(d), bool)
    for r in rutas:
        m |= r.contains_points(np.column_stack([lon, lat]))
    d = d[m].copy()
    d["lat"], d["lon"] = lat[m].to_numpy(), lon[m].to_numpy()
    d["clat"] = (np.floor(d.lat / PASO) * PASO + PASO / 2).round(3)
    d["clon"] = (np.floor(d.lon / PASO) * PASO + PASO / 2).round(3)
    j = np.floor((d.clon - meta["lon0"]) / meta["paso"]).astype(int).clip(0, elev.shape[1] - 1)
    i = np.floor((meta["lat1"] - d.clat) / meta["paso"]).astype(int).clip(0, elev.shape[0] - 1)
    e = elev[i, j].astype(float)
    d["alt"] = np.where(e > -9000, e, np.nan).round(0)
    d["frp_f"] = d["frp"].astype(float)
    return d


def dias_con_datos(d):
    return set(d["loc"])


# --- 1. Días sin S-NPP (todo Perú, sin filtros)
snpp_pe, n20_pe, mod_pe = leer("viirs-snpp_*.csv"), leer("viirs-jpss1_*.csv"), leer("modis_*.csv")
dias = pd.date_range(DESDE_V, FIN, freq="D")
con_snpp, con_n20 = dias_con_datos(snpp_pe), dias_con_datos(n20_pe)
huecos = [x for x in dias if x not in con_snpp]
print("Días sin S-NPP en todo Perú (2013-2025): %d | con NOAA-20 ese día: %d | sin ninguno de los dos: %d" % (
    len(huecos), sum(x in con_n20 for x in huecos), sum(x not in con_n20 for x in huecos)))

snpp, n20, mod = cusco(snpp_pe, True), cusco(n20_pe, True), cusco(mod_pe, False)


def celdas(d):
    """Celdas-día con al menos un foco, por estrato."""
    g = d.groupby(["loc", "clat", "clon"]).agg(n=("frp_f", "size"), frp=("frp_f", "sum"), alt=("alt", "first"))
    g["estrato"] = np.where(g.alt >= 2500, "alto", "bajo")
    return g.reset_index()


cs, c20, cm = celdas(snpp), celdas(n20), celdas(mod)

# --- 2. Calibración de k20 en los días en que los dos satélites entregaron datos
comunes = {x for x in con_snpp & con_n20 if DESDE_V <= x <= FIN}


def entre(c, a, b):
    return c[(c["loc"] >= pd.Timestamp(a)) & (c["loc"] <= pd.Timestamp(b)) & c["loc"].isin(comunes)]


r20, k20 = {}, {}
for est in ("alto", "bajo"):
    s, t = entre(cs, *CAL), entre(c20, *CAL)
    r20[est] = (s.estrato == est).sum() / (t.estrato == est).sum()
    k20[est] = K[est] * r20[est]
print("Calibración %s a %s: S-NPP/NOAA-20 = %s -> k20 = %s" % (
    CAL[0][:4], CAL[1][:4], {e: round(v, 3) for e, v in r20.items()}, {e: round(v, 3) for e, v in k20.items()}))

# Validación con años reservados: NOAA-20 x k20 frente a S-NPP x k, por año y por mes de temporada.
w = lambda c, fac: c.estrato.map(fac).to_numpy()
anual = []
for a in range(int(VAL[0][:4]), int(VAL[1][:4]) + 1):
    s, t = entre(cs, f"{a}-01-01", f"{a}-12-31"), entre(c20, f"{a}-01-01", f"{a}-12-31")
    anual.append((a, round(float(w(s, K).sum()), 1), round(float(w(t, k20).sum()), 1)))
print("Validación anual (S-NPP x k, NOAA-20 x k20, razón):")
for a, x, y in anual:
    print("  %d: %7.1f %7.1f  %.2f" % (a, x, y, y / x))
vs, vt = entre(cs, *VAL), entre(c20, *VAL)
ms = vs.assign(v=w(vs, K)).groupby(vs["loc"].dt.to_period("M"))["v"].sum()
mt = vt.assign(v=w(vt, k20)).groupby(vt["loc"].dt.to_period("M"))["v"].sum()
mm = pd.concat([ms.rename("snpp"), mt.rename("n20")], axis=1).fillna(0)
ok = mm.snpp >= 15
mdape = float(np.median(np.abs(mm.n20 - mm.snpp)[ok] / mm.snpp[ok]))
print("Validación mensual %s-%s (meses con >= 15): error mediano %.0f %% en %d meses" % (
    VAL[0][:4], VAL[1][:4], 100 * mdape, int(ok.sum())))
# Comprobación con MODIS real en 2018-2019 (dentro de la ventana de k): NOAA-20 x k20 frente a celdas-día MODIS.
for a in (2018, 2019):
    t = entre(c20, f"{a}-01-01", f"{a}-12-31")
    m = cm[(cm["loc"].dt.year == a) & cm["loc"].isin(comunes)]
    print("  %d: MODIS real %d | NOAA-20 x k20 %.0f | razón %.2f" % (a, len(m), w(t, k20).sum(), w(t, k20).sum() / len(m)))

# --- 3. Filas nuevas de celda-día para los días sin S-NPP
cd = pd.read_csv(ent / CD_CSV, dtype=str, keep_default_na=False)
fo = pd.read_csv(ent / FO_CSV, dtype=str, keep_default_na=False)
v12 = cd[cd.fuente_serie == "VIIRS*k"]
alto = pd.to_numeric(v12.alt_m, errors="coerce") >= 2500
for est, mask in (("alto", alto), ("bajo", ~alto)):
    if not np.allclose(v12.loc[mask, "eq_hotspots"].astype(float).unique(), K[est]):
        sys.exit("ERROR: el k de %s en el CSV de entrada no es %.3f: ¿no es la v1.2?" % (est, K[est]))
hueco_txt = {x.strftime("%Y-%m-%d") for x in huecos}
if cd.fecha_local.isin(hueco_txt).any():
    sys.exit("ERROR: la entrada ya tiene celdas-día en días sin S-NPP: ¿ya está rellenada?")

f1 = lambda x: repr(round(float(x), 1))
f3 = lambda x: repr(round(float(x), 3))
alt_txt = lambda x: "" if pd.isna(x) else repr(float(x))
key = ["loc", "clat", "clon"]
mod_cd = cm.set_index(key)
nuevas, por_fuente = [], {}
for dia in huecos:
    if dia in con_n20:
        fuente, calidad, base = FUENTE_N20, "calibrado", c20[c20["loc"] == dia]
    else:
        fuente, calidad, base = FUENTE_MOD, "referencia", cm[cm["loc"] == dia]
    for r in base.itertuples(index=False):
        k_ = (r.loc, r.clat, r.clon)
        if fuente == FUENTE_N20:
            nm, fm = (mod_cd.at[k_, "n"], mod_cd.at[k_, "frp"]) if k_ in mod_cd.index else (0, 0.0)
            nv, fv, eq = r.n, r.frp, k20[r.estrato]
        else:
            nm, fm, nv, fv, eq = r.n, r.frp, 0, 0.0, 1.0
        nuevas.append({"fecha_local": dia.strftime("%Y-%m-%d"), "cell_lat": f3(r.clat), "cell_lon": f3(r.clon),
                       "alt_m": alt_txt(r.alt), "n_modis": repr(float(nm)), "n_viirs": repr(float(nv)),
                       "frp_modis": f1(fm), "frp_viirs": f1(fv), "eq_hotspots": f3(eq),
                       "fuente_serie": fuente, "calidad": calidad})
        por_fuente[fuente] = por_fuente.get(fuente, 0) + 1
nuevas = pd.DataFrame(nuevas, columns=cd.columns)
print("Celdas-día nuevas: %s | suma de peso nueva: %.2f" % (por_fuente, nuevas.eq_hotspots.astype(float).sum()))

# --- 4. Focos: NOAA-20 de los días rellenados con NOAA-20 y MODIS de los días rellenados con MODIS
peso = nuevas.set_index(["fecha_local", "cell_lat", "cell_lon"])[["eq_hotspots", "fuente_serie", "calidad"]]
n20_f = n20[n20["loc"].isin([x for x in huecos if x in con_n20])].copy()
n20_f["fecha_local"] = n20_f["loc"].dt.strftime("%Y-%m-%d")
n20_f["kc"] = list(zip(n20_f.fecha_local, n20_f.clat.map(f3), n20_f.clon.map(f3)))
cuenta = n20_f.groupby("kc")["frp"].transform("size")
filas_n20 = pd.DataFrame({
    "fecha_local": n20_f.fecha_local, "fecha_utc": n20_f.acq_date, "hora_utc": n20_f.hora_utc,
    "latitude": n20_f.lat.map(repr), "longitude": n20_f.lon.map(repr),
    "cell_lat": n20_f.clat.map(f3), "cell_lon": n20_f.clon.map(f3), "alt_m": n20_f.alt.map(alt_txt),
    "sensor": "VIIRS", "satelite": "NOAA-20", "frp": n20_f.frp.astype(float).map(repr),
    "brillo_k": n20_f.bright_ti4.astype(float).map(repr), "confianza": n20_f.confidence,
    "diurno_nocturno": n20_f.daynight, "fuente_serie": FUENTE_N20, "calidad": "calibrado", "en_serie": "1",
    "eq_foco": [repr(round(float(peso.loc[k, "eq_hotspots"]) / c, 4)) for k, c in zip(n20_f.kc, cuenta)],
}, columns=fo.columns)

# Días rellenados con MODIS: sus focos MODIS ya están en la v1.2 como fuera de serie; pasan a llevar el peso.
dias_mod = {x.strftime("%Y-%m-%d") for x in huecos if x not in con_n20}
sel = fo.fecha_local.isin(dias_mod) & (fo.sensor == "MODIS")
if sel.any():
    kc = list(zip(fo.loc[sel, "fecha_local"], fo.loc[sel, "cell_lat"], fo.loc[sel, "cell_lon"]))
    n = Counter(kc)
    fo.loc[sel, "fuente_serie"], fo.loc[sel, "calidad"], fo.loc[sel, "en_serie"] = FUENTE_MOD, "referencia", "1"
    fo.loc[sel, "eq_foco"] = [repr(round(1.0 / n[x], 4)) for x in kc]

cd2 = pd.concat([cd, nuevas], ignore_index=True)
cd2 = cd2.iloc[np.lexsort((cd2.cell_lon.astype(float), cd2.cell_lat.astype(float), cd2.fecha_local))]
fo2 = pd.concat([fo, filas_n20], ignore_index=True)
fo2 = fo2.iloc[np.lexsort((fo2.longitude.astype(float), fo2.latitude.astype(float), fo2.fecha_local))]
cd2.to_csv(out / CD_CSV, index=False, lineterminator="\r\n")
fo2.to_csv(out / FO_CSV, index=False, lineterminator="\r\n")

s1, s2 = cd.eq_hotspots.astype(float).sum(), cd2.eq_hotspots.astype(float).sum()
print("Celda-día: %d -> %d filas | suma eq_hotspots %.2f -> %.2f" % (len(cd), len(cd2), s1, s2))
print("Focos: %d -> %d filas (NOAA-20 nuevos: %d) | suma eq_foco %.2f" % (
    len(fo), len(fo2), len(filas_n20), fo2.eq_foco.astype(float).sum()))
mes = lambda df: df.assign(m=df.fecha_local.str[:7]).groupby("m").eq_hotspots.apply(lambda v: v.astype(float).sum())
m1, m2 = mes(cd), mes(cd2)
cambio = (m2 - m1.reindex(m2.index).fillna(0)).round(1)
print("Meses que cambian (v1.2 -> v1.3):")
for m_ in cambio[cambio.abs() > 0.05].index:
    print("  %s: %6.1f -> %6.1f" % (m_, m1.get(m_, 0.0), m2[m_]))
json.dump({"k20": {e: round(v, 3) for e, v in k20.items()}, "razon_snpp_n20": {e: round(v, 3) for e, v in r20.items()},
           "dias_sin_snpp": sorted(hueco_txt), "dias_con_modis": sorted(dias_mod),
           "validacion_anual": anual, "mdape_mensual": round(mdape, 3)},
          open(out / "relleno_n20_resumen.json", "w"), indent=1)

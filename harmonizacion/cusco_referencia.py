"""Límite del departamento de Cusco (FAO GAUL) y grilla de altitud SRTM a 0.01°.

Salida: cusco_ref/limite.json, cusco_ref/elev.npy, cusco_ref/meta.json
"""
import json
import os

import ee
import numpy as np

ee.Initialize(project=os.environ.get("EE_PROJECT"))      # define EE_PROJECT con tu proyecto de Earth Engine
salida = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cusco_ref")
os.makedirs(salida, exist_ok=True)

gaul = ee.FeatureCollection("FAO/GAUL_SIMPLIFIED_500m/2015/level1").filter(ee.Filter.eq("ADM0_NAME", "Peru"))
nombres = sorted(gaul.aggregate_array("ADM1_NAME").getInfo())
print("ADM1 de Perú:", nombres)
cusco = gaul.filter(ee.Filter.stringContains("ADM1_NAME", "Cu")).filter(ee.Filter.neq("ADM1_NAME", "Callao"))
print("Candidatos:", cusco.aggregate_array("ADM1_NAME").getInfo())
cusco = gaul.filter(ee.Filter.inList("ADM1_NAME", ["Cusco", "Cuzco"])).first()
geom = ee.Feature(cusco).geometry()
info = geom.getInfo()
json.dump(info, open(os.path.join(salida, "limite.json"), "w"))
b = geom.bounds().getInfo()["coordinates"][0]
lons, lats = [p[0] for p in b], [p[1] for p in b]
lon0, lon1, lat0, lat1 = min(lons), max(lons), min(lats), max(lats)
print("bbox: lon %.3f..%.3f  lat %.3f..%.3f" % (lon0, lon1, lat0, lat1))
print("área km²:", round(geom.area().getInfo() / 1e6))

PASO = 0.01
nx, ny = int(np.ceil((lon1 - lon0) / PASO)), int(np.ceil((lat1 - lat0) / PASO))
print("grilla de elevación: %d x %d = %d px" % (nx, ny, nx * ny))
srtm = (ee.Image("USGS/SRTMGL1_003").select("elevation")
        .reduceResolution(ee.Reducer.mean(), maxPixels=4096)
        .reproject(crs="EPSG:4326", crsTransform=[PASO, 0, lon0, 0, -PASO, lat1]))
reg = ee.Geometry.Rectangle([lon0, lat1 - ny * PASO, lon0 + nx * PASO, lat1], proj="EPSG:4326", geodesic=False)
arr = np.array(srtm.sampleRectangle(region=reg, defaultValue=-9999).get("elevation").getInfo(), dtype="float32")
print("elevación array:", arr.shape, "| rango %.0f..%.0f m" % (arr[arr > -9000].min(), arr.max()))
np.save(os.path.join(salida, "elev.npy"), arr)
json.dump({"lon0": lon0, "lat1": lat1, "paso": PASO, "nx": nx, "ny": ny},
          open(os.path.join(salida, "meta.json"), "w"))

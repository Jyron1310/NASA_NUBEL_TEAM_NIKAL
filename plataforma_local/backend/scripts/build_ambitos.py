"""Ámbitos de Cusco para la tipificación y los informes: provincias, distritos y cuencas.

Uso (desde plataforma_local/backend):
    python scripts/build_ambitos.py <carpeta_limites> <carpeta_hydrobasins>

- <carpeta_limites>: ``peru_provincial_simple.geojson`` y ``peru_distrital_simple.geojson`` de
  https://github.com/juaneladio/peru-geojson (límites de INEI con código de ubigeo).
- <carpeta_hydrobasins>: ``hybas_sa_lev01_v1c.zip`` ... ``hybas_sa_lev12_v1c.zip`` de HydroBASINS
  (HydroSHEDS, https://www.hydrosheds.org), con el código Pfafstetter de cada cuenca (PFAF_ID).

Salida: ``config/ambitos/<nivel>.geojson`` (provincia, distrito, pfaf_01 ... pfaf_12). Cada unidad
se recorta al límite de Cusco que usa la serie armonizada (``harmonizacion/cusco_ref/limite.json``,
FAO GAUL), porque solo hay datos dentro de ese límite; su área se mide sobre la parte recortada.
Necesita ``pyshp`` solo para este script.
"""

from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import shapefile  # pyshp: solo para leer HydroBASINS
from shapely import make_valid
from shapely.geometry import mapping, shape
from shapely.ops import unary_union

ROOT = Path(__file__).resolve().parents[1]  # plataforma_local/backend
REPO = ROOT.parents[1]
LIMITE = REPO / "harmonizacion" / "cusco_ref" / "limite.json"
OUT = ROOT / "config" / "ambitos"
SIMPLIFY = 0.0015  # grados (~150 m)
MIN_KM2 = 1.0  # se descartan restos menores

sys.path.insert(0, str(ROOT))
from firecal.regions import geodesic_area_km2  # noqa: E402


def cusco() -> object:
    lim = json.loads(LIMITE.read_text(encoding="utf-8"))
    geoms = lim["geometries"] if lim["type"] == "GeometryCollection" else [lim]
    # Igual que la serie: solo los anillos exteriores de los polígonos.
    polys = [
        shape({"type": "Polygon", "coordinates": [g["coordinates"][0]]})
        for g in geoms
        if g["type"] == "Polygon"
    ]
    return make_valid(unary_union(polys))


def recorte(geom, region):
    g = make_valid(geom).intersection(region)
    if g.is_empty:
        return None, 0.0
    area = geodesic_area_km2(g)
    if area < MIN_KM2:
        return None, 0.0
    return g.simplify(SIMPLIFY, preserve_topology=True), area


def guardar(nivel: str, titulo: str, fuente: str, feats: list[dict]) -> None:
    feats.sort(key=lambda f: f["properties"]["codigo"])
    OUT.mkdir(parents=True, exist_ok=True)
    data = {
        "type": "FeatureCollection",
        "nivel": nivel,
        "titulo": titulo,
        "fuente": fuente,
        "features": feats,
    }
    path = OUT / f"{nivel}.geojson"
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"{nivel}: {len(feats)} unidades, {path.stat().st_size / 1e6:.2f} MB")


def feature(geom, **props) -> dict:
    coords = json.loads(json.dumps(mapping(geom)), parse_float=lambda x: round(float(x), 5))
    return {"type": "Feature", "properties": props, "geometry": coords}


def inei(region, carpeta: Path) -> None:
    fuente_inei = (
        "INEI, vía https://github.com/juaneladio/peru-geojson (límites de referencia, no "
        "oficiales para fines legales)"
    )
    prov = json.loads((carpeta / "peru_provincial_simple.geojson").read_text(encoding="utf-8"))
    feats = []
    for f in prov["features"]:
        p = f["properties"]
        if p.get("FIRST_NOMB") != "CUSCO":
            continue
        g, area = recorte(shape(f["geometry"]), region)
        if g is not None:
            feats.append(
                feature(
                    g, codigo=p["FIRST_IDPR"], nombre=p["NOMBPROV"].title(), area_km2=round(area, 1)
                )
            )
    guardar("provincia", "Provincias de Cusco", fuente_inei, feats)

    dist = json.loads((carpeta / "peru_distrital_simple.geojson").read_text(encoding="utf-8"))
    feats = []
    for f in dist["features"]:
        p = f["properties"]
        if p.get("NOMBDEP") != "CUSCO":
            continue
        g, area = recorte(shape(f["geometry"]), region)
        if g is not None:
            feats.append(
                feature(
                    g,
                    codigo=p["IDDIST"],
                    nombre=p["NOMBDIST"].title(),
                    provincia=p["NOMBPROV"].title(),
                    area_km2=round(area, 1),
                )
            )
    guardar("distrito", "Distritos de Cusco", fuente_inei, feats)


def pfafstetter(region, carpeta: Path) -> None:
    fuente = (
        "HydroBASINS v1c (HydroSHEDS; Lehner y Grill, 2013), código Pfafstetter PFAF_ID. No son "
        "las "
        "unidades hidrográficas oficiales de la ANA"
    )
    x0, y0, x1, y1 = region.bounds
    for nivel in range(1, 13):
        zf = carpeta / f"hybas_sa_lev{nivel:02d}_v1c.zip"
        with zipfile.ZipFile(zf) as z:
            base = next(n[:-4] for n in z.namelist() if n.endswith(".shp"))
            r = shapefile.Reader(
                shp=z.open(base + ".shp"), dbf=z.open(base + ".dbf"), shx=z.open(base + ".shx")
            )
            campos = [c[0] for c in r.fields[1:]]
            feats = []
            for i, sh in enumerate(r.iterShapes()):
                bx0, by0, bx1, by1 = sh.bbox
                if bx1 < x0 or bx0 > x1 or by1 < y0 or by0 > y1:
                    continue
                rec = dict(zip(campos, r.record(i), strict=True))
                g, area = recorte(shape(sh.__geo_interface__), region)
                if g is None:
                    continue
                total = float(rec["SUB_AREA"])
                feats.append(
                    feature(
                        g,
                        codigo=str(rec["PFAF_ID"]),
                        nombre=f"Unidad Pfafstetter {rec['PFAF_ID']}",
                        hybas_id=int(rec["HYBAS_ID"]),
                        area_km2=round(area, 1),
                        fraccion_en_cusco=round(min(area / total, 1.0), 3) if total else None,
                    )
                )
        guardar(
            f"pfaf_{nivel:02d}",
            f"Cuencas Pfafstetter nivel {nivel} (dentro de Cusco)",
            fuente,
            feats,
        )


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    region = cusco()
    print(f"Cusco (FAO GAUL): {geodesic_area_km2(region):,.0f} km2")
    inei(region, Path(sys.argv[1]))
    pfafstetter(region, Path(sys.argv[2]))

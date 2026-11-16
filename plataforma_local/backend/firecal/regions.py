"""Regiones de trabajo (GeoJSON en ``config/regions/``) y utilidades geométricas.

Cada archivo ``<code>.geojson`` es una FeatureCollection; cada Feature es una región con
propiedades ``code``, ``name`` y ``level``. Geometrías en WGS84 (lon, lat).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import shapely
from pyproj import Geod, Transformer
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from firecal.settings import Settings

log = logging.getLogger(__name__)
_GEOD = Geod(ellps="WGS84")
M2_PER_KM2 = 1e6


@dataclass(frozen=True)
class Region:
    code: str
    name: str
    level: str
    geometry: BaseGeometry

    @property
    def area_km2(self) -> float:
        return geodesic_area_km2(self.geometry)


def geodesic_area_km2(geom: BaseGeometry) -> float:
    """Área geodésica (elipsoide WGS84) de una geometría en lon/lat."""
    area, _ = _GEOD.geometry_area_perimeter(geom)
    return abs(area) / M2_PER_KM2


def utm_epsg(lon: float, lat: float) -> int:
    """EPSG de la zona UTM WGS84 que contiene el punto (326xx norte, 327xx sur)."""
    zone = int((lon + 180) // 6) + 1
    return (32600 if lat >= 0 else 32700) + zone


def buffer_km(geom: BaseGeometry, km: float) -> BaseGeometry:
    """Buffer en kilómetros, calculado en la proyección UTM del centroide de la geometría."""
    if km == 0:
        return geom
    c = geom.centroid
    epsg = utm_epsg(c.x, c.y)
    fwd = Transformer.from_crs("EPSG:4326", f"EPSG:{epsg}", always_xy=True).transform
    inv = Transformer.from_crs(f"EPSG:{epsg}", "EPSG:4326", always_xy=True).transform
    projected = shapely.transform(geom, fwd, interleaved=False)
    return shapely.transform(projected.buffer(km * 1000.0), inv, interleaved=False)


def load_regions(regions_dir: Path) -> dict[str, Region]:
    """Lee todas las regiones de ``regions_dir``."""
    regions: dict[str, Region] = {}
    for path in sorted(regions_dir.glob("*.geojson")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for feat in data.get("features", []):
            props = feat.get("properties", {})
            code = props.get("code")
            if not code:
                log.warning("Region sin 'code' en %s; se ignora", path.name)
                continue
            geom = shape(feat["geometry"])
            if not geom.is_valid:
                raise ValueError(f"Geometria invalida en la region {code} ({path.name})")
            regions[code] = Region(code, props.get("name", code), props.get("level", ""), geom)
    return regions


@lru_cache(maxsize=4)
def _cached_regions(regions_dir: str) -> dict[str, Region]:
    return load_regions(Path(regions_dir))


def get_region(settings: Settings, code: str | None = None) -> Region:
    """Región por código (por defecto ``FIRECAL_REGION``)."""
    code = code or settings.env.region
    regions = _cached_regions(str(settings.paths.regions_dir))
    if code not in regions:
        raise KeyError(
            f"No existe la region '{code}' en {settings.paths.regions_dir}. "
            f"Disponibles: {sorted(regions)}"
        )
    return regions[code]

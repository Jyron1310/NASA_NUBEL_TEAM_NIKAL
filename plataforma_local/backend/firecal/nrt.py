"""Detecciones casi en tiempo real (NRT) de NASA FIRMS en Cusco.

Es una capa APARTE de la serie armonizada (METHODOLOGY.md): son detecciones crudas de los últimos
días, sin armonizar ni ponderar, y nunca se suman al calendario. No se usa FRP (regla del equipo);
tampoco se habla de "alerta" ni de "riesgo": se muestra qué detectaron los satélites.

- **Fuente:** API "area" de FIRMS (``/api/area/csv/<MAP_KEY>/<SOURCE>/<O,S,E,N>/<días>``) con las
  cuatro fuentes NRT: VIIRS S-NPP, NOAA-20, NOAA-21 y MODIS (Terra y Aqua).
- **Clave:** ``FIRMS_MAP_KEY`` (variable de entorno). Solo vive en el servidor: nunca se envía al
  navegador ni aparece en logs o mensajes de error (la URL con la clave no se registra).
- **Cuota:** se piden siempre 5 días de las 4 fuentes y se guardan ``refresh_min`` minutos para
  todos: ~16 transacciones por hora frente al límite de FIRMS (5000 cada 10 minutos).
  Si FIRMS falla, se sigue mostrando lo último que se obtuvo, marcado como desactualizado.
"""

from __future__ import annotations

import csv
import io
import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import httpx
from shapely import contains_xy

from firecal.i18n import t
from firecal.logging_utils import RedactMapKeyFilter

log = logging.getLogger(__name__)

FIRMS_URL = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/{key}/{source}/{area}/{days}"
SOURCES = {                                  # fuente de la API -> (satélite, instrumento)
    "VIIRS_SNPP_NRT": ("Suomi NPP", "VIIRS"),
    "VIIRS_NOAA20_NRT": ("NOAA-20", "VIIRS"),
    "VIIRS_NOAA21_NRT": ("NOAA-21", "VIIRS"),
    "MODIS_NRT": ("Terra/Aqua", "MODIS"),
}
DAY_RANGE = 5                                # máximo que permite la API
HORAS_VALIDAS = (24, 48, 120)
LOCAL_UTC_OFFSET = timedelta(hours=-5)       # Perú (UTC-5, sin horario de verano)
MODIS_CONF = {"l": "baja", "n": "nominal", "h": "alta"}  # VIIRS ya trae l/n/h; MODIS 0-100


class NrtNotConfigured(RuntimeError):
    """No hay MAP_KEY: la capa en tiempo real está apagada."""


class NrtUnavailable(RuntimeError):
    """FIRMS no respondió y no hay nada guardado que mostrar."""


def _confianza(instrumento: str, valor: str) -> str:
    v = (valor or "").strip().lower()
    if instrumento == "MODIS":
        try:
            n = int(float(v))
        except ValueError:
            return "nominal"
        return "baja" if n < 30 else "alta" if n >= 80 else "nominal"
    return MODIS_CONF.get(v[:1], "nominal")


def parse_csv(text: str, source: str) -> list[dict]:
    """Filas de FIRMS -> detecciones (sin FRP ni brillo). Ignora filas incompletas."""
    satelite, instrumento = SOURCES[source]
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        try:
            lat, lon = float(row["latitude"]), float(row["longitude"])
            hhmm = f"{int(row['acq_time']):04d}"
            utc = datetime.strptime(f"{row['acq_date']} {hhmm}", "%Y-%m-%d %H%M").replace(
                tzinfo=UTC)
        except (KeyError, TypeError, ValueError):
            continue
        out.append({"lat": lat, "lon": lon, "utc": utc, "satelite": satelite,
                    "instrumento": instrumento,
                    "confianza": _confianza(instrumento, row.get("confidence", "")),
                    "dia_noche": "día" if row.get("daynight", "").upper() == "D" else "noche"})
    return out


@dataclass
class _Snapshot:
    detecciones: list[dict] = field(default_factory=list)
    obtenido: datetime | None = None
    fuentes_ok: list[str] = field(default_factory=list)
    fuentes_error: list[str] = field(default_factory=list)


class NrtStore:
    """Detecciones NRT de Cusco, guardadas ``refresh_min`` minutos y compartidas por todos."""

    def __init__(self, map_key: str | None, region_geom, refresh_min: float = 15.0,
                 timeout_s: float = 10.0, client: httpx.Client | None = None) -> None:
        self._key = map_key
        self._geom = region_geom
        self._refresh_s = refresh_min * 60
        self._timeout = timeout_s
        self._client = client
        self._lock = threading.Lock()
        self._snap = _Snapshot()
        self._t_ok = 0.0
        if map_key:
            _redact_httpx(map_key)

    @property
    def configured(self) -> bool:
        return bool(self._key)

    def _area(self) -> str:
        w, s, e, n = self._geom.bounds
        return f"{w - 0.05:.3f},{s - 0.05:.3f},{e + 0.05:.3f},{n + 0.05:.3f}"

    def _fetch(self) -> _Snapshot:
        snap = _Snapshot(obtenido=datetime.now(UTC))
        client = self._client or httpx.Client(timeout=self._timeout)
        try:
            for source in SOURCES:
                url = FIRMS_URL.format(key=self._key, source=source, area=self._area(),
                                       days=DAY_RANGE)
                try:
                    r = client.get(url)
                    text = r.text
                    # FIRMS responde 200 con un texto de error si la clave es inválida o se
                    # agotó la cuota: se reconoce porque no trae la cabecera del CSV.
                    if r.status_code != 200 or not text.startswith("latitude"):
                        raise ValueError(f"HTTP {r.status_code}")
                except (httpx.HTTPError, ValueError) as exc:
                    # Nunca registrar la URL ni el texto de la excepción: llevan la clave.
                    log.warning("FIRMS NRT %s no disponible (%s)", source, type(exc).__name__)
                    snap.fuentes_error.append(source)
                    continue
                filas = parse_csv(text, source)
                snap.detecciones += [f for f in filas
                                     if contains_xy(self._geom, f["lon"], f["lat"])]
                snap.fuentes_ok.append(source)
        finally:
            if self._client is None:
                client.close()
        return snap

    def snapshot(self) -> tuple[_Snapshot, bool]:
        """(datos, desactualizado). Refresca si pasaron ``refresh_min``; un solo hilo pide."""
        if not self._key:
            raise NrtNotConfigured(t(
                es="El tiempo real no está configurado en este servidor (falta la MAP_KEY de "
                   "NASA FIRMS).",
                en="Near real-time data is not configured on this server (the NASA FIRMS "
                   "MAP_KEY is missing)."))
        if time.monotonic() - self._t_ok < self._refresh_s and self._snap.obtenido is not None:
            return self._snap, False
        # Hay que refrescar. Si ya hay datos y otro hilo está pidiendo a FIRMS, no se espera:
        # se devuelve lo anterior (los visitantes no quedan bloqueados por la red de FIRMS).
        if not self._lock.acquire(blocking=self._snap.obtenido is None):
            return self._snap, False
        try:
            if time.monotonic() - self._t_ok < self._refresh_s and self._snap.obtenido is not None:
                return self._snap, False             # otro hilo ya refrescó mientras se esperaba
            nuevo = self._fetch()
            if nuevo.fuentes_ok:                     # al menos una fuente respondió
                self._snap, self._t_ok = nuevo, time.monotonic()
                return self._snap, False
            if self._snap.obtenido is None:
                raise NrtUnavailable(t(
                    es="NASA FIRMS no respondió. Intenta de nuevo en unos minutos.",
                    en="NASA FIRMS did not respond. Try again in a few minutes."))
            self._t_ok = time.monotonic() - self._refresh_s + 120       # reintento en 2 min
            return self._snap, True                  # se mantiene lo anterior, marcado
        finally:
            self._lock.release()

    def geojson(self, horas: int) -> dict:
        snap, viejo = self.snapshot()
        ahora = datetime.now(UTC)
        desde = ahora - timedelta(hours=horas)
        feats = []
        for d in sorted(snap.detecciones, key=lambda x: x["utc"], reverse=True):
            if d["utc"] < desde:
                continue
            local = d["utc"] + LOCAL_UTC_OFFSET
            feats.append({"type": "Feature",
                          "geometry": {"type": "Point", "coordinates": [d["lon"], d["lat"]]},
                          "properties": {
                              "fecha_hora_utc": d["utc"].strftime("%Y-%m-%dT%H:%MZ"),
                              "fecha_hora_local": local.strftime("%Y-%m-%d %H:%M"),
                              "horas_atras": round((ahora - d["utc"]).total_seconds() / 3600, 1),
                              "satelite": d["satelite"], "instrumento": d["instrumento"],
                              "confianza": d["confianza"], "dia_noche": d["dia_noche"]}})
        ultima = feats[0]["properties"]["fecha_hora_local"] if feats else None
        return {
            "type": "FeatureCollection", "features": feats,
            "metadata": {
                "horas": horas, "detecciones": len(feats), "ultima_deteccion_local": ultima,
                "actualizado_utc": snap.obtenido.strftime("%Y-%m-%dT%H:%MZ"),
                "proxima_actualizacion_min": round(self._refresh_s / 60),
                # Desactualizado: FIRMS falló en el último intento o los datos tienen más del
                # doble del intervalo de refresco.
                "desactualizado": viejo or (ahora - snap.obtenido).total_seconds()
                                  > 2 * self._refresh_s,
                "fuentes": [f"{SOURCES[s][1]} {SOURCES[s][0]}" for s in snap.fuentes_ok],
                "fuentes_sin_respuesta": [f"{SOURCES[s][1]} {SOURCES[s][0]}"
                                          for s in snap.fuentes_error],
                "notes": [
                    t(es="Detecciones satelitales de los últimos días, SIN armonizar: cada punto "
                         "es una detección (VIIRS ve más que MODIS) y no se suman a la serie "
                         "histórica de focos armonizados.",
                      en="Satellite detections from the last few days, NOT harmonized: each point "
                         "is one detection (VIIRS sees more than MODIS) and they are not added to "
                         "the historical series of harmonized hotspots."),
                    t(es="Un foco de calor no es un incendio confirmado. Los datos llegan con "
                         "unas horas de retraso tras el paso del satélite.",
                      en="A hotspot is not a confirmed wildfire. Data arrive a few hours after "
                         "the satellite overpass."),
                    t(es="Fuente: NASA FIRMS (VIIRS y MODIS, tiempo casi real). Hora local de "
                         "Perú (UTC-5).",
                      en="Source: NASA FIRMS (VIIRS and MODIS, near real-time). Peru local time "
                         "(UTC-5)."),
                ]},
        }


def _redact_httpx(key: str) -> None:
    """httpx registra cada solicitud con la URL completa (que lleva la MAP_KEY): se redacta en
    su propio logger, así no depende de cómo se arranque el servidor (uvicorn o firecal serve)."""
    lg = logging.getLogger("httpx")
    if not any(isinstance(f, RedactMapKeyFilter) for f in lg.filters):
        lg.addFilter(RedactMapKeyFilter(key))

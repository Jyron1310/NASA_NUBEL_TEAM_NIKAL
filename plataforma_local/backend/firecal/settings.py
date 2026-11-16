"""Configuración central de Nikal.

Dos fuentes:
- Variables de entorno / archivo ``.env`` (modo de datos, MAP_KEY, región, rutas): ``EnvSettings``.
- ``config/settings.yaml`` (parámetros científicos): ``ScientificParams``.

``get_settings()`` devuelve ambas combinadas y en caché. Todas las rutas se resuelven con
``pathlib`` a partir de la raíz del proyecto (o de ``FIRECAL_HOME``), nunca con rutas absolutas.
"""

from __future__ import annotations

from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DataMode = Literal["synthetic", "real"]
ConfidenceCat = Literal["low", "nominal", "high"]

_YEAR_MONTH_PATTERN = r"^\d{4}-(0[1-9]|1[0-2])$"


# --------------------------------------------------------------------------------------
# Parámetros científicos (config/settings.yaml)
# --------------------------------------------------------------------------------------
class _Strict(BaseModel):
    """Base que rechaza claves desconocidas, para detectar errores de tipeo en el YAML."""

    model_config = ConfigDict(extra="forbid", frozen=True)


def _check_range(v: tuple[float, float]) -> tuple[float, float]:
    if v[0] > v[1]:
        raise ValueError(f"rango invalido [min, max]: {v}")
    return v


def _check_12(v: list[float]) -> list[float]:
    if len(v) != 12:
        raise ValueError(f"se esperan 12 valores (ene..dic), llegaron {len(v)}")
    return v


class RegionParams(_Strict):
    name: str
    bbox: tuple[float, float, float, float] = Field(description="[oeste, sur, este, norte] WGS84")
    buffer_km: float = Field(ge=0)

    @field_validator("bbox")
    @classmethod
    def _check_bbox(cls, v: tuple[float, float, float, float]):
        w, s, e, n = v
        if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
            raise ValueError(f"bbox invalido (se espera [oeste, sur, este, norte]): {v}")
        return v


class GridParams(_Strict):
    h3_res_store: int = Field(ge=0, le=15)
    h3_res_calibration_parent: int = Field(ge=0, le=15)
    px1km_deg: float = Field(gt=0)


class FilterParams(_Strict):
    min_confidence: ConfidenceCat
    static_source_month_fraction: float = Field(gt=0, le=1)
    modis_confidence_bins: tuple[int, int]
    bowtie_max_km: float = Field(gt=0)

    _ranges = field_validator("modis_confidence_bins")(_check_range)


SatelliteName = Literal["TERRA", "AQUA", "SNPP", "N20", "N21"]


class HarmonizationParams(_Strict):
    reference: str
    calib_window: tuple[date, date]
    n20_snpp_window: tuple[date, date]
    holdout_years: list[int]
    aqua_observed_until: str = Field(pattern=_YEAR_MONTH_PATTERN)
    series_start: str = Field(pattern=_YEAR_MONTH_PATTERN)
    bootstrap_reps: int = Field(gt=0)
    bootstrap_seed: int
    dry_season_months: list[int]
    data_version: str
    h3_res_calibration_mid: int = Field(ge=0, le=15)
    terra_aqua_window: tuple[date, date]
    n21_snpp_window: tuple[date, date]
    stratum_min_ref_focos: int = Field(ge=0)
    stratum_min_years: int = Field(ge=1)
    band_quantiles: tuple[float, float]
    band_min_coverage: float = Field(gt=0, le=1)
    band_target_coverage: tuple[float, float]
    band_log_offset: float = Field(gt=0)
    band_error_pred_edges: list[float]
    band_error_min_n: int = Field(ge=1)
    validation_min_focos_unit: int = Field(ge=0)
    satellite_periods: dict[SatelliteName, tuple[date, date | None]]

    _ranges = field_validator("band_quantiles", "band_target_coverage")(_check_range)

    @field_validator("band_error_pred_edges")
    @classmethod
    def _check_edges(cls, v: list[float]):
        if not v or v[0] != 0 or any(b <= a for a, b in zip(v, v[1:], strict=False)):
            raise ValueError(f"band_error_pred_edges debe empezar en 0 y ser creciente: {v}")
        return v

    @field_validator("dry_season_months")
    @classmethod
    def _check_months(cls, v: list[int]):
        if any(m < 1 or m > 12 for m in v):
            raise ValueError(f"dry_season_months debe contener meses 1-12: {v}")
        return v


class ClimatologyParams(_Strict):
    base_years: tuple[int, int]
    percentile_min_years: int = Field(ge=1)
    category_percentiles: tuple[float, float, float, float]


class ReliabilityParams(_Strict):
    expected_annual_low: float = Field(ge=0)
    expected_annual_high: float = Field(ge=0)
    report_edges: list[float]

    @model_validator(mode="after")
    def _check_order(self):
        if self.expected_annual_low > self.expected_annual_high:
            raise ValueError("reliability: expected_annual_low debe ser <= expected_annual_high")
        return self


class RateLimitParams(_Strict):
    """Protocolo de solicitudes (api.limits): cubeta de fichas por cliente + semáforo de pesadas."""

    enabled: bool = True
    # Los cupos son por IP y una sala entera (wifi, oficina) sale por la misma IP pública: están
    # pensados para ~60 personas detrás de una IP. Las respuestas servidas desde la caché
    # (api.cache) no gastan cupo; solo cuenta lo que hay que calcular.
    requests_per_minute: float = Field(default=600, gt=0)   # recarga de la cubeta general
    burst: int = Field(default=120, gt=0)                    # tamaño de la cubeta general
    heavy_per_minute: float = Field(default=60, gt=0)       # CSV y consultas costosas
    heavy_burst: int = Field(default=20, gt=0)
    max_concurrent_heavy: int = Field(default=4, gt=0)      # pesadas en paralelo (todo el proceso)
    queue_timeout_s: float = Field(default=8.0, ge=0)       # espera máxima por un turno
    max_queue: int = Field(default=16, ge=0)                # pesadas en espera; más -> 503 ya
    trust_proxy_headers: bool = False                       # X-Forwarded-For (solo tras proxy)
    proxy_hops: int = Field(default=1, ge=1)                # proxies de confianza delante
    max_clients: int = Field(default=10000, gt=0)           # clientes recordados en memoria


class ResponseCacheParams(_Strict):
    """Caché de respuestas completas de Cusco entero (api.cache)."""

    enabled: bool = True
    max_items: int = Field(default=3000, gt=0)              # ~1.300 respuestas distintas x idioma
    max_mb: float = Field(default=64, gt=0)                 # memoria máxima (ya comprimidas)


class ApiParams(_Strict):
    max_aoi_km2: float = Field(gt=0)
    max_csv_years: int = Field(gt=0)
    cors_origins: list[str]
    max_point_radius_km: float = Field(gt=0)
    max_geojson_features: int = Field(gt=0)
    csv_chunk_rows: int = Field(gt=0)
    region_simplify_deg: float = Field(ge=0)
    max_csv_rows: int = Field(default=200000, gt=0)         # filas máximas por descarga CSV
    default_lang: str = Field(default="en", pattern="^(en|es)$")  # idioma si no llega ?lang=
    rate_limit: RateLimitParams = RateLimitParams()
    response_cache: ResponseCacheParams = ResponseCacheParams()


class SynthLandscape(_Strict):
    n_hot_zones: tuple[int, int]
    zone_sigma_deg: tuple[float, float]
    zone_amplitude: tuple[float, float]
    background_weight: float = Field(ge=0)

    _ranges = field_validator("n_hot_zones", "zone_sigma_deg", "zone_amplitude")(_check_range)


class SynthEvents(_Strict):
    base_per_month: float = Field(gt=0)
    seasonality: list[float]
    annual_sigma: float = Field(ge=0)
    n_extreme_years: tuple[int, int]
    extreme_multiplier: tuple[float, float]
    trend_per_year: float
    size_ha_median: float = Field(gt=0)
    size_ha_sigma: float = Field(gt=0)
    size_ha_max: float = Field(gt=0)
    duration_coef: float = Field(ge=0)
    duration_ref_ha: float = Field(gt=0)
    daily_area_sigma: float = Field(ge=0)
    location_jitter_km: float = Field(ge=0)

    _ranges = field_validator("n_extreme_years", "extreme_multiplier")(_check_range)
    _months = field_validator("seasonality")(_check_12)


class SynthDiurnal(_Strict):
    peak_hour: float = Field(ge=0, lt=24)
    min_factor: float = Field(gt=0, le=1)
    sharpness: float = Field(gt=0)


class SynthSensor(_Strict):
    pixel_ha: float = Field(gt=0)
    s50_ha: float = Field(gt=0)
    slope: float = Field(gt=0)
    coverage: float = Field(gt=0, le=1)
    geoloc_sigma_km: float = Field(ge=0)


class SynthSatellite(_Strict):
    sensor: Literal["MODIS", "VIIRS"]
    code: str
    start: date
    end: date | None = None
    overpass_day: float = Field(ge=0, lt=24, description="hora local aproximada")
    overpass_night: float = Field(ge=0, lt=24, description="hora local aproximada")




class SynthIndustrial(_Strict):
    n_sources: tuple[int, int]
    pass_detect_prob: float = Field(gt=0, le=1)

    _ranges = field_validator("n_sources")(_check_range)


class SyntheticParams(_Strict):
    seed: int
    scale: float = Field(gt=0)
    start: date
    end: date | None = Field(default=None, description="None = hoy en la zona horaria del proyecto")
    nrt_days: int = Field(ge=0)
    landscape: SynthLandscape
    events: SynthEvents
    diurnal: SynthDiurnal
    cloud_prob_by_month: list[float]
    sensors: dict[Literal["MODIS", "VIIRS"], SynthSensor]
    satellites: dict[Literal["TERRA", "AQUA", "SNPP", "N20", "N21"], SynthSatellite]
    overpass_jitter_h: float = Field(ge=0)
    overpass_drift: dict[Literal["TERRA", "AQUA", "SNPP", "N20", "N21"], list[tuple[date, float]]]
    industrial: SynthIndustrial
    bowtie_fraction: float = Field(ge=0, lt=1)
    bowtie_offset_km: tuple[float, float]

    _months = field_validator("cloud_prob_by_month")(_check_12)
    _ranges = field_validator("bowtie_offset_km")(_check_range)

    @model_validator(mode="after")
    def _check_drift_nodes(self):
        for sat, nodes in self.overpass_drift.items():
            dates = [d for d, _ in nodes]
            if not nodes or dates != sorted(dates):
                raise ValueError(f"overpass_drift.{sat}: nodos vacios o fechas desordenadas")
            nominal = self.satellites[sat].overpass_day
            if abs(nodes[0][1] - nominal) > 1e-6:
                raise ValueError(
                    f"overpass_drift.{sat}: el primer nodo ({nodes[0][1]}) debe ser igual a "
                    f"overpass_day ({nominal}) para que no haya un salto"
                )
        return self


class ScientificParams(_Strict):
    region: RegionParams
    timezone: str
    grid: GridParams
    filters: FilterParams
    harmonization: HarmonizationParams
    climatology: ClimatologyParams
    reliability: ReliabilityParams
    api: ApiParams
    synthetic: SyntheticParams


def load_params(path: Path) -> ScientificParams:
    """Lee y valida el YAML de parámetros científicos."""
    if not path.is_file():
        raise FileNotFoundError(f"No existe el archivo de parametros: {path}")
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return ScientificParams.model_validate(raw)


# --------------------------------------------------------------------------------------
# Entorno (.env)
# --------------------------------------------------------------------------------------
class EnvSettings(BaseSettings):
    """Variables de entorno. Se leen de ``.env`` en la raíz del proyecto si existe."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_mode: DataMode = Field(default="synthetic", validation_alias="FIRECAL_DATA_MODE")
    firms_map_key: SecretStr | None = Field(default=None, validation_alias="FIRMS_MAP_KEY")
    region: str = Field(default="peru_sur", validation_alias="FIRECAL_REGION")
    # Orígenes extra permitidos por CORS, separados por comas (p. ej. el frontend publicado en
    # Vercel). Se suman a api.cors_origins de settings.yaml. Idea de antonio/backend-modelo.
    cors_origins: str = Field(default="", validation_alias="FIRECAL_CORS_ORIGINS")
    home: Path = Field(default=PROJECT_ROOT, validation_alias="FIRECAL_HOME")
    config_file: Path | None = Field(default=None, validation_alias="FIRECAL_CONFIG")
    log_level: str = Field(default="INFO", validation_alias="FIRECAL_LOG_LEVEL")
    api_host: str = Field(default="127.0.0.1", validation_alias="FIRECAL_API_HOST")
    api_port: int = Field(default=8000, validation_alias="FIRECAL_API_PORT")

    @field_validator("firms_map_key", mode="before")
    @classmethod
    def _empty_key_is_none(cls, v):
        return None if v in ("", None) else v


# --------------------------------------------------------------------------------------
# Rutas y objeto combinado
# --------------------------------------------------------------------------------------
class Paths(BaseModel):
    """Rutas del proyecto, todas derivadas de ``home``."""

    model_config = ConfigDict(frozen=True)

    home: Path

    @property
    def config_dir(self) -> Path:
        return self.home / "config"

    @property
    def regions_dir(self) -> Path:
        return self.config_dir / "regions"

    @property
    def data_dir(self) -> Path:
        return self.home / "data"

    @property
    def raw_firms_dir(self) -> Path:
        return self.data_dir / "raw" / "firms"

    @property
    def nrt_dir(self) -> Path:
        return self.raw_firms_dir / "nrt"

    @property
    def covariates_dir(self) -> Path:
        return self.data_dir / "raw" / "covariates"

    @property
    def synthetic_dir(self) -> Path:
        return self.data_dir / "synthetic"

    @property
    def interim_dir(self) -> Path:
        return self.data_dir / "interim"

    @property
    def processed_dir(self) -> Path:
        return self.data_dir / "processed"

    @property
    def duckdb_path(self) -> Path:
        return self.processed_dir / "firecal.duckdb"

    @property
    def cache_dir(self) -> Path:
        return self.processed_dir / "cache"

    @property
    def artifacts_dir(self) -> Path:
        return self.home / "models" / "artifacts"

    @property
    def reports_dir(self) -> Path:
        return self.home / "reports"


class Settings(BaseModel):
    """Configuración completa: entorno + parámetros científicos + rutas."""

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    env: EnvSettings
    params: ScientificParams
    paths: Paths

    @property
    def data_mode(self) -> DataMode:
        return self.env.data_mode

    @property
    def input_dir(self) -> Path:
        """Carpeta de CSV de entrada según el modo (FIRMS real o simulador)."""
        if self.data_mode == "synthetic":
            return self.paths.synthetic_dir
        return self.paths.raw_firms_dir


def build_settings(env: EnvSettings | None = None) -> Settings:
    """Construye la configuración sin caché (útil en tests)."""
    env = env or EnvSettings()
    home = env.home.resolve()
    config_file = env.config_file or (home / "config" / "settings.yaml")
    return Settings(env=env, params=load_params(config_file), paths=Paths(home=home))


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Configuración global en caché. Usa ``get_settings.cache_clear()`` para recargar."""
    return build_settings()

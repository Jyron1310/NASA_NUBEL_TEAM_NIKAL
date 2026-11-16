"""Aplicación FastAPI de Nikal Cusco: idioma, límites, caché, rutas /api y la interfaz."""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from api.cache import ResponseCacheMiddleware, ResponseCacheStore
from api.limits import HeavyGate, RateLimiter
from api.routers import ambitos, informe, plan
from firecal import __version__
from firecal.i18n import reset_lang, set_lang, t
from firecal.plan.query import PlanNotReady, PlanStore
from firecal.settings import PROJECT_ROOT, Settings, get_settings

log = logging.getLogger(__name__)


class HealthResponse(BaseModel):
    status: str
    data_mode: str
    data_ready: bool
# Frontend (React + MapLibre, base de Dante) ya compilado con `npm run build` en frontend/dist.
# FIRECAL_FRONTEND_DIR lo cambia (p. ej. en Docker); vacío = no servir.
DEFAULT_FRONTEND = PROJECT_ROOT.parent / "frontend" / "dist"


class UTF8JSONResponse(JSONResponse):
    """JSON con charset explícito (PowerShell 5.1 asume Latin-1 si no se declara)."""

    media_type = "application/json; charset=utf-8"


def cache_control(request: Request, status: int) -> str:
    """Caché del navegador y de proxies. Los datos son históricos (no cambian entre despliegues de
    datos), así que las respuestas 200 de /api se pueden reutilizar 1 hora; errores, límites y
    /health, nunca. Los archivos de la interfaz con hash en el nombre (/assets/) duran 1 año."""
    path = request.url.path
    if request.method != "GET" or status != 200 or path.startswith("/health"):
        return "no-store"
    if path == "/api/tiempo-real":
        return "public, max-age=300"                    # se refresca cada 15 min en el servidor
    if path.startswith("/api/"):
        return "public, max-age=3600"
    if path.startswith("/assets/"):
        return "public, max-age=31536000, immutable"
    return "no-cache"                                   # index.html: siempre revalidar


def _validation_msg(e: dict) -> str:
    """Mensaje de validación de FastAPI en el idioma de la persona (QA de Erik, 11)."""
    kind, ctx = e.get("type", ""), e.get("ctx") or {}
    if kind == "missing":
        return t(es="falta este parámetro", en="this parameter is required")
    if kind in ("float_parsing", "float_type", "finite_number"):
        return t(es="debe ser un número", en="must be a number")
    if kind in ("int_parsing", "int_type", "int_from_float"):
        return t(es="debe ser un número entero", en="must be a whole number")
    if kind in ("bool_parsing", "bool_type"):
        return t(es="debe ser true o false", en="must be true or false")
    for key, es, en in (("ge", "mayor o igual que", "greater than or equal to"),
                        ("gt", "mayor que", "greater than"),
                        ("le", "menor o igual que", "less than or equal to"),
                        ("lt", "menor que", "less than")):
        if key in ctx:
            return t(es=f"debe ser {es} {ctx[key]}", en=f"must be {en} {ctx[key]}")
    if "max_length" in ctx:
        return t(es=f"admite como máximo {ctx['max_length']} caracteres",
                 en=f"at most {ctx['max_length']} characters")
    return t(es="valor no válido", en="invalid value")


def create_app(settings: Settings | None = None) -> FastAPI:
    """Crea la app. Recibe ``settings`` explícitos en tests; si no, usa los globales."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """Carga los datos al arrancar (no con el primer visitante): ~1,6 s y ~20 MB."""
        def preload() -> None:
            store: PlanStore = app.state.plan
            try:
                store.monthly(store.resolve_aoi("PE-CUS"))   # tablas en memoria + serie de Cusco
            except PlanNotReady:
                log.warning("Datos de Cusco sin cargar: corre 'firecal plan-events'.")
        await run_in_threadpool(preload)
        yield

    app = FastAPI(
        lifespan=lifespan,
        default_response_class=UTF8JSONResponse,
        title="Nikal Cusco API",
        version=__version__,
        description=(
            "Calendario armonizado de focos de calor MODIS + VIIRS para **Cusco** (2000-11 a "
            "2025-12), con datos reales de NASA FIRMS. Unidad: **focos armonizados** (celdas de "
            "~1 km con focos de calor por día, en escala MODIS). Detalles en `GET /api/metadatos`."
        ),
    )
    app.state.settings = settings
    app.state.plan = PlanStore(settings)
    rl = settings.params.api.rate_limit
    app.state.limiter = RateLimiter(rl)
    app.state.gate = HeavyGate(rl.max_concurrent_heavy, rl.queue_timeout_s, rl.max_queue)
    rc = settings.params.api.response_cache
    app.state.cache = ResponseCacheStore(rc.enabled, rc.max_items, int(rc.max_mb * 1024 * 1024),
                                         version=app.state.plan.data_version)

    @app.middleware("http")
    async def _timing_and_limits(request: Request, call_next):
        """Idioma (?lang=en|es), protocolo de solicitudes (429) y latencia en X-Process-Time-ms."""
        t0 = time.perf_counter()
        token = set_lang(request.query_params.get("lang"), settings.params.api.default_lang)
        try:
            rejected = app.state.limiter.check(request)
            response = rejected or await call_next(request)
        finally:
            reset_lang(token)
        response.headers["X-Process-Time-ms"] = f"{(time.perf_counter() - t0) * 1000:.1f}"
        remaining = getattr(request.state, "rate_remaining", None)
        if remaining is not None:
            response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers.setdefault("Cache-Control", cache_control(request, response.status_code))
        # Encabezados de seguridad básicos para una URL pública.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return response

    # Compresión: focos.geojson de un año pasa de ~1,6 MB a ~0,2 MB (auditoría de Gabriel).
    app.add_middleware(GZipMiddleware, minimum_size=1024)

    # Caché de respuestas de Cusco entero (api/cache.py). Va por fuera de la compresión y de los
    # límites (guarda la respuesta ya comprimida y una repetida no gasta cupo) y por dentro de
    # CORS (esas cabeceras dependen de quién pregunta).
    app.add_middleware(ResponseCacheMiddleware, store=app.state.cache)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[*settings.params.api.cors_origins,
                       *(o.strip() for o in settings.env.cors_origins.split(",") if o.strip())],
        allow_methods=["GET", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=["Content-Disposition", "X-Data-Mode", "X-Row-Count",
                        "X-Process-Time-ms", "X-RateLimit-Remaining", "Retry-After", "X-Cache"],
    )

    @app.exception_handler(RequestValidationError)
    def _validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"campo": ".".join(str(x) for x in e.get("loc", [])[1:]),
                   "error": _validation_msg(e)} for e in exc.errors()]
        return UTF8JSONResponse(status_code=422, content={
            "detail": t(es="Solicitud inválida: revisa los campos indicados en 'errors'.",
                        en="Invalid request: check the fields listed in 'errors'."),
            "errors": errors})

    @app.get("/health", response_model=HealthResponse, tags=["meta"])
    def health() -> HealthResponse:
        """Estado del servicio: si los datos de Cusco están cargados."""
        plan_store: PlanStore = app.state.plan
        return HealthResponse(status="ok", data_mode="real", data_ready=plan_store.ready)

    @app.get("/health/limits", tags=["meta"])
    def health_limits() -> dict:
        """Estado del protocolo de solicitudes: clientes, rechazos 429/503, pesadas y caché."""
        return {**app.state.limiter.stats(), **app.state.gate.stats(), **app.state.cache.stats()}

    app.include_router(plan.router)
    app.include_router(ambitos.router)
    app.include_router(informe.router)

    frontend = Path(os.environ.get("FIRECAL_FRONTEND_DIR", DEFAULT_FRONTEND))
    if os.environ.get("FIRECAL_FRONTEND_DIR") != "" and (frontend / "index.html").is_file():
        app.mount("/", StaticFiles(directory=frontend, html=True), name="frontend")
    return app


app = create_app()

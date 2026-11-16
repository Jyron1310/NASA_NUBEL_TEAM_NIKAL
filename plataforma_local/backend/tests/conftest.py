"""Fixtures comunes: configuración aislada en modo sintético, sin depender de un .env local."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.main import create_app
from firecal.settings import EnvSettings, Settings, build_settings, get_settings


@pytest.fixture(autouse=True)
def _lang_es():
    """Las aserciones de texto existentes están en español (fuera de una solicitud HTTP)."""
    from firecal.i18n import reset_lang, set_lang

    token = set_lang("es")
    yield
    reset_lang(token)


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch):
    """Fuerza modo sintético y quita la MAP_KEY para que los tests no dependan del entorno."""
    monkeypatch.setenv("FIRECAL_DATA_MODE", "synthetic")
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def settings() -> Settings:
    return build_settings(EnvSettings(_env_file=None))


@pytest.fixture
def client(settings: Settings) -> TestClient:
    return TestClient(create_app(settings))


@pytest.fixture(scope="session")
def plan_home(tmp_path_factory):
    """Datos reales de Cusco (CSV de Antonio, data/harmonized/) cargados en una carpeta aislada.

    No necesita el pipeline sintético: es lo que usa la plataforma del prototipo.
    """
    import shutil
    from types import SimpleNamespace

    from firecal.plan.events import build_events
    from firecal.settings import PROJECT_ROOT, Paths, ScientificParams, load_params

    home = tmp_path_factory.mktemp("plan_home")
    shutil.copytree(PROJECT_ROOT / "config", home / "config")
    raw = load_params(home / "config" / "settings.yaml").model_dump()
    raw["api"]["rate_limit"]["enabled"] = False
    raw["api"]["default_lang"] = "es"             # las aserciones de texto están en español
    env = EnvSettings(_env_file=None, FIRECAL_DATA_MODE="real")
    settings = Settings(env=env, params=ScientificParams.model_validate(raw),
                        paths=Paths(home=home))
    meta = build_events(settings)
    return SimpleNamespace(settings=settings, meta=meta)

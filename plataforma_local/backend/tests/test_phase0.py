"""Tests de la Fase 0: salud de la API, configuración, CLI y redacción de la MAP_KEY."""

from __future__ import annotations

import logging
from datetime import date

import pytest
from pydantic import ValidationError
from typer.testing import CliRunner

from firecal.cli import app as cli_app
from firecal.logging_utils import RedactMapKeyFilter, redact
from firecal.settings import EnvSettings, ScientificParams, build_settings


def test_health_returns_ok_and_data_mode(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    # El prototipo sirve los datos reales de Cusco.
    assert body["status"] == "ok" and body["data_mode"] == "real"
    assert isinstance(body["data_ready"], bool)


def test_docs_available(client):
    assert client.get("/docs").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_cors_allows_configured_origin(client, settings):
    origin = settings.params.api.cors_origins[0]
    resp = client.get("/health", headers={"Origin": origin})
    assert resp.headers.get("access-control-allow-origin") == origin


def test_settings_yaml_defaults(settings):
    p = settings.params
    assert p.region.name.startswith("Sur del Perú")
    assert p.grid.h3_res_store == 7
    assert p.harmonization.calib_window == (date(2012, 1, 20), date(2021, 6, 30))
    assert p.harmonization.holdout_years == [2019, 2020]
    assert p.synthetic.end is None
    assert settings.paths.duckdb_path.parts[-3:] == ("data", "processed", "firecal.duckdb")


def test_data_mode_from_env(monkeypatch):
    monkeypatch.setenv("FIRECAL_DATA_MODE", "real")
    s = build_settings(EnvSettings(_env_file=None))
    assert s.data_mode == "real"
    assert s.input_dir == s.paths.raw_firms_dir


def test_invalid_data_mode_rejected(monkeypatch):
    monkeypatch.setenv("FIRECAL_DATA_MODE", "fake")
    with pytest.raises(ValidationError):
        EnvSettings(_env_file=None)


def test_yaml_rejects_unknown_keys(settings):
    raw = settings.params.model_dump()
    raw["grid"]["h3_res_stroe"] = 7  # error de tipeo
    with pytest.raises(ValidationError):
        ScientificParams.model_validate(raw)


def test_redact_map_key_in_url():
    url = "https://firms.modaps.eosdis.nasa.gov/api/area/csv/abc123SECRET/MODIS_NRT/-74,-15,-70,-11/5/2026-11-01"
    out = redact(url)
    assert "abc123SECRET" not in out
    assert "/csv/***/MODIS_NRT/" in out


def test_log_filter_redacts_literal_key(caplog):
    logger = logging.getLogger("test.redact")
    logger.addFilter(RedactMapKeyFilter("abc123SECRET"))
    with caplog.at_level(logging.INFO, logger="test.redact"):
        logger.info("clave=%s", "abc123SECRET")
    assert "abc123SECRET" not in caplog.text
    assert "***" in caplog.text


def test_cli_help_lists_commands():
    result = CliRunner().invoke(cli_app, ["--help"])
    assert result.exit_code == 0
    for cmd in ("plan-events", "serve"):
        assert cmd in result.output

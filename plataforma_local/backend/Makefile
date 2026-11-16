# Atajos a la CLI de Nikal. Funciona en Linux/macOS/WSL y en Windows con GNU make.

ifeq ($(OS),Windows_NT)
  PYTHON_BOOT ?= py -3.12
  VENV_BIN := .venv/Scripts
else
  PYTHON_BOOT ?= python3
  VENV_BIN := .venv/bin
endif

# Python en UTF-8 siempre (Windows usa cp1252 por defecto).
export PYTHONUTF8 := 1

PY := $(VENV_BIN)/python
FIRECAL := $(PY) -m firecal.cli

.PHONY: help venv install lint format test serve synth precompute all-synthetic

help:
	@echo "make install        crea .venv e instala dependencias (incluye dev)"
	@echo "make lint           ruff check ."
	@echo "make format         ruff format + ruff check --fix"
	@echo "make test           pytest -q"
	@echo "make serve          levanta la API en http://localhost:8000 (docs en /docs)"
	@echo "make all-synthetic  corre todo el pipeline en modo sintético (Fase 8)"

venv:
	$(PYTHON_BOOT) -m venv .venv

install: venv
	$(PY) -m pip install --upgrade pip
	$(PY) -m pip install -e ".[dev]"

lint:
	$(PY) -m ruff check .

format:
	$(PY) -m ruff format .
	$(PY) -m ruff check --fix .

test:
	$(PY) -m pytest -q

serve:
	$(FIRECAL) serve

synth:
	$(FIRECAL) synth

precompute:
	$(FIRECAL) precompute

all-synthetic:
	$(FIRECAL) all --mode synthetic

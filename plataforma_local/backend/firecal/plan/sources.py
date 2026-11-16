"""Ubicación y contrato de los datos armonizados de Antonio (ver METHODOLOGY.md en la raíz).

Los datos NO se copian dentro del backend: se leen desde la raíz del repositorio
(``data/harmonized/`` y ``harmonizacion/cusco_ref/``). Se buscan, en orden:

1. ``FIRECAL_SOURCE_ROOT`` (variable de entorno), si está definida.
2. La carpeta padre del backend (``plataforma_local/`` en el repo; ``/app`` en Docker).
3. La raíz del repositorio (dos niveles arriba del backend).
"""

from __future__ import annotations

import os
from pathlib import Path

from firecal.settings import PROJECT_ROOT

CELDA_DIA_CSV = "harmonizado_cusco_celda_dia.csv"
FOCOS_CSV = "focos_cusco_individuales.csv"

# Contratos (harmonizacion/docs/CONTRATO.md y CONTRATO_focos.md): nombres y orden exactos.
COLS_CELDA_DIA = ["fecha_local", "cell_lat", "cell_lon", "alt_m", "n_modis", "n_viirs",
                  "frp_modis", "frp_viirs", "eq_hotspots", "fuente_serie", "calidad"]
COLS_FOCOS = ["fecha_local", "fecha_utc", "hora_utc", "latitude", "longitude", "cell_lat",
              "cell_lon", "alt_m", "sensor", "satelite", "frp", "brillo_k", "confianza",
              "diurno_nocturno", "fuente_serie", "calidad", "en_serie", "eq_foco"]

# Sumas de control (METHODOLOGY.md §14; v1.3: NOAA-20 en los días sin S-NPP). Si cambian, los datos
# cambiaron: investigar.
CONTROL = {
    "celda_dia": {"filas": 36568, "suma": 15818.39,
                  "sha256": "d686c8fda6259392730e416e40139b436311042c5081b9273cac747778e639b1"},
    "focos": {"filas": 59211, "suma": 15818.36,
              "sha256": "934c28d5f5fa8c4eedd926719292ac08ddaf3bb6a8cfad824bffd25f7f334d26"},
}

# Región armonizada y validada (METHODOLOGY.md y §12): solo Cusco.
REGION_CODE = "PE-CUS"
REGION_NAME = "Cusco"


def source_root() -> Path:
    env = os.environ.get("FIRECAL_SOURCE_ROOT")
    candidates = [Path(env)] if env else [PROJECT_ROOT.parent, PROJECT_ROOT.parent.parent]
    for root in candidates:
        if (root / "data" / "harmonized" / CELDA_DIA_CSV).is_file():
            return root
    raise FileNotFoundError(
        "No se encontraron los CSV armonizados (data/harmonized/). Busque en: "
        + ", ".join(str(c) for c in candidates)
        + ". Define FIRECAL_SOURCE_ROOT con la raiz del repositorio.")


def harmonized_dir() -> Path:
    return source_root() / "data" / "harmonized"


def cusco_ref_dir() -> Path:
    return source_root() / "harmonizacion" / "cusco_ref"

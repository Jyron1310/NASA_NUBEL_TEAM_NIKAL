"""Configuración de logging con redacción de la MAP_KEY de FIRMS.

La MAP_KEY nunca debe aparecer en los logs. El filtro ``RedactMapKeyFilter``:
- reemplaza el segmento de la clave en URLs de la API de FIRMS
  (``.../csv/<KEY>/...`` → ``.../csv/***/...``);
- reemplaza cualquier aparición literal de la clave configurada.
"""

from __future__ import annotations

import contextlib
import logging
import re
import sys

# Segmento de clave en URLs de FIRMS: /api/<servicio>/csv/<MAP_KEY>/...
_FIRMS_KEY_IN_URL = re.compile(r"(/csv/)[^/\s]+(/)")
REDACTED = "***"


def redact(text: str, secret: str | None = None) -> str:
    """Devuelve ``text`` con la MAP_KEY redactada."""
    out = _FIRMS_KEY_IN_URL.sub(rf"\1{REDACTED}\2", text)
    if secret:
        out = out.replace(secret, REDACTED)
    return out


class RedactMapKeyFilter(logging.Filter):
    """Filtro de logging que redacta la MAP_KEY en el mensaje ya formateado."""

    def __init__(self, secret: str | None = None) -> None:
        super().__init__()
        self._secret = secret

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        cleaned = redact(message, self._secret)
        if cleaned != message:
            record.msg = cleaned
            record.args = None
        return True


def force_utf8_stdio() -> None:
    """Fuerza UTF-8 en stdout/stderr aunque la consola de Windows use cp1252.

    Así un carácter no ASCII en un mensaje nunca hace caer el programa. Los mensajes de
    consola se mantienen en ASCII como medida extra, pero el sistema no depende de eso.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            # Stream cerrado o no reconfigurable (p. ej. capturado en tests): se deja igual.
            with contextlib.suppress(ValueError, OSError):
                reconfigure(encoding="utf-8", errors="backslashreplace")


def setup_logging(level: str = "INFO", secret: str | None = None) -> None:
    """Configura el logger raíz (UTF-8, formato legible y filtro de redacción)."""
    force_utf8_stdio()
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%H:%M:%S")
    )
    handler.addFilter(RedactMapKeyFilter(secret))
    root = logging.getLogger()
    for old in list(root.handlers):
        root.removeHandler(old)
    root.addHandler(handler)
    root.setLevel(level.upper())

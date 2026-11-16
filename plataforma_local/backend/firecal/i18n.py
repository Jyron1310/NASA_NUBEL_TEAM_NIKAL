"""Idioma de los textos para el usuario (mensajes de error, notas, frases de las analíticas).

Uso:  ``t(es="Sin datos", en="No data")``. El idioma de cada solicitud lo fija la API
(``?lang=en|es``; por defecto ``api.default_lang``) en una variable de contexto, así que el código
de cálculo no necesita recibirlo como parámetro. Fuera de una solicitud (CLI, pruebas) vale el
idioma por defecto del contexto.

Para agregar un idioma: sumarlo a ``SUPPORTED`` y pasar su texto en cada ``t(...)`` (p. ej.
``pt="..."``). Si falta una traducción se usa la inglesa y, si tampoco está, la española.
Los nombres de campos y los códigos de la API (``categoria``, ``calidad``...) NO se traducen:
son el contrato con la interfaz.
"""

from __future__ import annotations

from contextvars import ContextVar

SUPPORTED = ("en", "es")
DEFAULT = "en"

_lang: ContextVar[str] = ContextVar("firecal_lang", default=DEFAULT)


def get_lang() -> str:
    return _lang.get()


def set_lang(lang: str | None, default: str = DEFAULT):
    """Fija el idioma de la solicitud actual. Devuelve el token para restaurarlo."""
    code = (lang or "").strip().lower()[:2]
    return _lang.set(code if code in SUPPORTED else default)


def reset_lang(token) -> None:
    _lang.reset(token)


def t(**texts: str) -> str:
    """Texto en el idioma actual (con respaldo en inglés y luego en español)."""
    return texts.get(_lang.get()) or texts.get("en") or texts.get("es") or ""


# Nombres de meses en cada idioma (frases de las analíticas).
MONTHS = {
    "es": ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
           "septiembre", "octubre", "noviembre", "diciembre"],
    "en": ["January", "February", "March", "April", "May", "June", "July", "August",
           "September", "October", "November", "December"],
}


def month_name(m: int) -> str:
    return MONTHS.get(_lang.get(), MONTHS["en"])[m - 1]


def join_list(items: list[str]) -> str:
    """'a', 'a y b' / 'a and b', 'a, b y c' / 'a, b and c'."""
    conj = t(es="y", en="and")
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + f" {conj} " + items[-1]

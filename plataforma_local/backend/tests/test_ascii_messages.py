"""Los mensajes que van a la consola (logs, typer.echo, excepciones) deben ser ASCII.

Es una medida extra para consolas Windows con cp1252; el sistema igual fuerza UTF-8.
Docstrings y comentarios pueden llevar tildes.
"""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG_METHODS = {"debug", "info", "warning", "error", "exception", "critical"}
API_ERRORS = {"AOIError", "HTTPException", "PlanError", "PlanNoData", "PlanNotReady",
              "NrtNotConfigured", "NrtUnavailable"}


def _strings(node: ast.AST) -> list[str]:
    """Textos literales dentro de una expresión (constantes y partes de f-strings)."""
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant)
            and isinstance(n.value, str)]


def _console_nodes(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            attr, owner = node.func.attr, node.func.value
            owner_name = owner.id if isinstance(owner, ast.Name) else ""
            if (attr in LOG_METHODS and owner_name in {"log", "logger", "logging"}) or (
                attr == "echo" and owner_name == "typer"
            ):
                yield node
        elif isinstance(node, ast.Raise) and node.exc is not None:
            # Errores que la API devuelve como JSON al cliente (no van a la consola).
            func = getattr(node.exc, "func", None)
            if getattr(func, "id", None) in API_ERRORS:
                continue
            yield node.exc


def test_console_messages_are_ascii():
    offenders = []
    for path in sorted([*ROOT.glob("firecal/**/*.py"), *ROOT.glob("api/**/*.py")]):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in _console_nodes(tree):
            for text in _strings(node):
                if not text.isascii():
                    rel = path.relative_to(ROOT)
                    offenders.append(f"{rel}:{node.lineno}: {text!r}")
    assert not offenders, "Mensajes de consola con caracteres no ASCII:\n" + "\n".join(offenders)

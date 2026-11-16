"""CLI de Nikal Cusco (Typer).

- ``firecal plan-events``: valida los CSV de Cusco (METHODOLOGY.md §14) y arma el Parquet.
- ``firecal serve``: levanta la API (y la interfaz compilada) con uvicorn.
- ``firecal informes``: genera los informes HTML de todas las unidades de un nivel.

El pipeline sintético anterior (synth, ingest, build, validate, precompute, all) se retiró el
14-nov-2026; está completo en la rama ``archivo/backend-sintetico``.
"""

from __future__ import annotations

import logging
from typing import Annotated

import typer

from firecal.logging_utils import force_utf8_stdio, setup_logging
from firecal.settings import get_settings

# Antes de que Typer/rich imprima la ayuda: UTF-8 en la consola de Windows.
force_utf8_stdio()

app = typer.Typer(
    name="firecal",
    help="Nikal Cusco: calendario armonizado de focos MODIS + VIIRS (datos de METHODOLOGY.md).",
    no_args_is_help=True,
    add_completion=False,
)
log = logging.getLogger("firecal.cli")


@app.callback()
def _main() -> None:
    """Inicializa el logging con la configuración actual."""
    settings = get_settings()
    key = settings.env.firms_map_key
    setup_logging(settings.env.log_level, key.get_secret_value() if key else None)


@app.command(name="plan-events")
def plan_events() -> None:
    """Carga los CSV armonizados de Cusco -> Parquet por anio/mes, con controles."""
    from firecal.plan.events import DataContractError, build_events

    try:
        meta = build_events(get_settings())
    except (DataContractError, FileNotFoundError) as exc:
        typer.echo(f"ERROR plan-events: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    c = meta["controles"]
    typer.echo(f"OK plan-events: Cusco {meta['primer_dia']}..{meta['ultimo_dia']} | "
               f"celda-dia {c['celda_dia']['filas']:,} filas, suma {c['celda_dia']['suma']:,.2f} | "
               f"focos {c['focos']['filas']:,} filas, suma {c['focos']['suma']:,.2f} | "
               "sumas de control de METHODOLOGY.md seccion 14: OK (data/processed/plan/)")


@app.command()
def informes(
    nivel: Annotated[str, typer.Option(help="provincia, distrito o pfaf_01 ... pfaf_12.")] = (
        "distrito"
    ),
    salida: Annotated[str, typer.Option(help="Carpeta de salida.")] = "informes",
    lang: Annotated[str, typer.Option(help="Idioma: es o en.")] = "es",
) -> None:
    """Genera los informes de todas las unidades de un nivel (HTML), su índice y la tabla CSV."""
    import html
    from pathlib import Path

    from firecal.i18n import reset_lang, set_lang
    from firecal.plan import ambitos
    from firecal.plan.query import PlanNoData, PlanNotReady, PlanStore

    token = set_lang(lang)
    try:
        store = PlanStore(get_settings())
        try:
            res = ambitos.resumen_nivel(store, nivel)
        except (PlanNotReady, PlanNoData) as exc:
            typer.echo(f"ERROR informes: {exc}", err=True)
            raise typer.Exit(code=1) from exc
        out = Path(salida) / nivel
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{nivel}_nivel_de_peligro.csv").write_text(
            ambitos.csv_nivel(store, nivel), encoding="utf-8")
        filas = []
        for u in res["unidades"]:
            nombre = f"{u['codigo']}.html"
            (out / nombre).write_text(ambitos.informe_html(store, nivel, u["codigo"]),
                                      encoding="utf-8")
            filas.append(
                f"<tr><td>{u['puesto'] or ''}</td><td><a href='{nombre}'>{html.escape(u['nombre'])}"
                f"</a></td><td>{html.escape(u['codigo'])}</td><td><span style='background:"
                f"{u['color']};padding:2px 8px;border-radius:6px'>{html.escape(u['etiqueta'])}"
                f"</span></td><td>{u['densidad']}</td><td>{u['recurrencia']}</td></tr>")
        titulo = html.escape(res["titulo"])
        (out / "index.html").write_text(
            "<!doctype html><meta charset='utf-8'><title>Nikal Cusco - " + titulo + "</title>"
            "<style>body{font:14px system-ui;margin:24px}td,th{padding:4px 8px;border-bottom:"
            "1px solid #eee;text-align:left}</style><h1>" + titulo + "</h1><p>"
            + html.escape(" ".join(res["metodo"]["notas"][:2])) + "</p><table><tr><th>#</th>"
            "<th>Unidad</th><th>Codigo</th><th>Nivel</th><th>Densidad</th><th>Recurrencia</th>"
            "</tr>" + "".join(filas) + "</table>", encoding="utf-8")
        typer.echo(f"OK informes: {len(filas)} unidades de '{nivel}' en {out}")
    finally:
        reset_lang(token)


@app.command()
def serve(
    host: Annotated[str | None, typer.Option(help="Host (por defecto FIRECAL_API_HOST).")] = None,
    port: Annotated[int | None, typer.Option(help="Puerto (por defecto FIRECAL_API_PORT).")] = None,
    reload: Annotated[bool, typer.Option(help="Recarga automática al cambiar código.")] = False,
) -> None:
    """Levanta la API FastAPI con uvicorn."""
    import uvicorn

    settings = get_settings()
    host = host or settings.env.api_host
    port = port or settings.env.api_port
    log.info("API en http://%s:%d", host, port)
    uvicorn.run("api.main:app", host=host, port=port, reload=reload)


if __name__ == "__main__":
    app()

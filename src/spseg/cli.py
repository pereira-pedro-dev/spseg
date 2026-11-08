"""Interface de linha de comando (`uv run spseg ...`)."""

from __future__ import annotations

import dataclasses
import typing
from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from spseg.analysis.compare import build_compare
from spseg.analysis.street_summary import NoStreetData, build_street_summary
from spseg.analysis.summary import BairroNotFound, CacheMissing, build_summary
from spseg.config import DEFAULT_MUNICIPIO, Settings, get_settings
from spseg.data.cache import cached_years, latest_year, read_facts
from spseg.data.excel import read_workbook
from spseg.data.reference import load_reference
from spseg.geo.resolve import BairroResolver, registry_from_entries_frame
from spseg.geo.street import StreetAmbiguous, StreetNotFound, display_street
from spseg.geo.text import normalize_key
from spseg.ingest import find_workbooks
from spseg.ingest import ingest as run_ingest
from spseg.quality.checks import run_all
from spseg.render.console import (
    CONSOLE,
    fmt_int,
    render_check,
    render_compare,
    render_distrito_list,
    render_street_summary,
    render_summary,
)
from spseg.render.export import (
    compare_to_json,
    street_summary_to_json,
    summary_to_json,
)

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    help=(
        "Resumo de segurança por distrito e por rua dentro do distrito "
        "usando os dados públicos da SSP-SP."
    ),
)

RESOLVED_METHODS = {"exact", "alias", "fuzzy", "geo"}


def _settings(raw_dir: Path | None = None) -> Settings:
    settings = get_settings()
    settings.ensure_dirs()
    if raw_dir is not None:
        settings = dataclasses.replace(settings, raw_dir=raw_dir.expanduser().resolve())
    return settings


def _fail(message: str, code: int = 1) -> None:
    CONSOLE.print(f"[red]Erro:[/red] {message}")
    raise typer.Exit(code=code)


def _taxonomy_label(reference) -> str:
    if reference.taxonomy is None:
        return "n/d"
    return str(reference.taxonomy.provisional)


def _parse_date(value: str | None, option: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        _fail(f"{option} deve estar no formato AAAA-MM-DD (recebido: {value!r}).")


def _district_not_found(exc: BairroNotFound, source: BaseException) -> typing.NoReturn:
    CONSOLE.print(f"[red]Distrito não encontrado:[/red] {exc.query}")
    if exc.suggestions:
        CONSOLE.print("Talvez você quis dizer:")
        for name, score in exc.suggestions:
            CONSOLE.print(f"  • {name} ({score:.0f}%)")
    raise typer.Exit(code=2) from source


@app.command()
def ingest(
    raw: Path | None = typer.Option(None, "--raw", help="Diretório dos .xlsx (padrão: data/raw)."),
    force: bool = typer.Option(False, "--force", "-f", help="Reprocessa mesmo com cache válido."),
    keep_all_municipalities: bool = typer.Option(
        False,
        "--keep-all-municipalities",
        help="Não filtra a capital (útil para o futuro; aumenta muito o cache).",
    ),
    ano: list[int] = typer.Option([], "--ano", help="Processa apenas estes anos (repetível)."),
) -> None:
    """Lê os .xlsx, gera o cache parquet e resolve bairros/categorias."""
    settings = _settings(raw)
    try:
        results, reference = run_ingest(
            settings,
            force=force,
            years=ano or None,
            keep_all_municipalities=keep_all_municipalities,
            progress=CONSOLE.print,
        )
    except (FileNotFoundError, ValueError) as exc:
        _fail(str(exc))

    table = Table(title="Ingestão concluída", show_header=True, header_style="bold")
    table.add_column("Ano")
    table.add_column("Linhas brutas", justify="right")
    table.add_column("Linhas no cache", justify="right")
    table.add_column("Excel relido")
    table.add_column("Enriquecido")
    for result in results:
        table.add_row(
            str(result.year),
            fmt_int(result.raw_rows or None),
            fmt_int(result.facts_rows or None),
            "sim" if result.rebuilt_raw else "não",
            "sim" if result.rebuilt_facts else "não",
        )
    CONSOLE.print(table)
    for result in results:
        for warning in result.warnings:
            CONSOLE.print(f"[yellow]{result.year}:[/yellow] {warning}")
    CONSOLE.print(
        f"[dim]Referência v{reference.version}: {len(reference.entries)} distritos. "
        f"Taxonomia provisória: {_taxonomy_label(reference)}.[/dim]"
    )


@app.command()
def check(
    source: str = typer.Option(
        "cache", "--source", help="'cache' (parquet, rápido) ou 'excel' (relê o .xlsx)."
    ),
    ano: int | None = typer.Option(None, "--ano", help="Ano a verificar (padrão: mais recente)."),
    raw: Path | None = typer.Option(None, "--raw", help="Diretório dos .xlsx (padrão: data/raw)."),
) -> None:
    """Relatório de qualidade e proveniência da base."""
    settings = _settings(raw)
    try:
        if source == "excel":
            workbooks = find_workbooks(settings.raw_dir)
            if not workbooks:
                _fail(f"Nenhum workbook em {settings.raw_dir}.")
            year = ano or max(workbooks)
            if year not in workbooks:
                _fail(f"Workbook de {year} não encontrado em {settings.raw_dir}.")
            frame, warnings = read_workbook(
                workbooks[year],
                municipio=DEFAULT_MUNICIPIO,
                progress=CONSOLE.print,
            )
            context = f"Excel {workbooks[year].name} (capital filtrada)"
        elif source == "cache":
            year = ano or latest_year(settings)
            if year is None:
                _fail(
                    "Cache ausente. Rode `uv run spseg ingest` ou use `--source excel`.",
                    code=3,
                )
            frame = read_facts(settings, years=[year])
            warnings = []
            context = f"cache de fatos {year}"
        else:
            _fail("--source deve ser 'cache' ou 'excel'.")
    except FileNotFoundError as exc:
        _fail(str(exc), code=3)

    render_check(run_all(frame, context=context, warnings=warnings))


@app.command("list")
def list_bairros(
    search: str | None = typer.Option(None, "--search", help="Filtra por nome."),
    ano: list[int] = typer.Option([], "--ano", help="Restringe a estes anos (repetível)."),
) -> None:
    """Lista os distritos presentes no cache e a taxa de resolução."""
    settings = _settings()
    if not cached_years(settings, "facts"):
        _fail("Cache ausente. Rode `uv run spseg ingest` primeiro.", code=3)
    try:
        facts = read_facts(settings, years=ano or None)
    except FileNotFoundError as exc:
        _fail(str(exc), code=3)

    entries = registry_from_entries_frame(facts)
    if not entries:
        _fail("Não há distritos resolvidos no cache.")
    resolver = BairroResolver(entries)

    counts = facts.groupby("bairro_id", dropna=True).size()
    resolved = facts["bairro_method"].isin(RESOLVED_METHODS).groupby(facts["bairro_id"]).mean()
    rows = [
        (
            entry.bairro_nome,
            entry.bairro_id,
            int(counts.get(entry.bairro_id, 0)),
            float(resolved.get(entry.bairro_id, 0.0)),
        )
        for entry in entries
    ]

    if search:
        needle = normalize_key(search)
        filtered = [row for row in rows if needle and needle in normalize_key(row[0])]
        if not filtered:
            suggestions = resolver.suggestions(search, limit=10)
            by_name = {entry.bairro_nome: entry.bairro_id for entry in entries}
            filtered = [
                (
                    name,
                    by_name[name],
                    int(counts.get(by_name[name], 0)),
                    float(resolved.get(by_name[name], 0.0)),
                )
                for name, _score in suggestions
                if name in by_name
            ]
        rows = filtered

    rows.sort(key=lambda row: row[0])
    render_distrito_list(rows, title=f"Distritos disponíveis ({len(rows)})")
    reference = load_reference(settings)
    if not reference.status.has_rates:
        CONSOLE.print(
            "[dim]Sem população/domicílios em data/reference: taxas por habitante "
            "e por domicílio ficam 'n/d' até a referência ser construída.[/dim]"
        )


def _show_summary(
    nome: str,
    *,
    municipio: str,
    anos: int | None,
    desde: str | None,
    ate: str | None,
    json_output: bool,
) -> None:
    settings = _settings()
    try:
        summary = build_summary(
            settings,
            nome,
            municipio=municipio,
            since=_parse_date(desde, "--desde"),
            until=_parse_date(ate, "--ate"),
            years=anos,
        )
    except CacheMissing as exc:
        _fail(str(exc), code=3)
    except BairroNotFound as exc:
        _district_not_found(exc, exc)
    except (ValueError, FileNotFoundError) as exc:
        _fail(str(exc))

    if json_output:
        typer.echo(summary_to_json(summary))
    else:
        render_summary(summary)


def _show_street(
    rua: str,
    *,
    distrito: str,
    municipio: str,
    anos: int | None,
    desde: str | None,
    ate: str | None,
    json_output: bool,
) -> None:
    settings = _settings()
    try:
        summary = build_street_summary(
            settings,
            rua,
            distrito,
            municipio=municipio,
            since=_parse_date(desde, "--desde"),
            until=_parse_date(ate, "--ate"),
            years=anos,
        )
    except CacheMissing as exc:
        _fail(str(exc), code=3)
    except BairroNotFound as exc:
        _district_not_found(exc, exc)
    except StreetNotFound as exc:
        CONSOLE.print(f"[red]Rua não encontrada em {exc.distrito} no período:[/red] {exc.query}")
        if exc.suggestions:
            CONSOLE.print("Talvez você quis dizer:")
            for name, score in exc.suggestions:
                CONSOLE.print(f"  • {name} ({score:.0f}%)")
        raise typer.Exit(code=2) from exc
    except StreetAmbiguous as exc:
        CONSOLE.print(f"[red]Mais de uma rua corresponde a {exc.query} em {exc.distrito}:[/red]")
        for key in exc.candidates:
            count = exc.counts.get(key)
            suffix = f" ({fmt_int(count)} registros)" if count is not None else ""
            CONSOLE.print(f"  • {display_street(key)}{suffix}")
        example = display_street(exc.candidates[0]) if exc.candidates else "o tipo"
        CONSOLE.print(f'Repita informando o tipo (ex.: "{example}").')
        raise typer.Exit(code=2) from exc
    except NoStreetData as exc:
        CONSOLE.print(f"[red]Sem dados por rua:[/red] {exc}")
        raise typer.Exit(code=2) from exc
    except (ValueError, FileNotFoundError) as exc:
        _fail(str(exc))

    if json_output:
        typer.echo(street_summary_to_json(summary))
    else:
        render_street_summary(summary)


@app.command()
def rua(
    nome: str = typer.Argument(..., help="Nome da rua (ex.: Mourato Coelho)."),
    distrito: str = typer.Option(..., "--distrito", help="Distrito onde a rua será buscada."),
    municipio: str = typer.Option(DEFAULT_MUNICIPIO, "--municipio"),
    anos: int | None = typer.Option(
        None,
        "--anos",
        help="Janela móvel em anos (ex.: 3). Padrão: toda a cobertura dos arquivos.",
    ),
    desde: str | None = typer.Option(None, "--desde", help="Data inicial (AAAA-MM-DD)."),
    ate: str | None = typer.Option(None, "--ate", help="Data final (AAAA-MM-DD)."),
    json_output: bool = typer.Option(False, "--json", help="Saída JSON."),
) -> None:
    """Resumo de segurança de uma rua dentro de um distrito."""
    _show_street(
        nome,
        distrito=distrito,
        municipio=municipio,
        anos=anos,
        desde=desde,
        ate=ate,
        json_output=json_output,
    )


@app.command()
def bairro(
    nome: str = typer.Argument(..., help="Nome do distrito ou bairro (ex.: Pinheiros)."),
    municipio: str = typer.Option(DEFAULT_MUNICIPIO, "--municipio"),
    anos: int | None = typer.Option(
        None,
        "--anos",
        help="Janela móvel em anos (ex.: 3). Padrão: toda a cobertura dos arquivos.",
    ),
    desde: str | None = typer.Option(None, "--desde", help="Data inicial (AAAA-MM-DD)."),
    ate: str | None = typer.Option(None, "--ate", help="Data final (AAAA-MM-DD)."),
    json_output: bool = typer.Option(False, "--json", help="Saída JSON."),
) -> None:
    """Resumo de segurança de um distrito (aceita bairro como alias)."""
    _show_summary(
        nome,
        municipio=municipio,
        anos=anos,
        desde=desde,
        ate=ate,
        json_output=json_output,
    )


@app.command()
def distrito(
    nome: str = typer.Argument(..., help="Nome do distrito (ex.: Pinheiros)."),
    municipio: str = typer.Option(DEFAULT_MUNICIPIO, "--municipio"),
    anos: int | None = typer.Option(
        None,
        "--anos",
        help="Janela móvel em anos (ex.: 3). Padrão: toda a cobertura dos arquivos.",
    ),
    desde: str | None = typer.Option(None, "--desde", help="Data inicial (AAAA-MM-DD)."),
    ate: str | None = typer.Option(None, "--ate", help="Data final (AAAA-MM-DD)."),
    json_output: bool = typer.Option(False, "--json", help="Saída JSON."),
) -> None:
    """Alias de `spseg bairro`: resumo de segurança de um distrito."""
    _show_summary(
        nome,
        municipio=municipio,
        anos=anos,
        desde=desde,
        ate=ate,
        json_output=json_output,
    )


@app.command()
def compare(
    nomes: list[str] = typer.Argument(
        ...,
        help=('Dois a seis distritos na mesma janela (ex.: Pinheiros "Itaim Bibi").'),
    ),
    municipio: str = typer.Option(DEFAULT_MUNICIPIO, "--municipio"),
    anos: int | None = typer.Option(
        None,
        "--anos",
        help="Janela móvel em anos (ex.: 3). Padrão: toda a cobertura dos arquivos.",
    ),
    desde: str | None = typer.Option(None, "--desde", help="Data inicial (AAAA-MM-DD)."),
    ate: str | None = typer.Option(None, "--ate", help="Data final (AAAA-MM-DD)."),
    json_output: bool = typer.Option(False, "--json", help="Saída JSON."),
) -> None:
    """Compara distritos lado a lado, com score relativo (provisório)."""
    settings = _settings()
    try:
        comparison = build_compare(
            settings,
            nomes,
            municipio=municipio,
            since=_parse_date(desde, "--desde"),
            until=_parse_date(ate, "--ate"),
            years=anos,
        )
    except CacheMissing as exc:
        _fail(str(exc), code=3)
    except BairroNotFound as exc:
        _district_not_found(exc, exc)
    except (ValueError, FileNotFoundError) as exc:
        _fail(str(exc))

    if json_output:
        typer.echo(compare_to_json(comparison))
    else:
        render_compare(comparison)


@app.command()
def doctor() -> None:
    """Mostra o estado do cache e da referência."""
    settings = _settings()
    console = Console()
    facts_years = cached_years(settings, "facts")
    reference = load_reference(settings)
    console.print(f"data/: {settings.data_dir}")
    console.print(f"cache de fatos: {facts_years or 'ausente'}")
    status = reference.status
    console.print(
        f"referência v{reference.version}: distritos={status.distritos} "
        f"população={status.populacao} domicílios={status.domicilios} "
        f"aliases={status.aliases} taxonomia={status.taxonomia}"
    )
    for issue in status.issues:
        console.print(f"[yellow]• {issue}[/yellow]")
    if not facts_years:
        console.print("[yellow]Rode `uv run spseg ingest` para criar o cache.[/yellow]")


__all__ = ["app"]

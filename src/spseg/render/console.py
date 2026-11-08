"""Renderização no terminal (Rich), em português."""

from __future__ import annotations

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from spseg.models import BairroSummary, CompareSummary, StreetSummary
from spseg.quality.checks import CheckSection

CONSOLE = Console()

TREND = {
    "up": ("[red]↑[/red]", "subiu"),
    "down": ("[green]↓[/green]", "caiu"),
    "flat": ("[yellow]→[/yellow]", "estável"),
}


def fmt_int(value: int | None) -> str:
    if value is None:
        return "n/d"
    return f"{value:,}".replace(",", ".")


def fmt_rate(value: float | None, digits: int = 1) -> str:
    if value is None:
        return "n/d"
    text = f"{value:,.{digits}f}"
    return text.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/d"
    return fmt_rate(value, 1) + "%"


def _base_label(summary: BairroSummary) -> str:
    if not summary.denominator_level:
        return "sem denominador (apenas contagens)"
    source = (summary.denominator_source or "").split(" (")[0].strip()
    return f"{summary.denominator_level} ({source})" if source else summary.denominator_level


def render_summary(summary: BairroSummary, console: Console | None = None) -> None:
    console = console or CONSOLE
    unit_label = "Distrito" if summary.nivel == "distrito" else summary.nivel.capitalize()
    header = (
        f"[bold]{unit_label}:[/bold] {escape(summary.bairro_nome)} "
        f"({escape(summary.municipio)})\n"
        f"Período: {summary.period.label}\n"
        f"Base: {escape(_base_label(summary))}\n"
        f"População: {fmt_int(summary.population)} | "
        f"Domicílios: {fmt_int(summary.households)}"
    )
    if summary.period.partial:
        header += "\n[yellow]⚠ ano corrente incompleto na base[/yellow]"
    console.print(Panel(header, title="Resumo de segurança", expand=False))

    if summary.population is None and summary.households is None:
        console.print(
            "[dim]Sem denominadores em data/reference: o resumo mostra apenas "
            "contagens, não taxas.[/dim]"
        )

    table = Table(show_header=True, header_style="bold", expand=False)
    table.add_column("Categoria")
    table.add_column("Ocorr.", justify="right")
    table.add_column("Incidentes", justify="right")
    table.add_column("/100 mil hab.", justify="right")
    table.add_column("/10 mil dom.", justify="right")
    table.add_column("Tendência", justify="center")

    for category in summary.categories:
        arrow, verb = TREND.get(category.trend or "", ("—", ""))
        trend = arrow
        if category.trend_pct is not None:
            trend += f" {fmt_pct(abs(category.trend_pct))}"
        table.add_row(
            escape(category.label),
            fmt_int(category.occurrences),
            fmt_int(category.incidents),
            fmt_rate(category.rate_per_100k),
            fmt_rate(category.rate_per_10k_households),
            trend,
        )

    table.add_section()
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{fmt_int(summary.total_occurrences)}[/bold]",
        f"[bold]{fmt_int(summary.total_incidents)}[/bold]",
        "",
        "",
        "",
    )
    console.print(table)
    console.print(
        "[dim]Ocorr. = registros por natureza; Incidentes = BOs distintos. "
        "Cada registro entra em uma única categoria (prioridade).[/dim]"
    )
    console.print(_score_block(summary.score))

    nature_rows = [
        (category.label, category.top_natures)
        for category in summary.categories
        if category.top_natures
    ]
    if nature_rows:
        nature_table = Table(title="Principais naturezas por categoria", show_header=True)
        nature_table.add_column("Categoria")
        nature_table.add_column("Top naturezas")
        for label, natures in nature_rows:
            text = "\n".join(f"{escape(name)} ({fmt_int(count)})" for name, count in natures)
            nature_table.add_row(escape(label), text)
        console.print(nature_table)

    quality = summary.quality
    quality_lines = [
        f"Registros no distrito: {fmt_int(quality.rows_in_bairro)}",
        "Resolução da cidade no período: "
        + fmt_pct(None if quality.resolution_rate is None else quality.resolution_rate * 100),
    ]
    if quality.method_counts:
        methods = ", ".join(
            f"{method}: {fmt_int(count)}" for method, count in sorted(quality.method_counts.items())
        )
        quality_lines.append(f"Métodos: {methods}")
    if quality.notes:
        quality_lines.append("")
        quality_lines.extend(f"• {note}" for note in quality.notes)
    console.print(Panel("\n".join(quality_lines), title="Qualidade e metodologia", expand=False))

    if summary.taxonomy_provisional:
        console.print(
            "[yellow]Aviso:[/yellow] taxonomia provisória — as categorias não foram "
            "validadas. Não use este resumo como critério único de decisão."
        )


def _fmt_share(value: float | None) -> str:
    return fmt_pct(None if value is None else value * 100)


def _score_block(score) -> str:  # noqa: ANN001 - DistrictScore | None
    if score is None:
        return "Score: n/d — nenhum distrito com score na janela."
    header = "Score (provisório): n/d"
    if score.available and score.value is not None:
        if score.rank is not None and score.of:
            header = (
                f"Score (provisório): {fmt_rate(score.value, 2)} — "
                f"{fmt_int(score.rank)}º mais seguro de {fmt_int(score.of)} "
                "distritos com score"
            )
        else:
            header = f"Score (provisório): {fmt_rate(score.value, 2)}"
    if score.weight_coverage is not None and score.weight_coverage < 1:
        header += f" | peso elegível: {_fmt_share(score.weight_coverage)}"
    lines = [header]
    lines.extend(f"• {escape(note)}" for note in score.notes)
    return "\n".join(lines)


def render_compare(summary: CompareSummary, console: Console | None = None) -> None:
    console = console or CONSOLE
    names = " vs ".join(district.bairro_nome for district in summary.districts)
    header = (
        f"[bold]Distritos:[/bold] {escape(names)} — {escape(summary.municipio)}\n"
        f"Período: {summary.period.label}\n"
        f"Janela idêntica para todos os distritos"
    )
    if summary.period.partial:
        header += "\n[yellow]⚠ ano corrente incompleto na base[/yellow]"
    console.print(Panel(header, title="Comparação de distritos", expand=False))

    overview = Table(show_header=True, header_style="bold", expand=False)
    overview.add_column("Distrito")
    overview.add_column("Ocorr.", justify="right")
    overview.add_column("Incidentes", justify="right")
    overview.add_column("População", justify="right")
    overview.add_column("Score (provisório)", justify="right")
    overview.add_column("Posto de segurança", justify="right")
    for district in summary.districts:
        score = district.score
        if score is not None and score.available and score.value is not None:
            value = fmt_rate(score.value, 2)
            rank = (
                f"{fmt_int(score.rank)}º de {fmt_int(score.of)}"
                if score.rank is not None and score.of
                else "n/d"
            )
        else:
            value, rank = "n/d", "n/d"
        overview.add_row(
            escape(district.bairro_nome),
            fmt_int(district.total_occurrences),
            fmt_int(district.total_incidents),
            fmt_int(district.population),
            value,
            rank,
        )
    console.print(overview)

    category_table = Table(
        title="Por categoria: n / taxa por 100 mil hab. / percentil",
        show_header=True,
        header_style="bold",
        expand=False,
    )
    category_table.add_column("Categoria")
    for district in summary.districts:
        category_table.add_column(escape(district.bairro_nome), justify="right")
    category_ids = {
        category.id for district in summary.districts for category in district.categories
    }
    score_categories = {
        district.bairro_nome: {
            category.id: category
            for category in (district.score.categories if district.score else ())
        }
        for district in summary.districts
    }
    for category_id in category_ids:
        label = next(
            (
                category.label
                for district in summary.districts
                for category in district.categories
                if category.id == category_id
            ),
            category_id,
        )
        row = [escape(label)]
        for district in summary.districts:
            category = next((c for c in district.categories if c.id == category_id), None)
            if category is None:
                row.append("—")
                continue
            scored = score_categories.get(district.bairro_nome, {}).get(category_id)
            percentile = (
                _fmt_share(scored.percentile)
                if scored is not None and scored.percentile is not None
                else "n/d"
            )
            row.append(
                f"{fmt_int(category.occurrences)}\n{fmt_rate(category.rate_per_100k)} "
                f"| {percentile}"
            )
        category_table.add_row(*row)
    console.print(category_table)
    console.print(
        "[dim]Taxa por 100 mil habitantes (Censo 2022 estático para 2024–2026). "
        "Percentil: menor = mais seguro em relação aos distritos elegíveis na "
        "mesma janela. Score e posto são provisórios e aparecem sempre com os "
        "percentis por categoria.[/dim]"
    )

    quality_lines = [
        "Resolução da cidade no período: "
        + fmt_pct(
            None if summary.city_resolution_rate is None else summary.city_resolution_rate * 100
        ),
    ]
    if summary.city_suppressed:
        quality_lines.append(
            f"{fmt_int(summary.city_suppressed)} registros com local suprimido não "
            "entram em nenhum distrito."
        )
    if not summary.weights.declared:
        quality_lines.append(
            "Pesos por natureza não declarados: score com peso igual (provisório)."
        )
    for district in summary.districts:
        methods = ", ".join(
            f"{method}: {fmt_int(count)}"
            for method, count in sorted(district.method_counts.items())
        )
        quality_lines.append(f"[bold]{escape(district.bairro_nome)}[/bold]: {methods}")
        score = district.score
        if score is not None:
            quality_lines.extend(f"  • {escape(note)}" for note in score.notes)
    console.print(Panel("\n".join(quality_lines), title="Qualidade e metodologia", expand=False))

    if summary.taxonomy_provisional:
        console.print(
            "[yellow]Aviso:[/yellow] taxonomia e pesos provisórios — não use a "
            "comparação como critério único de decisão."
        )


def _composition_lines(rows: tuple[tuple[str, int], ...]) -> str:
    if not rows:
        return "n/d"
    return "; ".join(f"{escape(name)} ({fmt_int(count)})" for name, count in rows)


def render_street_summary(summary: StreetSummary, console: Console | None = None) -> None:
    console = console or CONSOLE
    tipo = f" ({summary.rua_tipo})" if summary.rua_tipo else ""
    coverage = summary.district_coverage
    coverage_line = (
        f"Cobertura de rua no distrito: {_fmt_share(coverage)} "
        f"({fmt_int(summary.district_visible_occurrences)} de "
        f"{fmt_int(summary.district_total_occurrences)} registros)"
        if coverage is not None
        else "Cobertura de rua no distrito: n/d"
    )
    header = (
        f"[bold]Rua:[/bold] {escape(summary.rua)}{escape(tipo)}\n"
        f"[bold]Distrito:[/bold] {escape(summary.distrito)} "
        f"({escape(summary.municipio)})\n"
        f"Período: {summary.period.label}\n"
        f"{coverage_line}\n\n"
        "[yellow]⚠ Grão rua:[/yellow] mede crime em espaço público no logradouro. "
        "Invasão de residência e violência sexual têm logradouro suprimido em 100% "
        "dos casos e não aparecem aqui. Não mede risco do imóvel."
    )
    if summary.period.partial:
        header += "\n[yellow]⚠ ano corrente incompleto na base[/yellow]"
    console.print(Panel(header, title="Resumo de segurança — rua", expand=False))

    violent = next(
        (category for category in summary.categories if category.id == "crime_violento"),
        None,
    )
    if violent is not None:
        parts = []
        if violent.share_of_district is not None:
            parts.append(
                f"{_fmt_share(violent.share_of_district)} do total de "
                f"{violent.label.lower()} do distrito"
            )
        if violent.share_of_street is not None:
            parts.append(f"{_fmt_share(violent.share_of_street)} das ocorrências da rua")
        detail = f" ({'; '.join(parts)})" if parts else ""
        console.print(
            f"[bold]{escape(violent.label)}:[/bold] {fmt_int(violent.occurrences)}{detail}"
        )
        console.print()

    table = Table(show_header=True, header_style="bold", expand=False)
    table.add_column("Categoria")
    table.add_column("Ocorr.", justify="right")
    table.add_column("Incidentes", justify="right")
    table.add_column("% do distrito*", justify="right")
    table.add_column("% da rua", justify="right")

    for category in summary.categories:
        table.add_row(
            escape(category.label),
            fmt_int(category.occurrences),
            fmt_int(category.incidents),
            _fmt_share(category.share_of_district),
            _fmt_share(category.share_of_street),
        )

    table.add_section()
    table.add_row(
        "[bold]Total[/bold]",
        f"[bold]{fmt_int(summary.total_occurrences)}[/bold]",
        f"[bold]{fmt_int(summary.total_incidents)}[/bold]",
        f"[bold]{_fmt_share(summary.share_of_district)}[/bold]",
        "[bold]100,0%[/bold]",
    )
    console.print(table)
    console.print(
        "[dim]* % do distrito = participação no total da categoria no distrito com "
        "rua atribuível. Não usa o total do distrito que inclui registros sem rua.[/dim]"
    )
    console.print("[dim]Ocorr. = registros por natureza; Incidentes = BOs distintos.[/dim]")

    context = Table(title="Contexto do distrito", show_header=True, header_style="bold")
    context.add_column("Categoria")
    context.add_column("No distrito", justify="right")
    context.add_column("Com rua", justify="right")
    context.add_column("Cobertura", justify="right")
    for category in summary.district_categories:
        context.add_row(
            escape(category.label),
            fmt_int(category.occurrences),
            fmt_int(category.visible_occurrences),
            _fmt_share(category.coverage),
        )
    context.add_section()
    context.add_row(
        "[bold]Total[/bold]",
        f"[bold]{fmt_int(summary.district_total_occurrences)}[/bold]",
        f"[bold]{fmt_int(summary.district_visible_occurrences)}[/bold]",
        f"[bold]{_fmt_share(summary.district_coverage)}[/bold]",
    )
    console.print(context)

    composition = Table(title="Composição da rua", show_header=True, header_style="bold")
    composition.add_column("Recorte")
    composition.add_column("Mais frequentes")
    composition.add_row("Principais naturezas", _composition_lines(summary.top_natures))
    composition.add_row("Principais tipos de local", _composition_lines(summary.top_tipo_local))
    console.print(composition)

    quality = summary.quality
    excluded = max(
        0,
        quality.not_visible_occurrences
        - quality.suppressed_logradouro
        - quality.missing_logradouro,
    )
    quality_lines = [
        f"Registros na rua: {fmt_int(quality.rows_in_street)}",
        f"Registros no distrito: {fmt_int(quality.rows_in_district)}",
        "Com rua atribuível: "
        f"{fmt_int(quality.rows_visible)} ({_fmt_share(summary.district_coverage)})",
        "Sem rua: "
        f"{fmt_int(quality.not_visible_occurrences)} "
        f"(suprimido: {fmt_int(quality.suppressed_logradouro)}; "
        f"ausente: {fmt_int(quality.missing_logradouro)}; "
        f"categoria excluída: {fmt_int(excluded)})",
    ]
    if quality.district_resolution_rate is not None:
        quality_lines.append(
            f"Resolução do distrito no período: {_fmt_share(quality.district_resolution_rate)}"
        )
    if quality.district_method_counts:
        methods = ", ".join(
            f"{method}: {fmt_int(count)}"
            for method, count in sorted(quality.district_method_counts.items())
        )
        quality_lines.append(f"Métodos: {methods}")
    if quality.notes:
        quality_lines.append("")
        quality_lines.extend(f"• {note}" for note in quality.notes)
    console.print(Panel("\n".join(quality_lines), title="Qualidade e metodologia", expand=False))

    if summary.taxonomy_provisional:
        console.print(
            "[yellow]Aviso:[/yellow] taxonomia provisória — as categorias não foram "
            "validadas. Não use este resumo como critério único de decisão."
        )


def render_check(sections: list[CheckSection], console: Console | None = None) -> None:
    console = console or CONSOLE
    for section in sections:
        console.print()
        console.rule(f"[bold]{escape(section.title)}[/bold]")
        for line in section.lines:
            console.print(line)


def render_distrito_list(
    rows: list[tuple[str, str, int, float | None]],
    *,
    console: Console | None = None,
    title: str = "Distritos disponíveis",
) -> None:
    console = console or CONSOLE
    table = Table(title=title, show_header=True, header_style="bold")
    table.add_column("Distrito", no_wrap=True, max_width=24, overflow="ellipsis")
    table.add_column("ID", no_wrap=True, max_width=24, overflow="ellipsis")
    table.add_column("Registros", justify="right", no_wrap=True)
    table.add_column("Resolvido", justify="right", no_wrap=True)
    for name, identifier, count, rate in rows:
        table.add_row(
            escape(name),
            escape(identifier),
            fmt_int(count),
            fmt_pct(None if rate is None else rate * 100),
        )
    console.print(table)

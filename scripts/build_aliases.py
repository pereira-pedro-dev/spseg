#!/usr/bin/env python
"""Aprende aliases bairro→distrito a partir do cache geolocalizado.

Uso:
    uv run python scripts/build_aliases.py --dry-run
    uv run python scripts/build_aliases.py
    uv run python scripts/build_aliases.py --min-n 10 --min-share 0.9

O script lê `data/cache/facts/*.parquet`, considera apenas linhas com
`bairro_method=geo`, agrupa por `bairro_raw` normalizado e grava
`data/reference/bairro_aliases.csv` com `fonte=derivado:geo n=... share=...`.

Aliases curados (fonte diferente de `derivado:geo`) são preservados. Depois de
gravar, rode `uv run spseg ingest` para aplicar a nova referência.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from spseg.analysis.aliases import (
    REASON_LABELS,
    derive_aliases,
    merge_alias_rows,
    read_alias_rows,
    write_alias_rows,
)
from spseg.config import Settings, get_settings
from spseg.data.cache import cached_years, read_facts
from spseg.data.reference import ALIASES_FILE, load_reference

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PROJECT_ROOT / "data" / "reference" / ALIASES_FILE


def _fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def _fmt_pct(value: float | None) -> str:
    if value is None:
        return "n/d"
    return f"{value * 100:.1f}%".replace(".", ",")


def _print_distribution(shares: tuple[float, ...]) -> None:
    if not shares:
        print("shares: nenhum grupo com coordenada")
        return
    series = pd.Series(shares)
    print(
        "shares dos grupos: "
        f"min {series.min():.2f} | p25 {series.quantile(0.25):.2f} | "
        f"p50 {series.median():.2f} | p90 {series.quantile(0.90):.2f} | "
        f"max {series.max():.2f}"
    )


def _print_rejected(report, limit: int) -> None:
    if not report.rejected:
        return
    print("\ngrafias rejeitadas com mais ocorrências:")
    ordered = sorted(report.rejected, key=lambda item: (-item.total, item.key))
    for item in ordered[:limit]:
        label = REASON_LABELS.get(item.reason, item.reason)
        print(
            f"  {item.raw} -> {item.bairro_id} | n={_fmt_int(item.n)} "
            f"share={_fmt_pct(item.share)} | {label}"
        )
    remaining = len(ordered) - min(limit, len(ordered))
    if remaining > 0:
        print(f"  ... e mais {remaining} grafias")


def _print_report(report, years: list[int], entries: int) -> None:
    print(f"cache: {_fmt_int(report.unresolved_rows)} linhas unresolved em {years}")
    print(f"referência: {entries} distritos")
    print(
        f"aliases derivados: {_fmt_int(len(report.derived))} | "
        f"rejeitados: {_fmt_int(len(report.rejected))}"
    )
    if report.rejected:
        counts: dict[str, int] = {}
        for item in report.rejected:
            counts[item.reason] = counts.get(item.reason, 0) + 1
        parts = ", ".join(
            f"{REASON_LABELS.get(reason, reason)}={_fmt_int(count)}"
            for reason, count in sorted(counts.items())
        )
        print(f"motivos: {parts}")
    _print_distribution(report.candidate_shares)
    print(
        "cobertura potencial dos unresolved: "
        f"{_fmt_int(report.covered_rows)}/{_fmt_int(report.unresolved_rows)} "
        f"({_fmt_pct(report.coverage)})"
    )


def _load_facts(settings: Settings, years: list[int] | None) -> tuple[pd.DataFrame, list[int]]:
    selected = years or cached_years(settings, "facts")
    if not selected:
        raise SystemExit("[erro] cache de fatos ausente. Rode `uv run spseg ingest` primeiro.")
    try:
        facts = read_facts(
            settings,
            years=selected,
            columns=["bairro_raw", "bairro_id", "bairro_method"],
        )
    except FileNotFoundError as exc:
        raise SystemExit(f"[erro] {exc}") from exc
    return facts, selected


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help=f"arquivo de saída (padrão: {DEFAULT_OUTPUT})",
    )
    parser.add_argument(
        "--ano",
        type=int,
        action="append",
        default=[],
        help="usa apenas estes anos do cache (repetível)",
    )
    parser.add_argument(
        "--min-n",
        type=int,
        default=5,
        help="mínimo de ocorrências geolocalizadas para gravar o alias (padrão: 5)",
    )
    parser.add_argument(
        "--min-share",
        type=float,
        default=0.85,
        help="share mínimo do distrito modal (padrão: 0.85)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="mostra o resultado sem gravar o arquivo",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=10,
        help="quantas grafias rejeitadas listar no relatório (padrão: 10)",
    )
    args = parser.parse_args(argv)

    if args.min_n < 1:
        parser.error("--min-n deve ser >= 1")
    if not 0 < args.min_share <= 1:
        parser.error("--min-share deve estar entre 0 e 1")
    if args.limit < 1:
        parser.error("--limit deve ser >= 1")

    settings = get_settings()
    settings.ensure_dirs()
    facts, selected = _load_facts(settings, args.ano or None)
    reference = load_reference(settings)
    report = derive_aliases(
        facts,
        reference.entries,
        min_n=args.min_n,
        min_share=args.min_share,
    )

    _print_report(report, selected, len(reference.entries))
    _print_rejected(report, args.limit)

    output = (args.output or settings.reference_dir / ALIASES_FILE).expanduser().resolve()
    if args.dry_run:
        print("\n[dry-run] arquivo não foi escrito.")
        return 0

    existing = read_alias_rows(output)
    rows = merge_alias_rows(existing, report.derived)
    written = write_alias_rows(output, rows)
    curated = sum(1 for row in rows if not row["fonte"].startswith("derivado:geo"))
    print(f"\n[ok] {written} aliases em {output} ({curated} curados preservados)")
    print("próximo passo: uv run spseg ingest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

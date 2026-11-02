"""Exportação do resumo em JSON."""

from __future__ import annotations

import json

from spseg.models import BairroSummary, CategorySummary


def _category_to_dict(category: CategorySummary) -> dict:
    return {
        "id": category.id,
        "label": category.label,
        "occurrences": category.occurrences,
        "incidents": category.incidents,
        "rate_per_100k": category.rate_per_100k,
        "rate_per_10k_households": category.rate_per_10k_households,
        "trend": category.trend,
        "trend_pct": category.trend_pct,
        "trend_note": category.trend_note,
        "top_natures": [
            {"natureza": name, "occurrences": count} for name, count in category.top_natures
        ],
    }


def summary_to_dict(summary: BairroSummary) -> dict:
    return {
        "bairro": summary.bairro_nome,
        "bairro_id": summary.bairro_id,
        "nivel": summary.nivel,
        "municipio": summary.municipio,
        "period": {
            "start": summary.period.start.isoformat(),
            "end": summary.period.end.isoformat(),
            "label": summary.period.label,
            "partial": summary.period.partial,
            "notes": list(summary.period.notes),
        },
        "population": summary.population,
        "households": summary.households,
        "denominator_level": summary.denominator_level,
        "denominator_source": summary.denominator_source,
        "totals": {
            "occurrences": summary.total_occurrences,
            "incidents": summary.total_incidents,
        },
        "categories": [_category_to_dict(category) for category in summary.categories],
        "quality": {
            "rows_in_bairro": summary.quality.rows_in_bairro,
            "method_counts": summary.quality.method_counts,
            "resolution_rate": summary.quality.resolution_rate,
            "suppressed_city": summary.quality.suppressed_city,
            "reference_status": summary.quality.reference_status,
            "notes": list(summary.quality.notes),
        },
        "taxonomy_provisional": summary.taxonomy_provisional,
        "generated_at": summary.generated_at.isoformat(timespec="seconds"),
    }


def summary_to_json(summary: BairroSummary, *, indent: int = 2) -> str:
    return json.dumps(summary_to_dict(summary), ensure_ascii=False, indent=indent)

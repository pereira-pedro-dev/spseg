"""Exportação do resumo em JSON."""

from __future__ import annotations

import json

from spseg.models import (
    BairroSummary,
    CategorySummary,
    DistrictCategoryContext,
    StreetCategory,
    StreetSummary,
)


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


def _street_category_to_dict(category: StreetCategory) -> dict:
    return {
        "id": category.id,
        "label": category.label,
        "occurrences": category.occurrences,
        "incidents": category.incidents,
        "share_of_street": category.share_of_street,
        "share_of_district": category.share_of_district,
        "district_visible_occurrences": category.district_visible_occurrences,
        "district_visible_incidents": category.district_visible_incidents,
        "top_natures": [
            {"natureza": name, "occurrences": count} for name, count in category.top_natures
        ],
    }


def _district_category_to_dict(category: DistrictCategoryContext) -> dict:
    return {
        "id": category.id,
        "label": category.label,
        "occurrences": category.occurrences,
        "incidents": category.incidents,
        "visible_occurrences": category.visible_occurrences,
        "visible_incidents": category.visible_incidents,
        "coverage": category.coverage,
        "not_visible_occurrences": category.not_visible_occurrences,
    }


def street_summary_to_dict(summary: StreetSummary) -> dict:
    """Contrato JSON do grão rua: sem população, taxas ou tendência."""
    quality = summary.quality
    return {
        "nivel": summary.nivel,
        "rua": summary.rua,
        "rua_raw": summary.rua_raw,
        "rua_key": summary.rua_key,
        "rua_tipo": summary.rua_tipo,
        "distrito": summary.distrito,
        "distrito_id": summary.distrito_id,
        "municipio": summary.municipio,
        "period": {
            "start": summary.period.start.isoformat(),
            "end": summary.period.end.isoformat(),
            "label": summary.period.label,
            "partial": summary.period.partial,
            "notes": list(summary.period.notes),
        },
        "totals": {
            "occurrences": summary.total_occurrences,
            "incidents": summary.total_incidents,
            "share_of_district": summary.share_of_district,
        },
        "district_context": {
            "occurrences": summary.district_total_occurrences,
            "incidents": summary.district_total_incidents,
            "visible_occurrences": summary.district_visible_occurrences,
            "visible_incidents": summary.district_visible_incidents,
            "coverage": summary.district_coverage,
            "not_visible_occurrences": quality.not_visible_occurrences,
            "not_visible_by_category": dict(summary.district_not_visible_by_category),
            "categories": [
                _district_category_to_dict(category) for category in summary.district_categories
            ],
        },
        "categories": [_street_category_to_dict(category) for category in summary.categories],
        "street_composition": {
            "top_natures": [
                {"natureza": name, "occurrences": count} for name, count in summary.top_natures
            ],
            "top_tipo_local": [
                {"tipo_local": name, "occurrences": count} for name, count in summary.top_tipo_local
            ],
        },
        "quality": {
            "rows_in_street": quality.rows_in_street,
            "rows_in_district": quality.rows_in_district,
            "rows_visible": quality.rows_visible,
            "suppressed_logradouro": quality.suppressed_logradouro,
            "missing_logradouro": quality.missing_logradouro,
            "not_visible_occurrences": quality.not_visible_occurrences,
            "district_method_counts": dict(quality.district_method_counts),
            "district_resolution_rate": quality.district_resolution_rate,
            "notes": list(quality.notes),
        },
        "taxonomy_provisional": summary.taxonomy_provisional,
        "generated_at": summary.generated_at.isoformat(timespec="seconds"),
    }


def street_summary_to_json(summary: StreetSummary, *, indent: int = 2) -> str:
    return json.dumps(street_summary_to_dict(summary), ensure_ascii=False, indent=indent)

"""Monta o `StreetSummary` a partir do cache de fatos + referência.

O grão é `(rua, distrito)`: a rua é resolvida dentro de um distrito já escolhido.
Não há taxa per capita/domicílio, tendência nem ranking.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from spseg.analysis.aggregate import total_incidents as count_incidents
from spseg.analysis.period import resolve_period
from spseg.analysis.summary import BairroNotFound, CacheMissing
from spseg.analysis.taxonomy import Taxonomy
from spseg.config import DEFAULT_MUNICIPIO, Settings
from spseg.data.cache import cached_years, load_manifest, read_facts
from spseg.data.reference import ReferenceData, load_reference
from spseg.data.schema import normalize_municipio
from spseg.geo.resolve import (
    BairroResolver,
    registry_from_entries_frame,
    registry_from_frame,
)
from spseg.geo.street import (
    StreetAmbiguous,
    StreetNotFound,
    display_street,
    display_street_name,
    find_street,
    normalize_street_key,
    street_suggestions,
    street_type,
)
from spseg.geo.text import suppressed_mask
from spseg.models import (
    DistrictCategoryContext,
    Period,
    StreetCategory,
    StreetQuality,
    StreetSummary,
)

RESOLVED_METHODS = {"exact", "alias", "fuzzy", "geo"}

# Categorias que não existem no grão rua: 100% das linhas têm logradouro e
# coordenada suprimidos. Só aparecem no contexto do distrito.
STREET_EXCLUDED_CATEGORIES = frozenset({"invasao_residencia", "violencia_sexual"})

SMALL_SAMPLE = 10
LIMITED_SAMPLE = 30
EQUIPMENT_SHARE_WARNING = 0.25

METHOD_LABELS = {
    "exact": "nome exato",
    "exact_sem_tipo": "nome exato sem tipo",
    "fuzzy": "nome aproximado",
}


class NoStreetData(LookupError):
    """O distrito não tem registros que possam ser analisados no grão rua."""

    def __init__(
        self,
        distrito: str,
        detail: str = "não tem registros com logradouro atribuível no período",
    ) -> None:
        self.distrito = distrito
        self.detail = detail
        super().__init__(f"O distrito {distrito} {detail}.")


def _district_entries(facts: pd.DataFrame, reference: ReferenceData):
    entries = registry_from_entries_frame(facts)
    if entries:
        return entries
    if reference.has_registry:
        return reference.entries
    return registry_from_frame(facts)


def _share(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return numerator / denominator


def _pct(value: float) -> str:
    return f"{value:.1%}".replace(".", ",")


def _top_counts(
    series: pd.Series | None,
    *,
    limit: int = 5,
    missing: str = "(sem informação)",
) -> tuple[tuple[str, int], ...]:
    if series is None or series.empty:
        return ()
    values = series.fillna(missing).astype("string")
    counts = values.value_counts().head(limit)
    return tuple((str(name), int(count)) for name, count in counts.items())


def _summarize_categories(
    street_frame: pd.DataFrame,
    visible_frame: pd.DataFrame,
    district_frame: pd.DataFrame,
    taxonomy: Taxonomy,
) -> tuple[tuple[StreetCategory, ...], tuple[DistrictCategoryContext, ...]]:
    street_total = len(street_frame)
    street_categories: list[StreetCategory] = []
    district_categories: list[DistrictCategoryContext] = []

    for category in taxonomy.categories:
        in_street = street_frame[street_frame["crime_category"] == category.id]
        in_visible = visible_frame[visible_frame["crime_category"] == category.id]
        in_district = district_frame[district_frame["crime_category"] == category.id]

        district_categories.append(
            DistrictCategoryContext(
                id=category.id,
                label=category.label,
                occurrences=len(in_district),
                incidents=count_incidents(in_district),
                visible_occurrences=len(in_visible),
                visible_incidents=count_incidents(in_visible),
                coverage=_share(len(in_visible), len(in_district)),
                not_visible_occurrences=len(in_district) - len(in_visible),
            )
        )

        if category.id in STREET_EXCLUDED_CATEGORIES:
            continue

        occurrences = len(in_street)
        street_categories.append(
            StreetCategory(
                id=category.id,
                label=category.label,
                occurrences=occurrences,
                incidents=count_incidents(in_street),
                share_of_street=_share(occurrences, street_total),
                share_of_district=_share(occurrences, len(in_visible)),
                district_visible_occurrences=len(in_visible),
                district_visible_incidents=count_incidents(in_visible),
                top_natures=_top_counts(
                    in_street["natureza"] if "natureza" in in_street.columns else None,
                    limit=3,
                    missing="(sem natureza)",
                ),
            )
        )

    return tuple(street_categories), tuple(district_categories)


def _not_visible_by_category(
    not_visible: pd.DataFrame,
    taxonomy: Taxonomy,
) -> dict[str, int]:
    if not_visible.empty:
        return {}
    categories = not_visible["crime_category"].astype("string")
    known = {category.id for category in taxonomy.categories}
    result: dict[str, int] = {}
    for category in taxonomy.categories:
        count = int((categories == category.id).sum())
        if count:
            result[category.id] = count
    unknown = int((~categories.isin(known)).sum())
    if unknown:
        result["(sem categoria)"] = unknown
    return result


@dataclass(frozen=True)
class StreetBinding:
    """Resultado comum da resolução `(rua, distrito)`, compartilhado pelas vistas.

    Contém o distrito, o período e o recorte de linhas da rua pronto para
    qualquer vista de rua (resumo ou lista de eventos), sem recalcular nada.
    """

    rua_query: str
    rua_nome: str
    rua_raw: str
    rua_key: str
    rua_tipo: str | None
    match_method: str
    distrito: str
    distrito_id: str | None
    municipio: str
    taxonomy: Taxonomy
    reference: ReferenceData
    reference_changed: bool
    period: Period
    street_frame: pd.DataFrame
    visible_frame: pd.DataFrame
    district_frame: pd.DataFrame
    suppressed_logradouro: int
    missing_logradouro: int
    district_method_counts: dict[str, int]
    district_resolution_rate: float | None


def build_street_binding(
    settings: Settings,
    rua: str,
    distrito: str,
    *,
    municipio: str = DEFAULT_MUNICIPIO,
    since: object = None,
    until: object = None,
    years: int | None = None,
    today: date | None = None,
) -> StreetBinding:
    """Resolve `(rua, distrito)` e devolve o recorte de linhas da rua.

    Erros possíveis: `CacheMissing` (sem cache), `BairroNotFound`,
    `StreetNotFound`, `StreetAmbiguous`, `NoStreetData` e `ValueError`.
    """
    if not cached_years(settings, "facts"):
        raise CacheMissing(
            "Nenhum cache encontrado. Rode `uv run spseg ingest` antes de consultar."
        )

    facts = read_facts(settings)
    target_municipio = normalize_municipio(municipio)
    if "municipio" in facts.columns:
        facts = facts[facts["municipio"] == target_municipio]
    if facts.empty:
        raise CacheMissing(f"Não há registros para o município '{municipio}' no cache.")

    manifest = load_manifest(settings)
    reference = load_reference(settings)
    reference_changed = bool(
        reference.has_registry and reference.version != manifest.get("reference_version")
    )
    taxonomy = reference.taxonomy
    if taxonomy is None:  # pragma: no cover - load_reference sempre devolve taxonomia
        raise RuntimeError("Taxonomia indisponível.")

    entries = _district_entries(facts, reference)
    resolver = BairroResolver(entries, aliases=reference.aliases)
    district_hit = resolver.find(distrito)
    if district_hit is None:
        raise BairroNotFound(distrito, resolver.suggestions(distrito))
    entry, _district_method, _confidence = district_hit

    if "crime_category" not in facts.columns:
        facts["crime_category"] = taxonomy.classify(facts)
    elif facts["crime_category"].isna().any():
        facts["crime_category"] = facts["crime_category"].fillna(taxonomy.default_category.id)

    period = resolve_period(
        facts["data_ocorrencia"],
        since=since,
        until=until,
        years=years,
        today=today,
        coverage_start=facts["data_registro"].min() if "data_registro" in facts.columns else None,
        coverage_end=facts["data_registro"].max() if "data_registro" in facts.columns else None,
    )
    dates = pd.to_datetime(facts["data_ocorrencia"], errors="coerce")
    in_period = (dates >= pd.Timestamp(period.start)) & (
        dates < pd.Timestamp(period.end) + pd.Timedelta(days=1)
    )
    district_frame = facts[in_period & (facts["bairro_id"] == entry.bairro_id)].copy()
    if district_frame.empty:
        raise NoStreetData(entry.bairro_nome, "não tem registros no período")
    if "logradouro" not in district_frame.columns:
        raise NoStreetData(
            entry.bairro_nome,
            "não tem a coluna `logradouro` no cache; reingira os dados",
        )

    raw_text = district_frame["logradouro"].astype("string").str.strip().fillna("")
    suppressed = suppressed_mask(raw_text)
    missing = raw_text.eq("")
    valid_mask = (~suppressed) & (~missing)
    eligible = ~district_frame["crime_category"].isin(STREET_EXCLUDED_CATEGORIES)

    valid_raw = raw_text[valid_mask]
    key_by_raw = {value: normalize_street_key(value) for value in valid_raw.unique()}
    keys = pd.Series("", index=district_frame.index, dtype="string")
    keys.loc[valid_mask] = valid_raw.map(key_by_raw).astype("string")

    district_frame["_rua_raw"] = raw_text
    district_frame["_rua_key"] = keys
    visible_mask = valid_mask & eligible & keys.ne("")
    visible_frame = district_frame[visible_mask]

    if visible_frame.empty:
        raise NoStreetData(entry.bairro_nome)

    keys_unique = tuple(str(key) for key in visible_frame["_rua_key"].unique() if key)
    try:
        match = find_street(rua, keys_unique, distrito=entry.bairro_nome)
    except StreetAmbiguous as exc:
        counts = {key: int((visible_frame["_rua_key"] == key).sum()) for key in exc.candidates}
        raise StreetAmbiguous(
            exc.query,
            exc.candidates,
            entry.bairro_nome,
            counts=counts,
        ) from exc
    if match is None:
        suggestions = [
            (display_street(key), score) for key, score in street_suggestions(rua, keys_unique)
        ]
        raise StreetNotFound(rua, entry.bairro_nome, suggestions)

    street_frame = visible_frame[visible_frame["_rua_key"] == match.key]
    raw_choices = street_frame["_rua_raw"].dropna().astype("string")
    rua_raw = str(raw_choices.value_counts().index[0]) if not raw_choices.empty else match.key

    if "bairro_method" in district_frame.columns:
        district_method_counts = {
            str(method): int(count)
            for method, count in district_frame["bairro_method"].value_counts().items()
        }
    else:
        district_method_counts = {}
    district_resolution_rate = _share(
        sum(district_method_counts.get(method, 0) for method in RESOLVED_METHODS),
        len(district_frame),
    )

    return StreetBinding(
        rua_query=rua,
        rua_nome=display_street_name(match.key),
        rua_raw=rua_raw,
        rua_key=match.key,
        rua_tipo=street_type(match.key),
        match_method=match.method,
        distrito=entry.bairro_nome,
        distrito_id=entry.distrito_id or entry.bairro_id,
        municipio=municipio,
        taxonomy=taxonomy,
        reference=reference,
        reference_changed=reference_changed,
        period=period,
        street_frame=street_frame,
        visible_frame=visible_frame,
        district_frame=district_frame,
        suppressed_logradouro=int(suppressed.sum()),
        missing_logradouro=int(missing.sum()),
        district_method_counts=district_method_counts,
        district_resolution_rate=district_resolution_rate,
    )


def build_street_summary(
    settings: Settings,
    rua: str,
    distrito: str,
    *,
    municipio: str = DEFAULT_MUNICIPIO,
    since: object = None,
    until: object = None,
    years: int | None = None,
    today: date | None = None,
) -> StreetSummary:
    binding = build_street_binding(
        settings,
        rua,
        distrito,
        municipio=municipio,
        since=since,
        until=until,
        years=years,
        today=today,
    )
    street_frame = binding.street_frame
    visible_frame = binding.visible_frame
    district_frame = binding.district_frame

    categories, district_categories = _summarize_categories(
        street_frame, visible_frame, district_frame, binding.taxonomy
    )

    total_occurrences = len(street_frame)
    total_incidents = count_incidents(street_frame)
    district_total_occurrences = len(district_frame)
    district_total_incidents = count_incidents(district_frame)
    district_visible_occurrences = len(visible_frame)
    district_visible_incidents = count_incidents(visible_frame)
    district_coverage = _share(district_visible_occurrences, district_total_occurrences)

    not_visible_mask = ~district_frame.index.isin(visible_frame.index)
    not_visible = district_frame[not_visible_mask]
    not_visible_by_category = _not_visible_by_category(not_visible, binding.taxonomy)

    district_method_counts = binding.district_method_counts
    district_resolution_rate = binding.district_resolution_rate

    top_natures = _top_counts(
        street_frame["natureza"] if "natureza" in street_frame.columns else None,
        limit=5,
        missing="(sem natureza)",
    )
    top_tipo_local = _top_counts(
        street_frame["tipo_local"] if "tipo_local" in street_frame.columns else None,
        limit=5,
        missing="(sem tipo)",
    )

    notes: list[str] = [
        "Grão rua: mede crimes registrados em espaço público no logradouro. "
        "Invasão de residência e violência sexual têm logradouro suprimido em 100% "
        "dos casos e não aparecem na rua; veja o contexto do distrito. Não mede "
        "risco do imóvel.",
        "A participação no distrito usa como denominador o total da categoria no "
        "distrito com rua atribuível, não o total do distrito.",
    ]
    if district_coverage is not None:
        notes.append(
            f"{_pct(district_coverage)} dos registros do distrito no período têm rua "
            "atribuível; os demais não entram nos percentuais."
        )
        if district_coverage < 0.98:
            notes.append("As contagens da rua são piso em relação ao total do distrito.")
    if district_resolution_rate is not None and district_resolution_rate < 0.98:
        notes.append(
            f"A resolução do distrito no período é de {_pct(district_resolution_rate)}; "
            "as contagens do distrito (e da rua) são piso."
        )

    notes.extend(binding.period.notes)
    years_cached = cached_years(settings, "facts")
    if len(years_cached) < 3:
        notes.append(
            "cache cobre apenas "
            + ", ".join(str(year) for year in years_cached)
            + "; períodos e comparações ficam incompletos até os outros anos serem ingeridos."
        )
    if binding.match_method != "exact":
        label = METHOD_LABELS.get(binding.match_method, binding.match_method)
        notes.append(f"'{rua}' interpretado como '{display_street(binding.rua_key)}' ({label}).")
    if binding.reference.status.issues:
        notes.extend(binding.reference.status.issues)
    if binding.reference_changed:
        notes.append(
            "A referência mudou desde o último `ingest`; rode novamente para "
            "aplicar aliases/população novas."
        )

    months = max(1, round(binding.period.months))
    if total_occurrences < SMALL_SAMPLE:
        notes.append(
            f"n pequeno ({total_occurrences} registros em {months} meses): use apenas "
            "como indício, não como ranking."
        )
    elif total_occurrences < LIMITED_SAMPLE:
        notes.append(
            f"amostra limitada ({total_occurrences} registros em {months} meses): "
            "diferenças de poucos casos não são interpretáveis."
        )

    if top_tipo_local and total_occurrences:
        top_tipo, top_count = top_tipo_local[0]
        share = top_count / total_occurrences
        if (
            top_tipo not in {"Via Pública", "(sem tipo)", "(sem informação)"}
            and share >= EQUIPMENT_SHARE_WARNING
        ):
            notes.append(
                f"{_pct(share)} dos registros da rua são em '{top_tipo}'; a contagem "
                "pode refletir o equipamento, não a rua residencial."
            )

    if "tipo_local" in street_frame.columns and not street_frame.empty:
        missing_tipo = float(street_frame["tipo_local"].isna().mean())
        if missing_tipo >= 0.25:
            notes.append(
                f"tipo de local ausente em {_pct(missing_tipo)} dos registros da rua; "
                "a composição por tipo fica incompleta."
            )
    if binding.taxonomy.provisional:
        notes.append(
            "Taxonomia provisória: as categorias ainda não foram validadas "
            "na sessão de metodologia."
        )

    quality = StreetQuality(
        rows_in_street=total_occurrences,
        rows_in_district=district_total_occurrences,
        rows_visible=district_visible_occurrences,
        suppressed_logradouro=binding.suppressed_logradouro,
        missing_logradouro=binding.missing_logradouro,
        not_visible_occurrences=district_total_occurrences - district_visible_occurrences,
        district_method_counts=district_method_counts,
        district_resolution_rate=district_resolution_rate,
        notes=tuple(notes),
    )

    return StreetSummary(
        rua=binding.rua_nome,
        rua_raw=binding.rua_raw,
        rua_key=binding.rua_key,
        rua_tipo=binding.rua_tipo,
        distrito=binding.distrito,
        distrito_id=binding.distrito_id,
        municipio=binding.municipio,
        period=binding.period,
        total_occurrences=total_occurrences,
        total_incidents=total_incidents,
        share_of_district=_share(total_occurrences, district_visible_occurrences),
        district_total_occurrences=district_total_occurrences,
        district_total_incidents=district_total_incidents,
        district_visible_occurrences=district_visible_occurrences,
        district_visible_incidents=district_visible_incidents,
        district_coverage=district_coverage,
        district_not_visible_by_category=not_visible_by_category,
        categories=categories,
        district_categories=district_categories,
        top_natures=top_natures,
        top_tipo_local=top_tipo_local,
        quality=quality,
        taxonomy_provisional=binding.taxonomy.provisional,
        generated_at=datetime.now(),
    )


__all__ = [
    "EQUIPMENT_SHARE_WARNING",
    "LIMITED_SAMPLE",
    "METHOD_LABELS",
    "NoStreetData",
    "SMALL_SAMPLE",
    "STREET_EXCLUDED_CATEGORIES",
    "StreetBinding",
    "build_street_binding",
    "build_street_summary",
]

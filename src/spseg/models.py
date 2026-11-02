"""Modelos de domínio compartilhados entre análise e renderização."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime


@dataclass(frozen=True)
class Period:
    start: date
    end: date
    label: str
    partial: bool = False
    notes: tuple[str, ...] = ()

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    @property
    def months(self) -> float:
        return self.days / 30.4375


@dataclass(frozen=True)
class Resolution:
    bairro_id: str | None
    bairro_nome: str | None
    method: str
    confidence: float = 0.0

    @property
    def resolved(self) -> bool:
        return self.bairro_id is not None


@dataclass(frozen=True)
class RegistryEntry:
    bairro_id: str
    bairro_nome: str
    distrito_id: str | None = None

    @property
    def key(self) -> str:
        from spseg.geo.text import normalize_key

        return normalize_key(self.bairro_nome)


@dataclass(frozen=True)
class CategorySummary:
    id: str
    label: str
    occurrences: int
    incidents: int
    rate_per_100k: float | None = None
    rate_per_10k_households: float | None = None
    trend: str | None = None
    trend_pct: float | None = None
    trend_note: str | None = None
    top_natures: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class QualityFlags:
    rows_in_bairro: int = 0
    method_counts: dict[str, int] = field(default_factory=dict)
    resolution_rate: float | None = None
    suppressed_city: int = 0
    reference_status: dict[str, bool] = field(default_factory=dict)
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class BairroSummary:
    bairro_nome: str
    bairro_id: str
    municipio: str
    period: Period
    total_occurrences: int
    total_incidents: int
    population: int | None
    households: int | None
    denominator_level: str | None
    categories: tuple[CategorySummary, ...]
    quality: QualityFlags
    taxonomy_provisional: bool
    generated_at: datetime
    nivel: str = "distrito"
    denominator_source: str | None = None


@dataclass(frozen=True)
class StreetCategory:
    """Categoria elegível ao grão rua; sem taxa e sem tendência."""

    id: str
    label: str
    occurrences: int
    incidents: int
    share_of_street: float | None = None
    share_of_district: float | None = None
    district_visible_occurrences: int = 0
    district_visible_incidents: int = 0
    top_natures: tuple[tuple[str, int], ...] = ()


@dataclass(frozen=True)
class DistrictCategoryContext:
    """Categoria no distrito inteiro, incluindo o que não tem rua atribuível."""

    id: str
    label: str
    occurrences: int
    incidents: int
    visible_occurrences: int
    visible_incidents: int
    coverage: float | None = None
    not_visible_occurrences: int = 0


@dataclass(frozen=True)
class StreetQuality:
    rows_in_street: int = 0
    rows_in_district: int = 0
    rows_visible: int = 0
    suppressed_logradouro: int = 0
    missing_logradouro: int = 0
    not_visible_occurrences: int = 0
    district_method_counts: dict[str, int] = field(default_factory=dict)
    district_resolution_rate: float | None = None
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class StreetSummary:
    rua: str
    rua_raw: str
    rua_key: str
    rua_tipo: str | None
    distrito: str
    distrito_id: str | None
    municipio: str
    period: Period
    total_occurrences: int
    total_incidents: int
    share_of_district: float | None
    district_total_occurrences: int
    district_total_incidents: int
    district_visible_occurrences: int
    district_visible_incidents: int
    district_coverage: float | None
    district_not_visible_by_category: dict[str, int]
    categories: tuple[StreetCategory, ...]
    district_categories: tuple[DistrictCategoryContext, ...]
    top_natures: tuple[tuple[str, int], ...]
    top_tipo_local: tuple[tuple[str, int], ...]
    quality: StreetQuality
    taxonomy_provisional: bool
    generated_at: datetime
    nivel: str = "rua"

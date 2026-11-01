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

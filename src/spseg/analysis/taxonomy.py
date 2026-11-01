"""Regras de agrupamento de naturezas criminais.

A taxonomia é editável em `data/reference/crime_taxonomy.yml`. As regras abaixo
são PROVISÓRIAS: servem para a base funcionar antes da sessão de metodologia.
Cada registro entra em exatamente uma categoria (a primeira que casar, por
prioridade), para que as categorias não se sobreponham.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

DEFAULT_CATEGORY_ID = "outros"


@dataclass(frozen=True)
class Rule:
    natureza_in: tuple[str, ...] = ()
    tipo_local_in: tuple[str, ...] = ()
    conduta_contains: tuple[str, ...] = ()

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Rule:
        return cls(
            natureza_in=_upper_tuple(data.get("natureza") or data.get("natureza_in")),
            tipo_local_in=_upper_tuple(data.get("tipo_local") or data.get("tipo_local_in")),
            conduta_contains=_upper_tuple(
                data.get("conduta_contem") or data.get("conduta_contains")
            ),
        )


@dataclass(frozen=True)
class Category:
    id: str
    label: str
    priority: int = 100
    rules: tuple[Rule, ...] = ()
    is_default: bool = False


@dataclass
class Taxonomy:
    categories: tuple[Category, ...]
    provisional: bool = True
    source: str | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        self.categories = tuple(sorted(self.categories, key=lambda c: (c.priority, c.id)))

    @property
    def default_category(self) -> Category:
        for category in self.categories:
            if category.is_default:
                return category
        return self.categories[-1]

    def label(self, category_id: str) -> str:
        for category in self.categories:
            if category.id == category_id:
                return category.label
        return category_id

    def classify(self, frame: pd.DataFrame) -> pd.Series:
        natureza = _upper_series(frame.get("natureza"))
        tipo_local = _upper_series(frame.get("tipo_local"))
        conduta = _upper_series(frame.get("conduta"))
        result = pd.Series(self.default_category.id, index=frame.index, dtype="string")
        assigned = pd.Series(False, index=frame.index)

        for category in self.categories:
            if category.is_default:
                continue
            mask = pd.Series(False, index=frame.index)
            for rule in category.rules:
                rule_mask = pd.Series(True, index=frame.index)
                if rule.natureza_in:
                    rule_mask &= natureza.isin(rule.natureza_in)
                if rule.tipo_local_in:
                    rule_mask &= tipo_local.isin(rule.tipo_local_in)
                if rule.conduta_contains:
                    conduta_mask = pd.Series(False, index=frame.index)
                    for needle in rule.conduta_contains:
                        conduta_mask |= conduta.str.contains(needle, regex=False, na=False)
                    rule_mask &= conduta_mask
                mask |= rule_mask
            take = mask & ~assigned
            result[take] = category.id
            assigned |= take
        return result


def _upper_tuple(value: Any) -> tuple[str, ...]:
    if not value:
        return ()
    if isinstance(value, str):
        value = [value]
    return tuple(str(item).strip().upper() for item in value if str(item).strip())


def _upper_series(series: pd.Series | None) -> pd.Series:
    if series is None:
        return pd.Series(dtype="string")
    return series.fillna("").astype("string").str.upper().str.strip()


_RESIDENTIAL = (
    "RESIDÊNCIA",
    "RESIDENCIA",
    "CONDOMÍNIO RESIDENCIAL",
    "CONDOMINIO RESIDENCIAL",
    "FAVELA",
)

DEFAULT_TAXONOMY_DATA: dict[str, Any] = {
    "versao": 1,
    "provisorio": True,
    "nota": (
        "Regras provisórias, pendentes da sessão de metodologia. "
        "Cada registro entra em uma única categoria, por ordem de prioridade."
    ),
    "categorias": [
        {
            "id": "invasao_residencia",
            "rotulo": "Invasão de residência",
            "prioridade": 10,
            "regras": [
                {
                    "tipo_local": list(_RESIDENTIAL),
                    "natureza": [
                        "FURTO - OUTROS",
                        "FURTO DE VEÍCULO",
                        "FURTO DE CARGA",
                        "ROUBO - OUTROS",
                        "ROUBO DE VEÍCULO",
                        "ROUBO DE CARGA",
                        "HOMICÍDIO DOLOSO",
                        "TENTATIVA DE HOMICÍDIO",
                        "LESÃO CORPORAL DOLOSA",
                        "LESÃO CORPORAL SEGUIDA DE MORTE",
                        "LATROCÍNIO",
                        "ESTUPRO",
                        "ESTUPRO DE VULNERÁVEL",
                        "EXTORSÃO MEDIANTE SEQUESTRO",
                    ],
                }
            ],
        },
        {
            "id": "violencia_sexual",
            "rotulo": "Violência sexual",
            "prioridade": 20,
            "regras": [{"natureza": ["ESTUPRO", "ESTUPRO DE VULNERÁVEL"]}],
        },
        {
            "id": "crime_violento",
            "rotulo": "Crimes violentos",
            "prioridade": 30,
            "regras": [
                {
                    "natureza": [
                        "HOMICÍDIO DOLOSO",
                        "TENTATIVA DE HOMICÍDIO",
                        "LATROCÍNIO",
                        "LESÃO CORPORAL DOLOSA",
                        "LESÃO CORPORAL SEGUIDA DE MORTE",
                        "ROUBO - OUTROS",
                        "ROUBO DE VEÍCULO",
                        "ROUBO DE CARGA",
                        "EXTORSÃO MEDIANTE SEQUESTRO",
                    ]
                }
            ],
        },
        {
            "id": "crime_nao_violento",
            "rotulo": "Crimes não violentos",
            "prioridade": 40,
            "regras": [{"natureza": ["FURTO - OUTROS", "FURTO DE VEÍCULO", "FURTO DE CARGA"]}],
        },
        {
            "id": DEFAULT_CATEGORY_ID,
            "rotulo": "Outros (drogas, armas, trânsito)",
            "prioridade": 999,
            "padrao": True,
            "regras": [],
        },
    ],
}


def taxonomy_from_dict(data: dict[str, Any], *, source: str | None = None) -> Taxonomy:
    categories: list[Category] = []
    for item in data.get("categorias", []):
        categories.append(
            Category(
                id=str(item["id"]).strip(),
                label=str(item.get("rotulo") or item.get("label") or item["id"]).strip(),
                priority=int(item.get("prioridade") or item.get("priority") or 100),
                rules=tuple(Rule.from_dict(rule) for rule in item.get("regras") or []),
                is_default=bool(item.get("padrao") or item.get("default")),
            )
        )
    if not categories:
        raise ValueError("Taxonomia sem categorias.")
    if not any(c.is_default for c in categories):
        categories.append(Category(DEFAULT_CATEGORY_ID, "Outros", 999, (), True))
    return Taxonomy(
        categories=tuple(categories),
        provisional=bool(data.get("provisorio", True)),
        source=source,
        note=data.get("nota"),
    )


def load_taxonomy(path: Path | None = None) -> tuple[Taxonomy, list[str]]:
    """Carrega o YAML; se ausente ou inválido, usa a taxonomia provisória embutida."""
    issues: list[str] = []
    if path is not None and Path(path).exists():
        try:
            payload = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
            return taxonomy_from_dict(payload, source=str(path)), issues
        except (OSError, yaml.YAMLError, KeyError, TypeError, ValueError) as exc:
            issues.append(f"Taxonomia inválida em {path}: {exc}. Usando a padrão provisória.")
    return taxonomy_from_dict(DEFAULT_TAXONOMY_DATA, source=None), issues

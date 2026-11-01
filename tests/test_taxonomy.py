"""Taxonomia provisória: prioridade, regras e fallback."""

from __future__ import annotations

import pandas as pd

from spseg.analysis.taxonomy import (
    DEFAULT_CATEGORY_ID,
    DEFAULT_TAXONOMY_DATA,
    load_taxonomy,
    taxonomy_from_dict,
)


def _classify(taxonomy, rows: list[dict]) -> list[str]:
    frame = pd.DataFrame(rows)
    return taxonomy.classify(frame).tolist()


def test_default_taxonomy_is_provisional_and_has_default_category():
    taxonomy = taxonomy_from_dict(DEFAULT_TAXONOMY_DATA)
    assert taxonomy.provisional is True
    assert taxonomy.default_category.id == DEFAULT_CATEGORY_ID


def test_categories_are_sorted_by_priority():
    taxonomy = taxonomy_from_dict(DEFAULT_TAXONOMY_DATA)
    priorities = [category.priority for category in taxonomy.categories]
    assert priorities == sorted(priorities)


def test_priority_gives_residential_invasion_precedence():
    taxonomy = taxonomy_from_dict(DEFAULT_TAXONOMY_DATA)
    result = _classify(
        taxonomy,
        [
            {"natureza": "ESTUPRO", "tipo_local": "Residência", "conduta": ""},
            {"natureza": "ESTUPRO", "tipo_local": "Via Pública", "conduta": ""},
        ],
    )
    assert result == ["invasao_residencia", "violencia_sexual"]


def test_violent_and_non_violent_crimes():
    taxonomy = taxonomy_from_dict(DEFAULT_TAXONOMY_DATA)
    result = _classify(
        taxonomy,
        [
            {"natureza": "ROUBO - OUTROS", "tipo_local": "Via Pública", "conduta": ""},
            {"natureza": "FURTO - OUTROS", "tipo_local": "Via Pública", "conduta": ""},
            {"natureza": "PORTE DE ARMA", "tipo_local": "Via Pública", "conduta": ""},
        ],
    )
    assert result == ["crime_violento", "crime_nao_violento", "outros"]


def test_labels_come_from_reference():
    taxonomy = taxonomy_from_dict(
        {
            "provisorio": False,
            "categorias": [
                {
                    "id": "x",
                    "rotulo": "Categoria X",
                    "prioridade": 1,
                    "regras": [{"conduta_contem": ["ARMA"]}],
                },
                {"id": "outros", "rotulo": "Outros", "prioridade": 99, "padrao": True},
            ],
        }
    )
    assert taxonomy.label("x") == "Categoria X"
    assert _classify(
        taxonomy, [{"natureza": "QUALQUER", "tipo_local": "", "conduta": "com arma"}]
    ) == ["x"]


def test_load_taxonomy_missing_file_falls_back_to_provisional(tmp_path):
    taxonomy, issues = load_taxonomy(tmp_path / "nao_existe.yml")
    assert issues == []
    assert taxonomy.provisional is True
    assert taxonomy.source is None


def test_load_taxonomy_invalid_yaml_reports_issue(tmp_path):
    path = tmp_path / "crime_taxonomy.yml"
    path.write_text("categorias: [", encoding="utf-8")
    taxonomy, issues = load_taxonomy(path)
    assert issues
    assert taxonomy.provisional is True


def test_load_taxonomy_reads_valid_file(tmp_path):
    path = tmp_path / "crime_taxonomy.yml"
    path.write_text(
        "provisorio: false\n"
        "categorias:\n"
        "  - id: unico\n"
        "    rotulo: Único\n"
        "    prioridade: 1\n"
        "    regras: [{natureza: [FURTO - OUTROS]}]\n"
        "  - id: outros\n"
        "    rotulo: Outros\n"
        "    prioridade: 9\n"
        "    padrao: true\n",
        encoding="utf-8",
    )
    taxonomy, issues = load_taxonomy(path)
    assert issues == []
    assert taxonomy.provisional is False
    assert taxonomy.source == str(path)
    assert taxonomy.label("unico") == "Único"

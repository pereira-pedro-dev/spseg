"""CLI: ajuda, doctor, list, check e bairro (texto e JSON)."""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from spseg.cli import app
from tests.helpers import make_facts, make_street_facts, write_facts, write_population

runner = CliRunner()


def _seed(settings) -> None:
    write_facts(settings, make_facts(), 2024)


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("ingest", "check", "list", "bairro", "distrito", "rua", "doctor"):
        assert command in result.output


def test_doctor_without_cache(settings):
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "ausente" in result.output


def test_doctor_with_cache(settings):
    _seed(settings)
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "2024" in result.output
    assert "distritos=" in result.output


def test_list_bairros(settings):
    _seed(settings)
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0
    assert "Distritos disponíveis" in result.output


def test_list_search_does_not_fail(settings):
    _seed(settings)
    result = runner.invoke(app, ["list", "--search", "pin"])
    assert result.exit_code == 0


def test_check_from_cache(settings):
    _seed(settings)
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 0


def test_check_without_cache_exits_3(settings):
    result = runner.invoke(app, ["check"])
    assert result.exit_code == 3


def test_bairro_json_output(settings):
    _seed(settings)
    result = runner.invoke(app, ["bairro", "Pinheiros", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["bairro"] == "Pinheiros"
    assert payload["bairro_id"] == "pinheiros"
    assert payload["nivel"] == "distrito"
    assert payload["totals"]["occurrences"] == 60
    assert payload["taxonomy_provisional"] is True
    assert payload["period"]["start"] == "2024-02-01"


def test_bairro_json_includes_denominators(settings):
    _seed(settings)
    write_population(settings)
    result = runner.invoke(app, ["bairro", "Pinheiros", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["population"] == 100_000
    assert payload["households"] == 50_000
    assert payload["denominator_level"] == "bairro"
    assert payload["denominator_source"] == "Censo teste"


def test_distrito_command_matches_bairro(settings):
    _seed(settings)
    via_bairro = runner.invoke(app, ["bairro", "Pinheiros", "--json"])
    via_distrito = runner.invoke(app, ["distrito", "Pinheiros", "--json"])
    assert via_bairro.exit_code == 0
    assert via_distrito.exit_code == 0
    left = json.loads(via_bairro.output)
    right = json.loads(via_distrito.output)
    left.pop("generated_at")
    right.pop("generated_at")
    assert left == right


def test_bairro_text_output(settings):
    _seed(settings)
    result = runner.invoke(app, ["bairro", "Pinheiros"])
    assert result.exit_code == 0


def test_bairro_not_found_exits_2(settings):
    _seed(settings)
    result = runner.invoke(app, ["bairro", "ZZZZZZZZ", "--json"])
    assert result.exit_code == 2


def test_bairro_without_cache_exits_3(settings):
    result = runner.invoke(app, ["bairro", "Pinheiros", "--json"])
    assert result.exit_code == 3


def test_bairro_invalid_date_exits_1(settings):
    _seed(settings)
    result = runner.invoke(app, ["bairro", "Pinheiros", "--desde", "31/01/2025"])
    assert result.exit_code == 1


def test_bairro_period_options(settings):
    _seed(settings)
    result = runner.invoke(
        app,
        [
            "bairro",
            "Pinheiros",
            "--desde",
            "2025-01-01",
            "--ate",
            "2025-12-31",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["period"]["start"] == "2025-01-01"
    assert payload["period"]["end"] == "2025-12-31"


def test_ingest_without_raw_files_exits_1(settings):
    result = runner.invoke(app, ["ingest"])
    assert result.exit_code == 1


def _seed_street(settings) -> None:
    write_facts(settings, make_street_facts(), 2024)


def test_rua_json_output(settings):
    _seed_street(settings)
    result = runner.invoke(app, ["rua", "Mourato Coelho", "--distrito", "Pinheiros", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["nivel"] == "rua"
    assert payload["rua"] == "Mourato Coelho"
    assert payload["rua_raw"] == "RUA MOURATO COELHO"
    assert payload["rua_key"] == "RUA MOURATO COELHO"
    assert payload["rua_tipo"] == "RUA"
    assert payload["distrito"] == "Pinheiros"
    assert payload["totals"]["occurrences"] == 8
    assert payload["totals"]["incidents"] == 7
    assert payload["totals"]["share_of_district"] == pytest.approx(8 / 13)
    assert payload["district_context"]["occurrences"] == 18
    assert payload["district_context"]["visible_occurrences"] == 13
    assert payload["district_context"]["not_visible_occurrences"] == 5
    assert "population" not in payload
    assert "households" not in payload
    assert "trend" not in payload
    assert "rate_per_100k" not in json.dumps(payload)


def test_rua_json_category_contract(settings):
    _seed_street(settings)
    result = runner.invoke(app, ["rua", "Mourato Coelho", "--distrito", "Pinheiros", "--json"])
    payload = json.loads(result.output)
    categories = {category["id"]: category for category in payload["categories"]}
    assert set(categories) == {"crime_violento", "crime_nao_violento", "outros"}
    violent = categories["crime_violento"]
    assert violent["occurrences"] == 3
    assert violent["share_of_district"] == pytest.approx(3 / 4)
    assert violent["share_of_street"] == pytest.approx(3 / 8)
    context = {category["id"]: category for category in payload["district_context"]["categories"]}
    assert context["invasao_residencia"]["visible_occurrences"] == 0
    assert context["violencia_sexual"]["coverage"] == 0.0
    assert payload["street_composition"]["top_tipo_local"][0] == {
        "tipo_local": "Via Pública",
        "occurrences": 6,
    }


def test_rua_text_output(settings):
    _seed_street(settings)
    result = runner.invoke(app, ["rua", "Mourato Coelho", "--distrito", "Pinheiros"])
    assert result.exit_code == 0
    output = result.output
    assert "Resumo de segurança — rua" in output
    assert "Crimes violentos" in output
    assert "% do distrito" in output
    assert "Não mede risco do imóvel" in output
    assert "Contexto do distrito" in output
    assert "Composição da rua" in output
    assert "Terminal/Estação" not in output


def test_rua_requires_distrito(settings):
    _seed_street(settings)
    result = runner.invoke(app, ["rua", "Mourato Coelho"])
    assert result.exit_code == 2


def test_rua_not_found_exits_2(settings):
    _seed_street(settings)
    result = runner.invoke(app, ["rua", "Mourato", "--distrito", "Pinheiros"])
    assert result.exit_code == 2
    assert "Rua não encontrada" in result.output


def test_rua_district_not_found_exits_2(settings):
    _seed_street(settings)
    result = runner.invoke(app, ["rua", "Mourato Coelho", "--distrito", "ZZZZZZZZ"])
    assert result.exit_code == 2
    assert "Distrito não encontrado" in result.output


def test_rua_without_cache_exits_3(settings):
    result = runner.invoke(app, ["rua", "Mourato Coelho", "--distrito", "Pinheiros"])
    assert result.exit_code == 3


def test_rua_ambiguous_exits_2(settings):
    import pandas as pd

    frame = make_street_facts()
    extra = frame.iloc[[0, 0]].copy()
    extra["logradouro"] = ["RUA PAULISTA", "AVENIDA PAULISTA"]
    extra["bo_key"] = ["2024/BO901", "2024/BO902"]
    write_facts(settings, pd.concat([frame, extra], ignore_index=True), 2024)

    result = runner.invoke(app, ["rua", "Paulista", "--distrito", "Pinheiros"])
    assert result.exit_code == 2
    assert "Mais de uma rua" in result.output
    assert "Rua Paulista" in result.output
    assert "Avenida Paulista" in result.output


def test_rua_same_street_two_districts(settings):
    import pandas as pd

    frame = make_street_facts()
    extra = frame.iloc[[0]].copy()
    extra["bairro_raw"] = "Vila Mariana"
    extra["bairro_nome"] = "Vila Mariana"
    extra["bairro_id"] = "vila-mariana"
    extra["distrito_id"] = "vila-mariana"
    extra["bo_key"] = "2024/BO902"
    write_facts(settings, pd.concat([frame, extra], ignore_index=True), 2024)

    pinheiros = runner.invoke(app, ["rua", "Mourato Coelho", "--distrito", "Pinheiros", "--json"])
    vila_mariana = runner.invoke(
        app, ["rua", "Mourato Coelho", "--distrito", "Vila Mariana", "--json"]
    )
    assert pinheiros.exit_code == 0
    assert vila_mariana.exit_code == 0
    assert json.loads(pinheiros.output)["totals"]["occurrences"] == 8
    assert json.loads(vila_mariana.output)["totals"]["occurrences"] == 1

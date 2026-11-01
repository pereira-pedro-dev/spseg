"""CLI: ajuda, doctor, list, check e bairro (texto e JSON)."""

from __future__ import annotations

import json

from typer.testing import CliRunner

from spseg.cli import app
from tests.helpers import make_facts, write_facts

runner = CliRunner()


def _seed(settings) -> None:
    write_facts(settings, make_facts(), 2024)


def test_help_lists_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("ingest", "check", "list", "bairro", "doctor"):
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


def test_list_bairros(settings):
    _seed(settings)
    result = runner.invoke(app, ["list"])
    assert result.exit_code == 0


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
    assert payload["totals"]["occurrences"] == 60
    assert payload["taxonomy_provisional"] is True
    assert payload["period"]["start"] == "2024-02-01"


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

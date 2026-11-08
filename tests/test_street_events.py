"""Lista de eventos por rua: linhas simples, horários e política de `n/d`."""

from __future__ import annotations

import json

import pytest

from spseg.analysis.street_events import build_street_events
from spseg.geo.street import StreetNotFound
from tests.helpers import make_street_facts, write_facts, write_population, write_taxonomy


def _seed(settings) -> None:
    write_facts(settings, make_street_facts(), 2024)
    write_population(settings)
    write_taxonomy(settings)


def test_events_lists_every_row_sorted(settings):
    _seed(settings)
    events = build_street_events(settings, "Mourato Coelho", "Pinheiros", today=None)
    assert events.nivel == "rua-eventos"
    assert events.rua == "Mourato Coelho"
    assert events.rua_raw == "RUA MOURATO COELHO"
    assert events.total_occurrences == 8
    assert events.total_incidents == 7  # BO004 aparece em duas linhas
    assert len(events.events) == 8
    # Ordenação cronológica por hora (todas as datas são iguais no fixture).
    horas = [event.hora for event in events.events]
    assert horas == [
        "00:05",
        "02:10",
        "07:15",
        "07:15",
        "12:30",
        "18:45",
        "23:40",
        None,
    ]
    first = events.events[0]
    assert first.categoria == "Crimes não violentos"
    assert first.natureza == "FURTO - OUTROS"
    assert first.tipo_local == "Via Pública"


def test_hour_buckets_and_missing_hour(settings):
    _seed(settings)
    events = build_street_events(settings, "Mourato Coelho", "Pinheiros")
    by_id = {bucket.id: bucket for bucket in events.hour_buckets}
    assert by_id["madrugada"].occurrences == 2
    assert by_id["madrugada"].violent == 1
    assert by_id["manha"].occurrences == 2
    assert by_id["manha"].violent == 0
    assert by_id["tarde"].occurrences == 1
    assert by_id["tarde"].violent == 1  # homicídio às 12:30
    assert by_id["noite"].occurrences == 2
    assert by_id["noite"].violent == 1
    assert events.events_without_hour == 1


def test_excluded_categories_never_appear(settings):
    _seed(settings)
    events = build_street_events(settings, "Mourato Coelho", "Pinheiros")
    json_text = json.dumps(events, default=str, ensure_ascii=False)
    assert "invasao_residencia" not in json_text
    assert "violencia_sexual" not in json_text
    assert "ESTUPRO" not in json_text


def test_limite_truncates_chronologically(settings):
    _seed(settings)
    events = build_street_events(settings, "Mourato Coelho", "Pinheiros", limite=3)
    assert len(events.events) == 3
    assert events.dropped_events == 5
    assert events.total_occurrences == 8
    assert events.events[0].hora == "00:05"


def test_limite_greater_than_total_is_noop(settings):
    _seed(settings)
    events = build_street_events(settings, "Mourato Coelho", "Pinheiros", limite=100)
    assert len(events.events) == 8
    assert events.dropped_events == 0


def test_street_without_hours_is_all_n_d(settings):
    _seed(settings)
    events = build_street_events(settings, "Capri", "Pinheiros")
    assert events.total_occurrences == 5
    assert events.events_without_hour == 5
    assert all(bucket.occurrences == 0 for bucket in events.hour_buckets)
    assert all(event.hora is None for event in events.events)


def test_unknown_street_raises_street_not_found(settings):
    _seed(settings)
    with pytest.raises(StreetNotFound, match="Rua Que Não Existe"):
        build_street_events(settings, "Rua Que Não Existe", "Pinheiros")


def test_json_contract(settings):
    _seed(settings)
    from spseg.render.export import street_events_to_dict, street_events_to_json

    events = build_street_events(settings, "Mourato Coelho", "Pinheiros")
    payload = json.loads(street_events_to_json(events))
    assert payload["nivel"] == "rua-eventos"
    assert payload["rua"] == "Mourato Coelho"
    assert payload["distrito"] == "Pinheiros"
    assert payload["totals"] == {"occurrences": 8, "incidents": 7}
    bucket_ids = {bucket["id"] for bucket in payload["hour_buckets"]}
    assert bucket_ids == {"madrugada", "manha", "tarde", "noite"}
    assert payload["events_without_hour"] == 1
    assert payload["dropped_events"] == 0
    first = payload["events"][0]
    assert first == {
        "data": events.events[0].data.isoformat(),
        "hora": "00:05",
        "categoria_id": "crime_nao_violento",
        "categoria": "Crimes não violentos",
        "natureza": "FURTO - OUTROS",
        "tipo_local": "Via Pública",
    }
    assert street_events_to_dict(events)["period"]["partial"] is False

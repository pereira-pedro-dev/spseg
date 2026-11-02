"""Normalização e resolução de ruas."""

from __future__ import annotations

import pytest

from spseg.geo.street import (
    StreetAmbiguous,
    display_street,
    display_street_name,
    find_street,
    normalize_street_key,
    street_suggestions,
    street_type,
    strip_street_type,
)

KEYS = {
    "RUA MOURATO COELHO",
    "AVENIDA CAPRI",
    "AVENIDA PAULISTA",
    "RUA PAULISTA",
}


def test_normalize_canonical_type():
    assert normalize_street_key("R. Augusta") == "RUA AUGUSTA"
    assert normalize_street_key("RUA AUGUSTA") == "RUA AUGUSTA"
    assert normalize_street_key("Rua Augusta") == "RUA AUGUSTA"
    assert normalize_street_key("AV. PAULISTA") == "AVENIDA PAULISTA"


def test_normalize_expands_honorifics():
    assert (
        normalize_street_key("AV. BRIG. FARIA LIMA")
        == "AVENIDA BRIGADEIRO FARIA LIMA"
        == normalize_street_key("Avenida Brigadeiro Faria Lima")
    )
    assert normalize_street_key("R. DR. X") == "RUA DOUTOR X"


def test_normalize_removes_only_trailing_door_number():
    assert normalize_street_key("RUA VINTE E CINCO DE MARÇO, 641") == ("RUA VINTE E CINCO DE MARCO")
    assert normalize_street_key("RUA X, Nº 123") == "RUA X"
    assert normalize_street_key("RUA X Nº 123") == "RUA X"
    assert normalize_street_key("AVENIDA 23 DE MAIO") == "AVENIDA 23 DE MAIO"
    assert normalize_street_key("RUA 7 DE ABRIL") == "RUA 7 DE ABRIL"


def test_type_helpers():
    assert street_type("RUA AUGUSTA") == "RUA"
    assert street_type("AUGUSTA") is None
    assert strip_street_type("AVENIDA BRIGADEIRO FARIA LIMA") == "BRIGADEIRO FARIA LIMA"
    assert strip_street_type("AUGUSTA") == "AUGUSTA"


def test_display_names():
    assert display_street_name("RUA MOURATO COELHO") == "Mourato Coelho"
    assert display_street_name("AVENIDA BRIGADEIRO FARIA LIMA") == ("Brigadeiro Faria Lima")
    assert display_street("RUA MOURATO COELHO") == "Rua Mourato Coelho"
    assert display_street("AVENIDA BRIGADEIRO FARIA LIMA") == ("Avenida Brigadeiro Faria Lima")


def test_find_exact_and_without_type():
    assert find_street("Rua Mourato Coelho", KEYS).key == "RUA MOURATO COELHO"
    match = find_street("Mourato Coelho", KEYS)
    assert match.key == "RUA MOURATO COELHO"
    assert match.method == "exact_sem_tipo"


def test_find_does_not_cross_street_types():
    assert find_street("Rua Paulista", {"AVENIDA PAULISTA"}) is None
    assert find_street("Avenida Paulista", {"RUA PAULISTA"}) is None


def test_find_ambiguous_without_type():
    with pytest.raises(StreetAmbiguous) as info:
        find_street("Paulista", KEYS, distrito="Pinheiros")
    assert info.value.candidates == ("AVENIDA PAULISTA", "RUA PAULISTA")
    assert info.value.distrito == "Pinheiros"


def test_find_fuzzy():
    match = find_street("Mourato Coehlo", KEYS)
    assert match.key == "RUA MOURATO COELHO"
    assert match.method == "fuzzy"
    assert match.confidence >= 0.92


def test_find_not_found():
    assert find_street("Rua Inexistente", KEYS) is None


def test_suggestions_stay_in_district():
    suggestions = street_suggestions("Mourato", KEYS)
    assert suggestions
    assert suggestions[0][0] == "RUA MOURATO COELHO"
    assert all(key in KEYS for key, _score in suggestions)

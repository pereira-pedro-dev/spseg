"""Normalização de texto usada na resolução de bairros."""

from __future__ import annotations

import math

import pandas as pd

from spseg.geo.text import (
    is_suppressed,
    looks_like_mojibake,
    normalize_key,
    slugify,
    strip_accents,
    suppressed_mask,
)


def test_normalize_key_handles_accents_case_and_punctuation():
    assert normalize_key("  São   Paulo!! ") == "SAO PAULO"
    assert normalize_key("são paulo") == "SAO PAULO"


def test_normalize_key_expands_common_abbreviations():
    assert normalize_key("Jd. Paulista") == "JARDIM PAULISTA"
    assert normalize_key("Vl Mariana") == "VILA MARIANA"
    assert normalize_key("Pq. Ibirapuera") == "PARQUE IBIRAPUERA"
    assert normalize_key("Sta Cecília") == "SANTA CECILIA"


def test_normalize_key_empty_values():
    assert normalize_key(None) == ""
    assert normalize_key("") == ""
    assert normalize_key(float("nan")) == ""
    assert normalize_key(math.nan) == ""


def test_strip_accents_keeps_letters():
    assert strip_accents("Ação") == "Acao"


def test_is_suppressed_detects_the_ssp_marker():
    assert is_suppressed("VEDAÇÃO DA DIVULGAÇÃO")
    assert is_suppressed("vedacao da divulgacao")
    assert not is_suppressed("Pinheiros")
    assert not is_suppressed(None)


def test_suppressed_mask_is_vectorized_and_boolean():
    series = pd.Series(["VEDAÇÃO DA DIVULGAÇÃO", "Pinheiros", None, ""])
    mask = suppressed_mask(series)
    assert mask.dtype == bool
    assert mask.tolist() == [True, False, False, False]


def test_looks_like_mojibake():
    assert looks_like_mojibake("SÃ\u0093o")
    assert not looks_like_mojibake("São Paulo")


def test_slugify():
    assert slugify("SAO PAULO") == "sao-paulo"
    assert slugify("  VILA  MARIANA ") == "vila-mariana"

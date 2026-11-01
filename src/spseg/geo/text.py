"""Normalização de texto para comparação de bairros.

Nada aqui altera os dados originais: serve para gerar chaves de comparação.
"""

from __future__ import annotations

import re
import unicodedata

import pandas as pd

from spseg.config import SUPPRESSED_MARKER

# Abreviações comuns nos registros da SSP. A expansão é aplicada por token,
# apenas na chave de comparação.
ABBREVIATIONS: dict[str, str] = {
    "JD": "JARDIM",
    "JDM": "JARDIM",
    "VL": "VILA",
    "PQ": "PARQUE",
    "PQUE": "PARQUE",
    "PCA": "PRACA",
    "PÇA": "PRACA",
    "STA": "SANTA",
    "STO": "SANTO",
    "CONJ": "CONJUNTO",
    "RES": "RESIDENCIAL",
    "NUC": "NUCLEO",
    "DIST": "DISTRITO",
}

_PUNCTUATION_RE = re.compile(r"[^A-Z0-9 ]+")
_SPACES_RE = re.compile(r"\s+")
_MOJIBAKE_RE = re.compile(r"Ã[\x80-\xBF]|Â[\x80-\xBF]")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


_SUPPRESSED_KEY = strip_accents(SUPPRESSED_MARKER).upper()


def normalize_key(value: object) -> str:
    """Chave de comparação: sem acento, maiúscula, sem pontuação, abreviações expandidas."""
    if value is None:
        return ""
    if isinstance(value, float) and value != value:  # NaN sem importar pandas
        return ""
    text = strip_accents(str(value)).upper()
    text = _PUNCTUATION_RE.sub(" ", text)
    text = _SPACES_RE.sub(" ", text).strip()
    if not text:
        return ""
    tokens = [ABBREVIATIONS.get(token, token) for token in text.split(" ")]
    return " ".join(tokens)


def is_suppressed(value: object) -> bool:
    """A SSP troca o local por um aviso de vedação em registros sensíveis."""
    if value is None:
        return False
    if isinstance(value, float) and value != value:
        return False
    return strip_accents(str(value)).upper().find(_SUPPRESSED_KEY) >= 0


def suppressed_mask(series: pd.Series) -> pd.Series:
    """Versão vetorizada de `is_suppressed`, segura para dtype `string`."""
    return pd.Series([is_suppressed(value) for value in series], index=series.index, dtype=bool)


def looks_like_mojibake(text: str) -> bool:
    """Heurística para UTF-8 lido como Latin-1 (bug de leitura, não sujeira real)."""
    return bool(_MOJIBAKE_RE.search(text))


def slugify(key: str) -> str:
    return _SPACES_RE.sub("-", key.strip().lower())

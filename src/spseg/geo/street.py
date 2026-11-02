"""Normalização e resolução de nomes de rua (`logradouro` da SSP).

O nome da rua já existe no cache de fatos. Este módulo só cria uma chave de
comparação estável e resolve a consulta do usuário dentro de um distrito. Nada
aqui altera os dados originais.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from spseg.config import FUZZY_MARGIN, FUZZY_SUGGESTION_LIMIT, FUZZY_THRESHOLD
from spseg.geo.text import normalize_key

# Tipos de logradouro canônicos. O tipo faz parte da identidade: "Rua Paulista"
# e "Avenida Paulista" são vias diferentes.
STREET_TYPE_ALIASES: dict[str, str] = {
    "R": "RUA",
    "RUA": "RUA",
    "AV": "AVENIDA",
    "AVE": "AVENIDA",
    "AVENIDA": "AVENIDA",
    "AL": "ALAMEDA",
    "ALAMEDA": "ALAMEDA",
    "TV": "TRAVESSA",
    "TRAVESSA": "TRAVESSA",
    "PC": "PRACA",
    "PCA": "PRACA",
    "PRACA": "PRACA",
    "EST": "ESTRADA",
    "ESTRADA": "ESTRADA",
    "ROD": "RODOVIA",
    "RODOVIA": "RODOVIA",
    "LGO": "LARGO",
    "LARGO": "LARGO",
    "VDA": "VIELA",
    "VIELA": "VIELA",
    "VIA": "VIA",
    "V": "VIA",
}

STREET_TYPE_DISPLAY: dict[str, str] = {
    "RUA": "Rua",
    "AVENIDA": "Avenida",
    "ALAMEDA": "Alameda",
    "TRAVESSA": "Travessa",
    "PRACA": "Praça",
    "ESTRADA": "Estrada",
    "RODOVIA": "Rodovia",
    "LARGO": "Largo",
    "VIELA": "Viela",
    "VIA": "Via",
}

# Honoríficos frequentes nos logradouros da SSP. Expandir só na chave de
# comparação evita fragmentar "AV. BRIG. FARIA LIMA" e "AVENIDA BRIGADEIRO
# FARIA LIMA" em duas séries.
HONORIFICS: dict[str, str] = {
    "BRIG": "BRIGADEIRO",
    "GEN": "GENERAL",
    "MAL": "MARECHAL",
    "ALM": "ALMIRANTE",
    "CEL": "CORONEL",
    "CAP": "CAPITAO",
    "DR": "DOUTOR",
    "DRA": "DOUTORA",
    "PROF": "PROFESSOR",
    "ENG": "ENGENHEIRO",
    "ARQ": "ARQUITETO",
    "DEP": "DEPUTADO",
    "SEN": "SENADOR",
    "GOV": "GOVERNADOR",
    "PRES": "PRESIDENTE",
    "MIN": "MINISTRO",
    "VISC": "VISCONDE",
}

CONNECTORS = frozenset({"de", "da", "do", "das", "dos", "e"})

# Só remove número de porta no fim, com vírgula ou "Nº". Números no início do
# nome ("AVENIDA 23 DE MAIO", "RUA 7 DE ABRIL") são parte do nome.
_SUFFIX_COMMA_RE = re.compile(r"\s*,\s*(?:N[Oº°]?\.?\s*)?\d+[A-Za-z]?\s*$", re.IGNORECASE)
_SUFFIX_NUMERO_RE = re.compile(r"\s+N[Oº°]\.?\s*\d+[A-Za-z]?\s*$", re.IGNORECASE)


class StreetNotFound(LookupError):
    """A rua não existe no distrito/período consultado."""

    def __init__(
        self,
        query: str,
        distrito: str,
        suggestions: list[tuple[str, float]] | None = None,
    ) -> None:
        self.query = query
        self.distrito = distrito
        self.suggestions = suggestions or []
        super().__init__(f"Rua não encontrada em {distrito}: {query}")


class StreetAmbiguous(LookupError):
    """Mais de uma rua do distrito casa com a consulta sem tipo."""

    def __init__(
        self,
        query: str,
        candidates: tuple[str, ...],
        distrito: str | None = None,
        counts: dict[str, int] | None = None,
    ) -> None:
        self.query = query
        self.candidates = candidates
        self.distrito = distrito
        self.counts = counts or {}
        where = f" em {distrito}" if distrito else ""
        super().__init__(f"Mais de uma rua corresponde a {query}{where}")


@dataclass(frozen=True)
class StreetMatch:
    key: str
    method: str
    confidence: float = 1.0


def _clean_raw(value: object) -> str:
    if value is None:
        return ""
    try:
        if value != value:  # NaN, sem importar pandas
            return ""
    except (TypeError, ValueError):
        pass
    text = str(value).strip()
    if text.lower() in {"nan", "none", "<na>"}:
        return ""
    return text


def _strip_unit_suffix(value: object) -> str:
    text = _clean_raw(value)
    if not text:
        return ""
    text = _SUFFIX_COMMA_RE.sub("", text)
    text = _SUFFIX_NUMERO_RE.sub("", text)
    return text.strip()


def normalize_street_key(value: object) -> str:
    """Chave de comparação da rua: tipo canônico, honoríficos e sem número de porta."""
    text = _strip_unit_suffix(value)
    if not text:
        return ""
    key = normalize_key(text)
    if not key:
        return ""
    tokens = [HONORIFICS.get(token, token) for token in key.split()]
    if not tokens:
        return ""
    canonical_type = STREET_TYPE_ALIASES.get(tokens[0])
    if canonical_type is not None:
        tokens[0] = canonical_type
    return " ".join(tokens)


def street_type(key: str) -> str | None:
    """Tipo canônico da chave, ou `None` quando o nome não começa com tipo."""
    if not key:
        return None
    first = normalize_street_key(key).split(" ", 1)[0]
    return first if first in STREET_TYPE_DISPLAY else None


def strip_street_type(key: str) -> str:
    """Remove o tipo canônico do início da chave."""
    if not key:
        return ""
    normalized = normalize_street_key(key)
    head, _, tail = normalized.partition(" ")
    if head in STREET_TYPE_DISPLAY:
        return tail.strip()
    return normalized


def titlecase_street(text: str) -> str:
    """Title case simples, com conectores (`de`, `da`, `dos`, `e`) em minúscula."""
    words = [word for word in text.lower().split() if word]
    return " ".join(word if word in CONNECTORS else word.capitalize() for word in words)


def display_street_name(key: str) -> str:
    """Nome da rua sem o tipo, para o campo `rua` da saída."""
    return titlecase_street(strip_street_type(key))


def display_street(key: str) -> str:
    """Nome completo para sugestões e desambiguação (ex.: `Rua Augusta`)."""
    normalized = normalize_street_key(key) or key.strip()
    tipo = street_type(normalized)
    name = display_street_name(normalized)
    if tipo:
        prefix = STREET_TYPE_DISPLAY.get(tipo, titlecase_street(tipo))
        return f"{prefix} {name}".strip()
    return name


def _unique_keys(keys: Iterable[str]) -> tuple[str, ...]:
    seen: dict[str, None] = {}
    for key in keys:
        if key:
            seen.setdefault(str(key), None)
    return tuple(seen)


def _fuzzy(
    query: str,
    candidates: tuple[str, ...],
    threshold: float,
    margin: float,
) -> StreetMatch | None:
    """Fuzzy com limiar e margem; nunca cruza tipos de logradouro."""
    query_type = street_type(query)
    pool = candidates
    if query_type is not None:
        same_type = tuple(key for key in candidates if street_type(key) == query_type)
        if not same_type:
            return None
        pool = same_type
    matches = process.extract(query, pool, scorer=fuzz.WRatio, limit=2)
    if not matches:
        return None
    best_key, best_score, _ = matches[0]
    if best_score < threshold:
        return None
    if len(matches) > 1 and (best_score - matches[1][1]) < margin:
        return None
    return StreetMatch(str(best_key), "fuzzy", float(best_score) / 100.0)


def find_street(
    query: str,
    keys: Iterable[str],
    *,
    distrito: str | None = None,
    threshold: float = FUZZY_THRESHOLD,
    margin: float = FUZZY_MARGIN,
) -> StreetMatch | None:
    """Resolve uma rua dentro do conjunto de chaves de um distrito.

    Ordem: exata com tipo -> exata sem tipo (só quando a consulta não tem tipo)
    -> fuzzy com limiar/margem. Consulta sem tipo que casa com mais de um tipo
    levanta `StreetAmbiguous`; o chamador lista os candidatos.
    """
    candidates = _unique_keys(keys)
    frame = normalize_street_key(query)
    if not candidates or not frame:
        return None

    if frame in set(candidates):
        return StreetMatch(frame, "exact", 1.0)

    query_type = street_type(frame)
    if query_type is None:
        stripped_query = strip_street_type(frame)
        same_name = tuple(key for key in candidates if strip_street_type(key) == stripped_query)
        if len(same_name) == 1:
            return StreetMatch(same_name[0], "exact_sem_tipo", 1.0)
        if len(same_name) > 1:
            raise StreetAmbiguous(query, tuple(sorted(same_name)), distrito)

    fuzzy_hit = _fuzzy(frame, candidates, threshold, margin)
    if fuzzy_hit is not None:
        return fuzzy_hit

    # A segunda passada só faz sentido quando a consulta não fixou um tipo.
    # Se o usuário escreveu "Rua Paulista", não podemos devolver a Avenida
    # Paulista só porque o nome restante é igual.
    if query_type is None:
        stripped_query = strip_street_type(frame)
        stripped_candidates = _unique_keys(strip_street_type(key) for key in candidates)
        if stripped_query and stripped_candidates:
            stripped_hit = _fuzzy(stripped_query, stripped_candidates, threshold, margin)
            if stripped_hit is not None:
                full = tuple(
                    key for key in candidates if strip_street_type(key) == stripped_hit.key
                )
                if len(full) == 1:
                    return StreetMatch(full[0], "fuzzy", stripped_hit.confidence)
                if len(full) > 1:
                    raise StreetAmbiguous(query, tuple(sorted(full)), distrito)
    return None


def street_suggestions(
    query: str,
    keys: Iterable[str],
    *,
    limit: int = FUZZY_SUGGESTION_LIMIT,
) -> list[tuple[str, float]]:
    """Sugestões de rua dentro do distrito, ordenadas por similaridade."""
    candidates = _unique_keys(keys)
    frame = normalize_street_key(query)
    if not candidates or not frame:
        return []
    matches = process.extract(
        frame,
        candidates,
        scorer=fuzz.WRatio,
        limit=limit,
        score_cutoff=60,
    )
    return [(str(key), float(score)) for key, score, _ in matches]


__all__ = [
    "HONORIFICS",
    "STREET_TYPE_ALIASES",
    "STREET_TYPE_DISPLAY",
    "StreetAmbiguous",
    "StreetMatch",
    "StreetNotFound",
    "display_street",
    "display_street_name",
    "find_street",
    "normalize_street_key",
    "street_suggestions",
    "street_type",
    "strip_street_type",
    "titlecase_street",
]

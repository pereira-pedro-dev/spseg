"""Caminhos, constantes e configuração do projeto."""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MUNICIPIO = "São Paulo"
DEFAULT_MUNICIPIO_KEY = "SAO PAULO"
DEFAULT_YEARS = 3

SCHEMA_VERSION = 2
FUZZY_THRESHOLD = 92.0
FUZZY_MARGIN = 4.0
FUZZY_SUGGESTION_LIMIT = 5

# Limites aproximados do estado de São Paulo.
LAT_MIN, LAT_MAX = -26.0, -19.0
LON_MIN, LON_MAX = -54.0, -43.0

# A SSP substitui o local por este texto em registros sensíveis.
SUPPRESSED_MARKER = "VEDAÇÃO DA DIVULGAÇÃO"

DATA_FILES_GLOB = "SPDadosCriminais_*.xlsx"


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    raw_dir: Path
    cache_dir: Path
    reference_dir: Path

    @classmethod
    def create(cls, data_dir: Path) -> Settings:
        data_dir = data_dir.expanduser().resolve()
        return cls(
            data_dir=data_dir,
            raw_dir=data_dir / "raw",
            cache_dir=data_dir / "cache",
            reference_dir=data_dir / "reference",
        )

    @property
    def raw_cache_dir(self) -> Path:
        return self.cache_dir / "raw"

    @property
    def facts_cache_dir(self) -> Path:
        return self.cache_dir / "facts"

    @property
    def manifest_path(self) -> Path:
        return self.cache_dir / "manifest.json"

    def ensure_dirs(self) -> None:
        for directory in (
            self.data_dir,
            self.raw_dir,
            self.cache_dir,
            self.raw_cache_dir,
            self.facts_cache_dir,
            self.reference_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Configuração global. `SPSEG_DATA_DIR` permite apontar para outro diretório."""
    env = os.environ.get("SPSEG_DATA_DIR")
    data_dir = Path(env) if env else PROJECT_ROOT / "data"
    return Settings.create(data_dir)

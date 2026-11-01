"""Leitura das planilhas da SSP (`.xlsx`), sem nenhuma regra de análise."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pandas as pd

from spseg.data.schema import (
    canonicalize_columns,
    filter_municipio,
    normalize_header,
)

Progress = Callable[[str], None]


def _noop(message: str) -> None:
    return None


def discover_data_sheets(sheet_names: list[str]) -> list[str]:
    """A primeira aba é o dicionário de campos ("CAMPOS...")."""
    data = [name for name in sheet_names if not normalize_header(name).startswith("CAMPOS")]
    if data:
        return data
    return sheet_names[1:] if len(sheet_names) > 1 else []


def read_workbook(
    path: Path,
    *,
    municipio: str | None = None,
    sheets: list[str] | None = None,
    progress: Progress | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Lê todas as abas de dados de um workbook e devolve (DataFrame canônico, avisos)."""
    log = progress or _noop
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {path}")

    excel = pd.ExcelFile(path, engine="openpyxl")
    try:
        selected = sheets or discover_data_sheets(excel.sheet_names)
        if not selected:
            raise ValueError(f"{path.name}: nenhuma aba de dados encontrada em {excel.sheet_names}")

        frames: list[pd.DataFrame] = []
        warnings: list[str] = []
        for sheet in selected:
            log(f"  lendo aba '{sheet}'...")
            raw = pd.read_excel(excel, sheet_name=sheet, engine="openpyxl")
            frame, frame_warnings = canonicalize_columns(raw, source=f"{path.name}:{sheet}")
            frame["source_file"] = path.name
            frame["source_sheet"] = sheet
            frames.append(frame)
            warnings.extend(frame_warnings)
            log(f"    {len(frame):,} linhas".replace(",", "."))

        data = pd.concat(frames, ignore_index=True)
    finally:
        excel.close()

    if municipio is not None:
        before = len(data)
        data = filter_municipio(data, municipio)
        log(
            f"  filtro município '{municipio}': {before:,} -> {len(data):,} linhas".replace(
                ",", "."
            )
        )

    return data.reset_index(drop=True), warnings

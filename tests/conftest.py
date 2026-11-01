"""Fixtures compartilhadas."""

from __future__ import annotations

import pytest

from spseg.config import get_settings


@pytest.fixture
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("SPSEG_DATA_DIR", str(tmp_path / "data"))
    get_settings.cache_clear()
    current = get_settings()
    current.ensure_dirs()
    yield current
    get_settings.cache_clear()

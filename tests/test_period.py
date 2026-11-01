"""Janela temporal: padrão, recortes, cobertura e ano parcial."""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from spseg.analysis.period import resolve_period, shift_years
from spseg.models import Period


@pytest.fixture
def dates() -> pd.Series:
    return pd.Series(pd.to_datetime(["2024-01-15", "2024-06-01", "2025-03-10", "2026-09-30"]))


def _resolve(dates, **kwargs):
    return resolve_period(
        dates,
        today=date(2026, 11, 1),
        coverage_start=date(2024, 1, 1),
        coverage_end=date(2026, 9, 30),
        **kwargs,
    )


def test_default_uses_registration_coverage(dates):
    period = _resolve(dates)
    assert period.start == date(2024, 1, 1)
    assert period.end == date(2026, 9, 30)
    assert period.partial is True
    assert any("incompleto" in note for note in period.notes)
    assert any("cobertura" in note for note in period.notes)


def test_years_window_is_clipped_to_coverage(dates):
    period = _resolve(dates, years=3)
    assert period.start == date(2024, 1, 1)
    assert period.end == date(2026, 9, 30)
    assert any("antes da base" in note for note in period.notes)


def test_explicit_window_within_coverage(dates):
    period = _resolve(dates, since=date(2025, 1, 1), until=date(2025, 12, 31))
    assert period.start == date(2025, 1, 1)
    assert period.end == date(2025, 12, 31)
    assert period.partial is False


def test_end_after_coverage_is_clipped(dates):
    period = _resolve(dates, until=date(2027, 1, 1))
    assert period.end == date(2026, 9, 30)
    assert any("depois da base" in note for note in period.notes)


def test_empty_window_raises(dates):
    with pytest.raises(ValueError, match="Período vazio"):
        _resolve(dates, since=date(2026, 1, 1), until=date(2025, 1, 1))


def test_invalid_dates_raise():
    with pytest.raises(ValueError, match="datas"):
        resolve_period(pd.Series([pd.NaT, None]))


def test_shift_years_handles_leap_day():
    assert shift_years(date(2024, 2, 29), 1) == date(2025, 2, 28)
    assert shift_years(date(2024, 2, 29), 4) == date(2028, 2, 29)


def test_period_derived_values():
    period = Period(start=date(2024, 1, 1), end=date(2024, 1, 31), label="teste")
    assert period.days == 31
    assert 1.0 < period.months < 1.1

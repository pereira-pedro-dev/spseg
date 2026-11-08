"""Lista de eventos de uma rua no grão `(rua, distrito)`.

Complementa o `spseg rua` quando `n` é pequeno: mostra cada registro
(ocorrência × natureza) com data, hora, categoria, natureza e tipo de local,
mais a distribuição por horário do dia. Política de `n/d`: `hora_ocorrencia`
ausente ou inválida fica fora das faixas e é contada em "sem hora" — nunca é
inventado nem chutado.
"""

from __future__ import annotations

import re
from datetime import datetime

import pandas as pd

from spseg.analysis.aggregate import total_incidents as count_incidents
from spseg.analysis.street_summary import (
    NoStreetData,
    StreetBinding,
    build_street_binding,
)
from spseg.config import DEFAULT_MUNICIPIO, Settings
from spseg.models import EventDetail, HourBucket, StreetEvents

# Warn at this many events; the console suggests narrowing the window.
STREET_EVENTS_WARN_LIMIT = 60

HOUR_PATTERN = re.compile(r"^(\d{1,2}):(\d{2})")

VIOLENT_CATEGORY_ID = "crime_violento"

HOUR_BUCKETS: tuple[tuple[str, str, int, int], ...] = (
    ("madrugada", "Madrugada (00–05h)", 0, 5),
    ("manha", "Manhã (06–11h)", 6, 11),
    ("tarde", "Tarde (12–17h)", 12, 17),
    ("noite", "Noite (18–23h)", 18, 23),
)

UNKNOWN_HOUR = 24  # sort key: events without hour go last within the same date


def parse_clock(value: object) -> tuple[int, int] | None:
    """`HH:MM[:SS]` → (hora, minuto); ausente/inválido → None (nunca chutado)."""
    if value is None or pd.isna(value):
        return None
    match = HOUR_PATTERN.match(str(value).strip())
    if match is None:
        return None
    hour = int(match.group(1))
    minute = int(match.group(2))
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        return None
    return hour, minute


def _bucket_for(hour: int) -> tuple[str, str]:
    for bucket_id, label, start, end in HOUR_BUCKETS:
        if start <= hour <= end:
            return bucket_id, label
    return "", ""  # unreachable: hour is validated between 0 and 23


def _clean(value: object, missing: str) -> str:
    if value is None or pd.isna(value):
        return missing
    text = str(value).strip()
    return text if text else missing


def build_street_events(
    settings: Settings,
    rua: str,
    distrito: str,
    *,
    municipio: str = DEFAULT_MUNICIPIO,
    since: object = None,
    until: object = None,
    years: int | None = None,
    today: object = None,
    limite: int | None = None,
) -> StreetEvents:
    """Resolve e lista os eventos de `(rua, distrito)` na janela.

    `limite` (opcional) trunca a lista em ordem cronológica; `dropped_events`
    informa quantos ficaram de fora. Sem limite, tudo é devolvido.
    """
    binding: StreetBinding = build_street_binding(
        settings,
        rua,
        distrito,
        municipio=municipio,
        since=since,
        until=until,
        years=years,
        today=today,
    )
    frame = binding.street_frame
    if frame.empty:  # pragma: no cover - street_frame nunca vazio após o binding
        raise NoStreetData(binding.distrito)

    labels = {category.id: category.label for category in binding.taxonomy.categories}

    records: list[tuple[tuple, EventDetail, str, bool]] = []
    for index in frame.index:
        clock = (
            parse_clock(frame.at[index, "hora_ocorrencia"])
            if "hora_ocorrencia" in frame.columns
            else None
        )
        timestamp = pd.to_datetime(frame.at[index, "data_ocorrencia"], errors="coerce")
        if pd.isna(timestamp):
            continue  # sem data não é evento listável; contagem fica consistente
        category_id = _clean(frame.at[index, "crime_category"], "(sem categoria)")
        event = EventDetail(
            data=pd.Timestamp(timestamp).date(),
            hora=f"{clock[0]:02d}:{clock[1]:02d}" if clock else None,
            categoria_id=category_id,
            categoria=labels.get(category_id, category_id),
            natureza=_clean(frame.at[index, "natureza"], "(sem natureza)"),
            tipo_local=_clean(frame.at[index, "tipo_local"], "(sem tipo)"),
        )
        if clock is None:
            sort_key = (event.data, UNKNOWN_HOUR, 99, event.natureza)
            bucket_id = ""
        else:
            sort_key = (event.data, clock[0], clock[1], event.natureza)
            bucket_id = _bucket_for(clock[0])[0]
        records.append((sort_key, event, bucket_id, category_id == VIOLENT_CATEGORY_ID))

    order = sorted(range(len(records)), key=lambda i: records[i][0])
    events = [records[i][1] for i in order]

    total = len(events)
    if limite is not None and limite >= 0 and total > limite:
        shown = events[:limite]
        dropped = total - limite
    else:
        shown = events
        dropped = 0

    bucket_id_list = [record[2] for record in records]
    violent_list = [record[3] for record in records]
    buckets = tuple(
        HourBucket(
            id=bucket_id,
            label=label,
            occurrences=bucket_id_list.count(bucket_id),
            violent=sum(
                1
                for hit_bucket, is_violent in zip(bucket_id_list, violent_list, strict=False)
                if hit_bucket == bucket_id and is_violent
            ),
        )
        for bucket_id, label, _start, _end in HOUR_BUCKETS
    )
    without_hour = sum(1 for bucket_id in bucket_id_list if not bucket_id)

    return StreetEvents(
        rua=binding.rua_nome,
        rua_raw=binding.rua_raw,
        rua_key=binding.rua_key,
        rua_tipo=binding.rua_tipo,
        distrito=binding.distrito,
        distrito_id=binding.distrito_id,
        municipio=binding.municipio,
        period=binding.period,
        total_occurrences=total,
        total_incidents=count_incidents(frame),
        hour_buckets=buckets,
        events_without_hour=without_hour,
        events=tuple(shown),
        dropped_events=dropped,
        taxonomy_provisional=binding.taxonomy.provisional,
        generated_at=datetime.now(),
    )


__all__ = [
    "STREET_EVENTS_WARN_LIMIT",
    "StreetEvents",
    "build_street_events",
    "parse_clock",
]

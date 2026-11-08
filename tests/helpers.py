"""Dados sintéticos pequenos para testes (nunca leem os .xlsx reais)."""

from __future__ import annotations

import json

import pandas as pd

from spseg.data.cache import facts_cache_path, write_parquet


def make_facts(
    bairro_nome: str = "Pinheiros",
    bairro_id: str = "pinheiros",
    *,
    start: str = "2024-01-05",
    months: int = 30,
    per_month: int = 2,
) -> pd.DataFrame:
    """Série mensal sintética com BOs distintos e naturezas variadas."""
    dates = pd.date_range(start=start, periods=months, freq="MS")
    rows = []
    naturezas = [
        ("ROUBO - OUTROS", "Via Pública"),
        ("FURTO - OUTROS", "Via Pública"),
        ("FURTO - OUTROS", "Residência"),
        ("HOMICÍDIO DOLOSO", "Via Pública"),
    ]
    counter = 0
    for date in dates:
        for _index in range(per_month):
            counter += 1
            natureza, tipo_local = naturezas[counter % len(naturezas)]
            rows.append(
                {
                    "num_bo": f"BO{counter:05d}",
                    "ano_bo": date.year,
                    "bo_key": f"{date.year}/BO{counter:05d}",
                    "data_registro": date,
                    "data_ocorrencia": date,
                    "bairro_raw": bairro_nome,
                    "bairro_nome": bairro_nome,
                    "bairro_id": bairro_id,
                    "bairro_method": "exact",
                    "bairro_confidence": 1.0,
                    "distrito_id": bairro_id,
                    "municipio": "São Paulo",
                    "municipio_key": "SAO PAULO",
                    "natureza": natureza,
                    "tipo_local": tipo_local,
                    "conduta": "Outros",
                    "latitude": -23.56,
                    "longitude": -46.70,
                    "crime_category": "crime_violento",
                    "source_sheet": "TESTE",
                }
            )
    return pd.DataFrame(rows)


def make_street_facts() -> pd.DataFrame:
    """Cache sintético para o grão `(rua, distrito)`.

    18 registros no distrito de Pinheiros:
    - 8 em RUA MOURATO COELHO (3 violentos, 5 não violentos);
    - 5 em AVENIDA CAPRI (1 violento, 4 não violentos; 100% Terminal/Estação);
    - 2 com logradouro suprimido;
    - 1 sem logradouro;
    - 1 de invasão de residência e 1 de violência sexual, com logradouro válido.
    Visíveis para rua: 13. Suprimidos: 2. Ausentes: 1. Categorias excluídas: 2.
    Horas de Mourato Coelho: 2 na madrugada, 2 na manhã, 1 na tarde, 2 na noite
    e 1 sem hora informada (BO006; violentos: 1 madrugada, 1 tarde, 1 noite).
    """
    from spseg.config import SUPPRESSED_MARKER

    rows = [
        # (logradouro, bo, natureza, tipo_local, crime_category, hora)
        (
            "RUA MOURATO COELHO",
            "BO001",
            "ROUBO - OUTROS",
            "Via Pública",
            "crime_violento",
            "02:10:00",
        ),
        (
            "RUA MOURATO COELHO",
            "BO002",
            "ROUBO - OUTROS",
            "Via Pública",
            "crime_violento",
            "23:40:00",
        ),
        (
            "RUA MOURATO COELHO",
            "BO003",
            "HOMICÍDIO DOLOSO",
            "Via Pública",
            "crime_violento",
            "12:30:00",
        ),
        (
            "RUA MOURATO COELHO",
            "BO004",
            "FURTO - OUTROS",
            "Residência",
            "crime_nao_violento",
            "07:15:00",
        ),
        (
            "RUA MOURATO COELHO",
            "BO004",
            "FURTO - OUTROS",
            "Residência",
            "crime_nao_violento",
            "07:15:00",
        ),
        (
            "RUA MOURATO COELHO",
            "BO005",
            "FURTO - OUTROS",
            "Via Pública",
            "crime_nao_violento",
            "00:05:00",
        ),
        (
            "RUA MOURATO COELHO",
            "BO006",
            "FURTO - OUTROS",
            "Via Pública",
            "crime_nao_violento",
            None,
        ),
        (
            "RUA MOURATO COELHO",
            "BO007",
            "FURTO - OUTROS",
            "Via Pública",
            "crime_nao_violento",
            "18:45:00",
        ),
        ("AVENIDA CAPRI", "BO101", "ROUBO - OUTROS", "Terminal/Estação", "crime_violento", None),
        (
            "AVENIDA CAPRI",
            "BO102",
            "FURTO - OUTROS",
            "Terminal/Estação",
            "crime_nao_violento",
            None,
        ),
        (
            "AVENIDA CAPRI",
            "BO103",
            "FURTO - OUTROS",
            "Terminal/Estação",
            "crime_nao_violento",
            None,
        ),
        (
            "AVENIDA CAPRI",
            "BO104",
            "FURTO - OUTROS",
            "Terminal/Estação",
            "crime_nao_violento",
            None,
        ),
        (
            "AVENIDA CAPRI",
            "BO105",
            "FURTO - OUTROS",
            "Terminal/Estação",
            "crime_nao_violento",
            None,
        ),
        (SUPPRESSED_MARKER, "BO201", "ROUBO - OUTROS", "Via Pública", "crime_violento", "01:00:00"),
        (SUPPRESSED_MARKER, "BO202", "PORTE DE ENTORPECENTES", "Via Pública", "outros", "02:00:00"),
        ("", "BO301", "ROUBO - OUTROS", "Via Pública", "crime_violento", "03:00:00"),
        (
            "RUA DAS FLORES",
            "BO401",
            "INVASAO DE RESIDENCIA",
            "Residência",
            "invasao_residencia",
            "04:00:00",
        ),
        ("RUA DAS FLORES", "BO501", "ESTUPRO", "Residência", "violencia_sexual", "05:00:00"),
    ]
    date = pd.Timestamp("2024-01-05")
    records = []
    for logradouro, bo, natureza, tipo_local, category, hora in rows:
        records.append(
            {
                "num_bo": bo[2:],
                "ano_bo": 2024,
                "bo_key": f"2024/{bo}",
                "data_registro": date,
                "data_ocorrencia": date,
                "hora_ocorrencia": hora,
                "bairro_raw": "Pinheiros",
                "bairro_nome": "Pinheiros",
                "bairro_id": "pinheiros",
                "bairro_method": "exact",
                "bairro_confidence": 1.0,
                "distrito_id": "pinheiros",
                "municipio": "São Paulo",
                "municipio_key": "SAO PAULO",
                "logradouro": logradouro,
                "natureza": natureza,
                "tipo_local": tipo_local,
                "conduta": "Outros",
                "latitude": -23.56,
                "longitude": -46.70,
                "crime_category": category,
                "source_sheet": "TESTE",
            }
        )
    return pd.DataFrame(records)


def write_facts(settings, frame: pd.DataFrame, year: int) -> None:
    write_parquet(frame, facts_cache_path(settings, year))


def make_city_facts(
    districts: tuple[tuple[str, str, int, int], ...],
    *,
    start: str = "2024-01-05",
    months: int = 12,
) -> pd.DataFrame:
    """Cidade sintética multi-distrito.

    `districts`: sequência de `(bairro_id, bairro_nome, n_violentos, n_nao_violentos)`.
    Cada linha violenta é `ROUBO - OUTROS` → `crime_violento`; cada não violenta
    é `FURTO - OUTROS` → `crime_nao_violento`. BOs e datas distintos, espalhados
    por `months` meses a partir de `start`.
    """
    dates = pd.date_range(start=start, periods=months, freq="MS")
    rows: list[dict] = []
    counter = 0
    for bairro_id, bairro_nome, violent, non_violent in districts:
        for natureza, count in (
            ("ROUBO - OUTROS", violent),
            ("FURTO - OUTROS", non_violent),
        ):
            category = "crime_violento" if natureza == "ROUBO - OUTROS" else "crime_nao_violento"
            for _index in range(count):
                counter += 1
                date = dates[(counter - 1) % months]
                rows.append(
                    {
                        "num_bo": f"BO{counter:05d}",
                        "ano_bo": date.year,
                        "bo_key": f"{date.year}/BO{counter:05d}",
                        "data_registro": date,
                        "data_ocorrencia": date,
                        "bairro_raw": bairro_nome,
                        "bairro_nome": bairro_nome,
                        "bairro_id": bairro_id,
                        "bairro_method": "exact",
                        "bairro_confidence": 1.0,
                        "distrito_id": bairro_id,
                        "municipio": "São Paulo",
                        "municipio_key": "SAO PAULO",
                        "natureza": natureza,
                        "tipo_local": "Via Pública",
                        "conduta": "Outros",
                        "latitude": -23.56,
                        "longitude": -46.70,
                        "crime_category": category,
                        "source_sheet": "TESTE",
                    }
                )
    return pd.DataFrame(rows)


def write_population_multi(
    settings,
    rows: tuple[tuple[str, str, int, int], ...],
    *,
    nivel: str = "bairro",
) -> None:
    """População/domicílios de vários bairros: `(id, nome, populacao, domicilios)`."""
    pd.DataFrame(
        [
            {
                "bairro_id": bairro_id,
                "bairro_nome": bairro_nome,
                "populacao": populacao,
                "domicilios": domicilios,
                "ano": 2022,
                "fonte": "Censo teste",
                "nivel": nivel,
            }
            for bairro_id, bairro_nome, populacao, domicilios in rows
        ]
    ).to_csv(settings.reference_dir / "populacao_bairro.csv", index=False)
    pd.DataFrame(
        [
            {
                "bairro_id": bairro_id,
                "bairro_nome": bairro_nome,
                "domicilios": domicilios,
                "ano": 2022,
                "fonte": "Censo teste",
                "nivel": nivel,
            }
            for bairro_id, bairro_nome, populacao, domicilios in rows
        ]
    ).to_csv(settings.reference_dir / "domicilios_bairro.csv", index=False)


WEIGHTED_TAXONOMY_YAML = """\
versao: 1
provisorio: true
# Pesos de teste: violento 5, não violento 2.
pesos:
  peso_padrao: 1
  por_natureza:
    ROUBO - OUTROS: 5
    FURTO - OUTROS: 2
categorias:
  - id: crime_violento
    rotulo: Crimes violentos
    prioridade: 30
    regras:
      - natureza: [ROUBO - OUTROS]
  - id: crime_nao_violento
    rotulo: Crimes não violentos
    prioridade: 40
    regras:
      - natureza: [FURTO - OUTROS]
"""


def write_taxonomy(settings) -> None:
    """Taxonomia com pesos fixos de teste."""
    (settings.reference_dir / "crime_taxonomy.yml").write_text(
        WEIGHTED_TAXONOMY_YAML, encoding="utf-8"
    )


def write_population(
    settings,
    *,
    bairro_id: str = "pinheiros",
    bairro_nome: str = "Pinheiros",
    populacao: int = 100_000,
    domicilios: int = 50_000,
    nivel: str = "bairro",
) -> None:
    pd.DataFrame(
        [
            {
                "bairro_id": bairro_id,
                "bairro_nome": bairro_nome,
                "populacao": populacao,
                "ano": 2022,
                "fonte": "Censo teste",
                "nivel": nivel,
            }
        ]
    ).to_csv(settings.reference_dir / "populacao_bairro.csv", index=False)
    pd.DataFrame(
        [
            {
                "bairro_id": bairro_id,
                "bairro_nome": bairro_nome,
                "domicilios": domicilios,
                "ano": 2022,
                "fonte": "Censo teste",
                "nivel": nivel,
            }
        ]
    ).to_csv(settings.reference_dir / "domicilios_bairro.csv", index=False)


def polygon_features() -> list[dict]:
    def square(lon: float, lat: float, size: float = 0.02) -> list:
        return [
            [lon - size, lat - size],
            [lon + size, lat - size],
            [lon + size, lat + size],
            [lon - size, lat + size],
            [lon - size, lat - size],
        ]

    features = []
    for bairro_id, nome, lon, lat in (
        ("pinheiros", "Pinheiros", -46.70, -23.56),
        ("vila-mariana", "Vila Mariana", -46.63, -23.59),
    ):
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "bairro_id": bairro_id,
                    "bairro_nome": nome,
                    "distrito_id": bairro_id,
                },
                "geometry": {"type": "Polygon", "coordinates": [square(lon, lat)]},
            }
        )
    return features


def write_polygons(settings) -> None:
    payload = {"type": "FeatureCollection", "features": polygon_features()}
    (settings.reference_dir / "distritos_sp.geojson").write_text(
        json.dumps(payload), encoding="utf-8"
    )

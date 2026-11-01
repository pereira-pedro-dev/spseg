# Scripts

Scripts auxiliares, executáveis com `uv run python scripts/<nome>.py`.

## Ainda não implementados

- **`build_reference.py`** — a partir do GeoJSON de bairros/distritos do
  GeoSampa e dos agregados do IBGE Censo 2022, gera:
  - `data/reference/bairros_sp.geojson` (com `bairro_id`, `bairro_nome`,
    `distrito_id`)
  - `data/reference/populacao_bairro.csv`
  - `data/reference/domicilios_bairro.csv`
- **`build_aliases.py`** — varre as grafias de `BAIRRO` no cache, compara com os
  nomes canônicos e sugere linhas para `data/reference/bairro_aliases.csv`
  (revisão manual).
- **`download_ssp.py`** — baixa as planilhas da SSP e coloca em `data/raw/`
  (fora da base atual; hoje o download é manual).

## Contrato

Os formatos esperados estão em [`../data/reference/README.md`](../data/reference/README.md).
Depois de gerar ou editar a referência:

```bash
uv run spseg ingest
uv run spseg doctor
```

O manifesto detecta a mudança da referência e refaz o estágio 2 sozinho.
`--force` só é necessário para reler o Excel.

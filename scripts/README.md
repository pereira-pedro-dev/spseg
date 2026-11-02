# Scripts

Scripts auxiliares, executáveis com `uv run python scripts/<nome>.py`.

## Implementados

- **`build_reference.py`** — baixa o GeoJSON de distritos do WFS do GeoSampa e
  os agregados por distrito do IBGE Censo 2022, casa os dois pelo nome
  normalizado e gera:
  - `data/reference/distritos_sp.geojson` (com `bairro_id`, `bairro_nome`,
    `distrito_id`, `nivel`)
  - `data/reference/populacao_bairro.csv`
  - `data/reference/domicilios_bairro.csv`
  - `data/reference/SOURCES.md` (URLs, SHA-256 e variáveis)

  ```bash
  uv run python scripts/build_reference.py            # baixa e monta
  uv run python scripts/build_reference.py --check    # valida sem rede
  uv run python scripts/build_reference.py --offline  # usa downloads locais
  ```

  Os arquivos crus ficam em `data/reference/downloads/` (ignorado pelo git).
  `--simplify 0.00005` reduz ~3,1 MB para ~1 MB, ao custo de precisão na divisa.

- **`build_aliases.py`** — lê o cache de fatos, considera apenas linhas
  `bairro_method=geo`, agrupa `bairro_raw` normalizado e grava
  `data/reference/bairro_aliases.csv` com `n` e `share` em `fonte`.

  ```bash
  uv run python scripts/build_aliases.py --dry-run   # audita sem gravar
  uv run python scripts/build_aliases.py             # grava
  uv run python scripts/build_aliases.py --min-n 10 --min-share 0.9
  ```

  Aliases curados (fonte diferente de `derivado:geo`) são preservados. O padrão
  `n >= 5` e `share >= 0.85` deixa de fora nomes ambíguos, que ficam
  `unresolved` em vez de serem atribuídos ao distrito modal. Depois de gravar,
  rode `uv run spseg ingest`.

## Ainda não implementado

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

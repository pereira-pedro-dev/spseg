# spseg — segurança por bairro em São Paulo

CLI para consultar um resumo de segurança por bairro a partir dos dados públicos
da Secretaria de Segurança Pública de São Paulo (`SPDadosCriminais_YYYY.xlsx`).

Esta é a **base de arquitetura e dados**. Ela ingere, cacheia, resolve bairros e
mostra contagens por categoria. A metodologia de pontuação e o comando
`compare` ficam para a próxima etapa.

## Escopo atual

- **Capital de São Paulo** (`municipio = São Paulo`). O schema já guarda o
  município para uma futura extensão ao estado.
- Planilhas de **2024, 2025 e 2026**. 2026 é um ano parcial e isso é sinalizado
  na saída.
- Saída em português; código e docstrings em inglês.
- Categorias de crime **provisórias** até a sessão de metodologia.

## Instalação

Requer [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Dados brutos

Coloque os arquivos baixados da SSP em `data/raw/`, um por ano:

```
data/raw/
├─ SPDadosCriminais_2024.xlsx
├─ SPDadosCriminais_2025.xlsx
└─ SPDadosCriminais_2026.xlsx
```

Os `.xlsx` e o cache não são versionados. O nome do arquivo precisa conter o
ano (`SPDadosCriminais_YYYY.xlsx`); mais de um arquivo para o mesmo ano é erro.

## Uso

```bash
# 1. Lê os Excel e monta o cache (a etapa demorada)
uv run spseg ingest

# 2. Confere cache, referência e anos disponíveis
uv run spseg doctor

# 3. Consulta um bairro
uv run spseg bairro pinheiros

# 4. Mesma consulta em JSON
uv run spseg bairro pinheiros --json

# 5. Lista/busca bairros presentes no cache
uv run spseg list --search pin

# 6. Relatório de qualidade da base
uv run spseg check --ano 2026
```

### Comandos

| Comando | O que faz |
|---|---|
| `spseg ingest` | Excel → parquet bruto → parquet enriquecido + `manifest.json`. |
| `spseg check` | Qualidade e proveniência (`--source cache` rápido ou `excel`). |
| `spseg list` | Bairros do cache, contagem e taxa de resolução. |
| `spseg bairro <nome>` | Resumo por categoria, com período, taxas e ressalvas. |
| `spseg doctor` | Estado do cache e dos arquivos de referência. |

### Opções de `bairro`

| Opção | Efeito |
|---|---|
| `--anos N` | Janela móvel de N anos terminando no fim da cobertura. |
| `--desde AAAA-MM-DD` | Início explícito. |
| `--ate AAAA-MM-DD` | Fim explícito. |
| `--municipio` | Padrão: `São Paulo`. |
| `--json` | Saída JSON para script/`jq`. |

Sem `--anos`/`--desde`/`--ate`, o período vai do início da cobertura dos
arquivos (menor `data_registro`) até a ocorrência mais recente. Datas de
ocorrência antigas não esticam a janela para trás.

### Exit codes

- `0` — sucesso
- `1` — erro de entrada (arquivo, data, opção)
- `2` — bairro não encontrado (com sugestões)
- `3` — cache ausente (`rode spseg ingest`)

## Como ler a saída

- **Ocorrências** — linhas da base; cada linha é uma ocorrência × natureza.
- **Incidentes** — `ano_bo/num_bo` distintos; um BO com três naturezas conta 1.
- **Taxas** — só aparecem se houver população/domicílios na referência. Sem
  denominador, aparecem como `n/d`, nunca com um denominador inventado.
- **Tendência** — últimos 12 meses vs. 12 anteriores, só para janelas de pelo
  menos 24 meses e com casos suficientes.
- **Cada registro entra em uma única categoria**, por ordem de prioridade.
- Todo resumo traz as ressalvas de cobertura, resolução de bairro e taxonomia
  provisória.

## Arquitetura

```
Excel ──► data/cache/raw/{ano}.parquet       (parse, tipos, filtro da capital)
              │
              ▼
         data/cache/facts/{ano}.parquet      (+ bairro, métodos, categoria)
              │
              ▼
         análise (janela, contagens, taxas)
              │
              ▼
         render (Rich PT-BR) / JSON
```

- `data/cache/raw/` depende do workbook (tamanho/mtime no manifesto).
- `data/cache/facts/` depende também de `data/reference/`. Mudar a referência
  faz o estágio 2 ser refeito automaticamente no próximo `spseg ingest`;
  `--force` só é necessário para reler o Excel.
- `data/cache/manifest.json` guarda proveniência, contagens, versão de schema,
  versão da referência e contagem por método de resolução.

### Resolução de bairro

O campo `BAIRRO` da SSP é texto livre. A resolução é registrada por linha em
`bairro_method`:

1. `exact` — nome normalizado (sem acento/caixa/abreviação) igual ao canônico.
2. `alias` — hit em `bairro_aliases.csv`.
3. `fuzzy` — similaridade acima do limiar, só quando não é ambíguo.
4. `geo` — coordenadas válidas + point-in-polygon (se houver GeoJSON).
5. `unresolved` / `suppressed` — contados e reportados, nunca descartados em
   silêncio.

Sem GeoJSON, os passos 4 e o fallback geográfico ficam desativados. Sem uma
lista canônica de bairros, o registro é derivado das próprias grafias do cache.

## Referência opcional

Tudo em `data/reference/` é opcional, pequeno e versionado. Detalhes de
contrato em [`data/reference/README.md`](data/reference/README.md).

| Arquivo | Sem ele |
|---|---|
| `crime_taxonomy.yml` | Usa a taxonomia provisória embutida. |
| `bairros_sp.geojson` | Sem fallback por coordenadas. |
| `populacao_bairro.csv` | Taxas por 100 mil habitantes ficam `n/d`. |
| `domicilios_bairro.csv` | Taxas por 10 mil domicílios ficam `n/d`. |
| `bairro_aliases.csv` | Só resolução exata/aproximada. |

Os scripts para construir essa referência (GeoSampa + IBGE Censo 2022) ainda
não estão implementados; veja [`scripts/README.md`](scripts/README.md).

## Desenvolvimento

```bash
uv run pytest
uv run ruff check src tests scripts
uv run ruff format src tests scripts
```

Os testes usam dados sintéticos e um `.xlsx` minúsculo; não leem as planilhas
reais de `data/raw/`. A variável `SPSEG_DATA_DIR` aponta o tool para outro
diretório de dados.

## Limitações conhecidas

- Categorias provisórias; não usar como critério único de decisão.
- **2024 não tem `DESCR_TIPOLOCAL`**: a categoria "Invasão de residência" não
  pode ser identificada nesse ano (as demais categorias não dependem do tipo de
  local). O `spseg check --ano 2024` mostra a coluna 100% nula.
- Sem população/domicílios, não há taxa — apenas contagem.
- Os `BAIRRO` da SSP muitas vezes são distritos, não bairros oficiais; o modelo
  mantém `bairro_id` e `distrito_id` lado a lado.
- Sem downloader automático das planilhas.
- Sem score consolidado nem `compare` (próxima etapa).

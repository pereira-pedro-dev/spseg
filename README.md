# spseg — segurança por distrito em São Paulo

CLI para consultar um resumo de segurança por **distrito** a partir dos dados
públicos da Secretaria de Segurança Pública de São Paulo
(`SPDadosCriminais_YYYY.xlsx`).

O distrito é a unidade canônica porque é o único recorte da capital com polígono
oficial (GeoSampa) e denominador oficial (IBGE Censo 2022). Nomes de bairro
continuam funcionando como **alias de busca**: `spseg bairro pinheiros` e
`spseg distrito pinheiros` devolvem o mesmo resumo do distrito de Pinheiros.

Esta é a **base de arquitetura e dados**. Ela ingere, cacheia, resolve distritos
e mostra contagens por categoria. A metodologia de pontuação e o comando
`compare` ficam para a próxima etapa.

## Escopo atual

- **Capital de São Paulo** (`municipio = São Paulo`, 96 distritos). O schema
  guarda o município para uma futura extensão ao estado.
- Planilhas de **2024, 2025 e 2026**. 2026 é um ano parcial e isso é sinalizado
  na saída.
- Saída em português; código e docstrings em inglês.
- Categorias de crime **provisórias** até a sessão de metodologia.

## Instalação

Requer [uv](https://docs.astral.sh/uv/).

```bash
uv sync
```

## Dados de entrada

### Planilhas da SSP

Coloque os arquivos baixados da SSP em `data/raw/`, um por ano:

```
data/raw/
├─ SPDadosCriminais_2024.xlsx
├─ SPDadosCriminais_2025.xlsx
└─ SPDadosCriminais_2026.xlsx
```

Os `.xlsx` e o cache **não são versionados**. O nome precisa conter o ano
(`SPDadosCriminais_YYYY.xlsx`); mais de um arquivo para o mesmo ano é erro.

### Referência oficial

`data/reference/` é um snapshot pequeno e **versionado**:

| Arquivo | Conteúdo |
|---|---|
| `distritos_sp.geojson` | 96 polígonos de distrito (GeoSampa/WFS). |
| `populacao_bairro.csv` | População por distrito (IBGE Censo 2022, `v0001`). |
| `domicilios_bairro.csv` | Domicílios particulares ocupados (IBGE 2022, `v0007`). |
| `bairro_aliases.csv` | Grafias de bairro aprendidas dos registros geolocalizados. |
| `crime_taxonomy.yml` | Taxonomia provisória de categorias. |
| `SOURCES.md` | URLs, SHA-256 e variáveis dos downloads. |

Os downloads crus ficam em `data/reference/downloads/` e são ignorados pelo git.
Contratos e detalhes em [`data/reference/README.md`](data/reference/README.md).

## Setup e bootstrap

Na primeira vez (ou ao regenerar a referência), o fluxo é de **dois passes**:

```bash
# 1. Gera distritos + denominadores (baixa GeoSampa e IBGE; precisa de rede)
uv run python scripts/build_reference.py

# 2. Primeiro passe: resolve por coordenada e texto exato
uv run spseg ingest

# 3. Aprende aliases bairro→distrito com os registros geolocalizados
uv run python scripts/build_aliases.py

# 4. Segundo passe: aplica os aliases (não precisa de --force)
uv run spseg ingest

# 5. Confere o estado
uv run spseg doctor
```

Se você clonou o repositório com `data/reference/` já commitado, os passos 1 e 3
podem ser pulados; rode `uv run spseg ingest` para montar o cache.

## Uso

```bash
# Consulta um distrito (nome de bairro também funciona)
uv run spseg distrito pinheiros
uv run spseg bairro pinheiros --anos 3

# Mesma consulta em JSON
uv run spseg bairro pinheiros --json

# Lista/busca distritos presentes no cache
uv run spseg list --search pin

# Relatório de qualidade da base
uv run spseg check --ano 2026

# Estado do cache e da referência
uv run spseg doctor
```

### Comandos

| Comando | O que faz |
|---|---|
| `spseg ingest` | Excel → parquet bruto → parquet enriquecido + `manifest.json`. |
| `spseg check` | Qualidade e proveniência (`--source cache` rápido ou `excel`). |
| `spseg list` | Distritos do cache, contagem e taxa de resolução. |
| `spseg bairro <nome>` | Resumo por categoria; bairro é tratado como alias. |
| `spseg distrito <nome>` | Alias de `spseg bairro`. |
| `spseg doctor` | Estado do cache e dos arquivos de referência. |

### Opções de `bairro` / `distrito`

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
- `2` — distrito não encontrado (com sugestões)
- `3` — cache ausente (`rode spseg ingest`)

## Como ler a saída

- **Ocorrências** — linhas da base; cada linha é uma ocorrência × natureza.
- **Incidentes** — `ano_bo/num_bo` distintos; um BO com três naturezas conta 1.
- **Taxas** — só aparecem se houver população/domicílios na referência. Sem
  denominador, aparecem como `n/d`, nunca com um denominador inventado.
- **Base** — mostra o nível do denominador e a fonte (ex.:
  `distrito (IBGE Censo 2022)`).
- **Tendência** — últimos 12 meses vs. 12 anteriores, só para janelas de pelo
  menos 24 meses e com casos suficientes.
- **Cada registro entra em uma única categoria**, por ordem de prioridade.
- Todo resumo traz as ressalvas de cobertura, resolução de distrito e taxonomia
  provisória. Quando a resolução da cidade fica abaixo de 98%, a saída avisa que
  as contagens do distrito são **piso**, não o total real.

## Arquitetura

```
Excel ──► data/cache/raw/{ano}.parquet       (parse, tipos, filtro da capital)
              │
              ▼
         data/cache/facts/{ano}.parquet      (+ distrito, métodos, categoria)
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

### Resolução de distrito

O campo `BAIRRO` da SSP é texto livre e tem milhares de grafias. A prioridade é:

1. **geo** — coordenada válida + point-in-polygon. Vence mesmo que o texto case
   com outro distrito: a coordenada é o sinal mais confiável.
2. **exact** — nome normalizado igual ao canônico.
3. **alias** — hit em `bairro_aliases.csv`.
4. **unresolved** / **suppressed** — contados e reportados, nunca descartados em
   silêncio.

No **lote**, `fuzzy` fica desligado (`BATCH_FUZZY = False`): casar nome de bairro
contra nome de distrito gera falso positivo. Na **busca do usuário**, `fuzzy`
continua ativo para sugestões, onde o erro é visível e corrigível.

Sem GeoJSON, a resolução por coordenadas fica desativada. Sem uma lista
canônica, o registro é derivado das próprias grafias do cache.

## Referência opcional

Tudo em `data/reference/` é opcional, pequeno e versionado. Detalhes de
contrato em [`data/reference/README.md`](data/reference/README.md).

| Arquivo | Sem ele |
|---|---|
| `crime_taxonomy.yml` | Usa a taxonomia provisória embutida. |
| `distritos_sp.geojson` | Sem fallback por coordenadas. |
| `populacao_bairro.csv` | Taxas por 100 mil habitantes ficam `n/d`. |
| `domicilios_bairro.csv` | Taxas por 10 mil domicílios ficam `n/d`. |
| `bairro_aliases.csv` | Só resolução exata ou por coordenada. |

### Fontes e política de commit

- **Polígonos:** `geoportal:distrito_municipal` no WFS do GeoSampa (EPSG:4326,
  Lei Municipal 11.220/1992; CC-BY).
- **População/domicílios:** IBGE, Censo Demográfico 2022, agregados por distrito
  (`v0001` e `v0007`; dados abertos).
- **Aliases:** derivados dos próprios registros geolocalizados, não curados à
  mão. Entram com `n >= 5` e `share >= 0.85`; a `fonte` carrega os números.

Commitar `data/reference/` deixa o resultado reprodutível e o diff revisável.
`data/raw/`, `data/cache/` e `data/reference/downloads/` ficam fora do git.

## Desenvolvimento

```bash
uv run pytest
uv run ruff check src tests scripts
uv run ruff format src tests scripts

# scripts auxiliares
uv run python scripts/build_reference.py --check
uv run python scripts/build_aliases.py --dry-run
```

Os testes usam dados sintéticos e um `.xlsx` minúsculo; não leem as planilhas
reais de `data/raw/`. A variável `SPSEG_DATA_DIR` aponta o tool para outro
diretório de dados.

## Limitações conhecidas

- Categorias provisórias; não usar como critério único de decisão.
- **2024 não tem `DESCR_TIPOLOCAL`**: a categoria "Invasão de residência" não
  pode ser identificada nesse ano (as demais categorias não dependem do tipo de
  local). O `spseg check --ano 2024` mostra a coluna 100% nula.
- O denominador é o Censo 2022, estático para 2024–2026; a `fonte` aparece na
  saída, mas não há projeção populacional.
- Cerca de **3% dos registros** da capital ficam `unresolved` mesmo após os
  aliases. São grafias ambíguas (o mesmo nome de bairro aparece em mais de um
  distrito) ou com suporte geográfico insuficiente; não são chutadas. Por isso
  as contagens por distrito são piso.
- Registros com local suprimido pelo SSP (`VEDAÇÃO DA DIVULGAÇÃO`) não entram em
  nenhum distrito.
- Sem downloader automático das planilhas.
- Sem score consolidado nem `compare` (próxima etapa).

## Granularidade por bairro (pendente)

> **Granularidade por bairro (pendente).** Bairro não tem polígono oficial nem
> denominador oficial no IBGE para a capital; o recorte oficial é distrito (96).
> A opção futura será **híbrida**: contagem por bairro a partir do campo
> `BAIRRO` (com a tabela `bairro_aliases.csv`) e taxa apenas no distrito
> correspondente, sempre rotulada como tal. Taxa por bairro não será estimada
> nem fabricada. Requer: alias bairro→distrito com suporte mínimo, campo de
> nível na saída e um comando/flag explícito de granularidade.

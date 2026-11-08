# spseg — segurança por distrito em São Paulo

CLI para consultar um resumo de segurança por **distrito** e por **rua dentro do
distrito** a partir dos dados públicos da Secretaria da Segurança Pública de São
Paulo (`SPDadosCriminais_YYYY.xlsx`).

O distrito é a unidade canônica porque é o único recorte da capital com polígono
oficial (GeoSampa) e denominador oficial (IBGE Censo 2022). Nomes de bairro
continuam funcionando como **alias de busca**: `spseg bairro pinheiros` e
`spseg distrito pinheiros` devolvem o mesmo resumo do distrito de Pinheiros.

Esta é a **base de arquitetura e dados**. Ela ingere, cacheia, resolve
distritos, mostra contagens por categoria e calcula um **score relativo**
(provisório) entre distritos, além de comparação lado a lado.

## Escopo atual

- **Capital de São Paulo** (`municipio = São Paulo`, 96 distritos). O schema
  guarda o município para uma futura extensão ao estado.
- Planilhas de **2024, 2025 e 2026**. 2026 é um ano parcial e isso é sinalizado
  na saída.
- Saída em português; código e docstrings em inglês.
- Categorias de crime e **pesos de severidade provisórios** até a sessão de
  metodologia.

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
| `crime_taxonomy.yml` | Taxonomia provisória de categorias e pesos de severidade. |
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

# Mesma consulta em JSON (inclui `score` com pesos e percentis)
uv run spseg bairro pinheiros --json

# Comparação lado a lado, na mesma janela (2 a 6 distritos)
uv run spseg compare pinheiros "itaim bibi" moema
uv run spseg compare pinheiros moema --json --anos 1

# Uma rua dentro de um distrito
uv run spseg rua "Mourato Coelho" --distrito Pinheiros
uv run spseg rua "Mourato Coelho" --distrito Pinheiros --json

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
| `spseg bairro <nome>` | Resumo por categoria + score relativo; bairro é tratado como alias. |
| `spseg distrito <nome>` | Alias de `spseg bairro`. |
| `spseg rua <rua> --distrito <nome>` | Resumo de uma rua dentro do distrito. |
| `spseg compare <2–6 nomes>` | Comparação lado a lado na mesma janela, com score. |
| `spseg doctor` | Estado do cache e dos arquivos de referência. |

### Opções de `bairro` / `distrito` / `rua` / `compare`

| Opção | Efeito |
|---|---|
| `--distrito` | Obrigatório em `rua`: distrito onde a rua será procurada. |
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
- `2` — distrito não encontrado, rua não encontrada, rua ambígua ou distrito
  sem rua atribuível (com sugestões)
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

## Score e comparação entre distritos

**Definição formal das fórmulas: [`docs/metricas.md`](docs/metricas.md).**

O **score** é uma nota relativa à cidade, não absoluta: ele diz *quão alto o
distrito está entre os distritos*, na janela consultada. Nunca é um número
isolado — a saída sempre mostra o score **com** os percentis por categoria.

- Base: taxa ponderada por severidade da natureza (pesos declarados em
  `crime_taxonomy.yml`, bloco `pesos`) → percentil por categoria entre os
  distritos elegíveis → composição ponderada dos percentis.
- O **posto** entra junto: "74º mais seguro de 95 distritos com score"
  (1º = mais seguro).
- Provisório por construção: pesos declarados manualmente, pendentes de
  metodologia; o rótulo e os avisos aparecem em toda saída.
- Piso por categoria: `1 <= n < 25` tira a categoria do percentil daquele
  distrito e renormaliza os pesos; `n == 0` permanece (observação real, protege
  o topo). O score só sai quando sobra peso elegível >= 60%.
- Sem reingestão: os pesos são aplicados na análise, não no cache.
- `spseg compare A B ...` (2–6 distritos) usa **uma única janela** para todos
  os distritos — comparar janelas diferentes é proibido. Exibe contagens,
  taxas, percentis por categoria, score/posto e qualidade da resolução.

### O que o score não é

- Não é probabilidade nem risco absoluto. Mudar os pesos reordena distritos —
  continue olhando os percentis por categoria exibidos junto.
- Não corrige a composição do território: distrito com comércio, terminal ou
  grande circulação concentra mais crime registrado; o percentil por categoria
  e o denominador de população do Censo 2022 não ajustam isso.

## Análise por rua dentro do distrito

`spseg rua <rua> --distrito <distrito>` responde a uma pergunta mais fina:
**quanto do crime do distrito está naquela rua e como a rua se compõe**.

- O grão é `(rua, distrito)`. A rua é resolvida **dentro** do distrito; nomes
  iguais em distritos diferentes são séries diferentes.
- A consulta aceita nome com ou sem tipo (`Mourato Coelho`, `Rua Mourato
  Coelho`, `R. Mourato Coelho`). O tipo faz parte da identidade: `Rua Paulista`
  não casa com `Avenida Paulista`. Se a consulta sem tipo for ambígua, a saída
  lista os candidatos e pede o tipo.
- Resolução: nome exato → nome exato sem tipo → aproximado (`>= 92` de
  similaridade e margem de 4). Não há alias de rua.
- **Não há taxa per capita nem por domicílio** no grão rua. O denominador
  confiável é do distrito, não da rua. No lugar, a saída mostra:
  - `% do distrito` — participação da rua no total da categoria no distrito
    **com rua atribuível** (ex.: 525 de 8.126 crimes violentos visíveis);
  - `% da rua` — composição interna da própria rua.
- O painel de contexto mostra o distrito inteiro, incluindo as categorias que
  **nunca** aparecem no grão rua.
- `% do distrito` é um **piso**: registros sem logradouro, suprimidos ou de
  categorias não atribuíveis ficam fora do denominador. A cobertura aparece no
  painel e no JSON.

As fórmulas, sempre sobre ocorrências:

```
share_of_district(c) = ocorrências da categoria c na rua
                       / ocorrências da categoria c no distrito com rua
share_of_street(c)   = ocorrências da categoria c na rua
                       / ocorrências da rua
coverage             = registros do distrito com rua
                       / registros do distrito
```

Exemplo real (cache de 2024–2026, período completo): em **Mourato Coelho /
Pinheiros**, 1.820 ocorrências, sendo 525 crimes violentos — **6,5%** dos 8.126
crimes violentos do distrito com rua atribuível e **28,8%** das ocorrências da
própria rua. Em **Rua Capri / Pinheiros**, 2.019 ocorrências e 900 em
`Terminal/Estação` (44,6%); a saída avisa que a contagem reflete o equipamento,
não uma rua residencial.

O nome da rua não é global: `Avenida Brigadeiro Faria Lima` em Pinheiros e em
Itaim Bibi são duas séries distintas, com contagens diferentes. Nesta versão não
há sugestão de ruas vizinhas.

### Por que invasão de residência e violência sexual não aparecem na rua

Nesses registros a SSP suprime logradouro e coordenada em 100% dos casos. Eles
não podem ser atribuídos a uma rua sem inventar dado. O `spseg rua` mostra
essas categorias apenas no **contexto do distrito**, com `Com rua = 0`.

### O que a saída não mede

O grão rua mede **crime registrado em espaço público no logradouro**, não o
risco do imóvel. Uma rua com muitos furtos pode refletir comércio, terminal ou
grande circulação. A saída avisa quando um tipo de local que não é via pública
concentra 25% ou mais dos registros.

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
- No grão rua, registros sem `logradouro`, com logradouro suprimido ou de
  `invasao_residencia`/`violencia_sexual` não são atribuídos a nenhuma rua; por
  isso os percentuais são piso. Duas ruas com o mesmo nome e o mesmo tipo no
  mesmo distrito continuam indistinguíveis; o `rua_raw` e a composição ajudam a
  perceber.
- `spseg rua` não traz número de porta, CEP, tendência nem ranking. Não há alias
  de rua nesta versão.
- Score e pesos de severidade são **provisórios**: pesos declarados à mão em
  `crime_taxonomy.yml`, pendentes da sessão de metodologia. Naturezas fora da
  tabela recebem peso 1 com aviso na saída.
- Comparar janelas diferentes não é suportado: `spseg compare` impõe uma única
  janela, e o score/posto é relativo aos distritos elegíveis daquela janela.
- Sem downloader automático das planilhas.

## Granularidade por bairro (pendente)

> **Granularidade por bairro (pendente).** Bairro não tem polígono oficial nem
> denominador oficial no IBGE para a capital; o recorte oficial é distrito (96).
> A opção futura será **híbrida**: contagem por bairro a partir do campo
> `BAIRRO` (com a tabela `bairro_aliases.csv`) e taxa apenas no distrito
> correspondente, sempre rotulada como tal. Taxa por bairro não será estimada
> nem fabricada. Requer: alias bairro→distrito com suporte mínimo, campo de
> nível na saída e um comando/flag explícito de granularidade.
>
> O fluxo desta entrega vai direto de distrito para `(rua, distrito)`; bairro
> continua apenas como **alias de busca** do distrito.

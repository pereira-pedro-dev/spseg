# Métricas — definição formal

Este documento é o **contrato** das métricas que o `spseg` exibe. Mudança de
fórmula passa por mudança aqui (diff revisável). Código e docstrings em inglês;
os identificadores de saída seguem os descritos abaixo.

Três grãos nesta versão:

| Comando | Grão | Denominador | Tendência | Score |
|---|---|---|---|---|
| `spseg bairro` / `distrito` | distrito (96 da capital) | população/domicílios (Censo 2022) | sim | sim (provisório) |
| `spseg rua` | `(rua, distrito)` | **nenhum** (participação) | não | não |
| `spseg compare` | 2–6 distritos, mesma janela | população/domicílios | por categoria | sim (provisório) |

## Universo de registros

Comum a todas as métricas do grão distrito:

- **no-distrito**: linhas do período com `bairro_id` resolvido por
  `geo`/`exact`/`alias`/`fuzzy` e atribuído àquele distrito.
- **fora do universo** (nunca descartados em silêncio):
  - `suppressed` — local suprimido pelo SSP (`VEDAÇÃO DA DIVULGAÇÃO`);
    contados na qualidade da cidade, não entram em distrito algum;
  - `unresolved` — não tiveram distrito; as contagens por distrito são
    **piso**, não totais reais (nota automática quando a resolução < 98%).
- Uma linha = uma **ocorrência × natureza**. O mesmo BO pode gerar várias
  linhas (naturezas distintas), então `occurrences >= incidents`.
- `incidents` = `bo_key` (`ano_bo/num_bo`) distintos.

## Grão distrito

| Métrica | Fórmula | `n/d` quando |
|---|---|---|
| `occurrences` | linhas no distrito, período e categoria | — |
| `incidents` | `nunique(bo_key)` idem | — |
| `rate_per_100k` | `occurrences / população × 100.000` | sem população na referência |
| `rate_per_10k_households` | `occurrences / domicílios × 10.000` | sem domicílios |
| `trend` | ver seção abaixo | janela < 24 meses ou `recent + previous < 30` |

- Janela padrão: da menor `data_registro` coberta pelos arquivos até a
  ocorrência mais recente; `--anos N`, `--desde`/`--ate` restringem.
- Tendência por categoria: janela móvel, **não por ano-calendário** —
  `recent` = últimos 365 dias até `period.end`; `previous` = os 365 dias
  anteriores; variação `= (recent − previous) / previous × 100`.
  Classificação: `>= +10%` ↑ subiu, `<= −10%` ↓ caiu, entre os limites →
  estável (o valor ainda é exibido). Requer `period.days >= 730` e
  `recent + previous >= 30` casos; com `previous = 0` mostra ↑ e `n/d`.
  Usa ocorrências (linhas), não incidentes e não taxa.
- Qualidade exposta: `rows_in_bairro`, `method_counts`, `resolution_rate`
  (cidade no período), `suppressed_city`, notas (cobertura, referência
  desatualizada, taxonomia provisória).

## Score relativo à cidade (provisório)

Base conceitual: índices compostos por território (CDC SVI: percentil por
indicador → combinação ponderada → re-ranking) e índices de severidade (Crime
Severity Index / ONS severity score). A diferença: **não há tabela de penas de
SP**, então os pesos são **declarados manualmente** em
`data/reference/crime_taxonomy.yml` (bloco `pesos`), versionados por diff e
carregam rótulo "provisório" nas saídas.

### Fórmulas

Sobre o frame recortado por município + janela, com `crime_category`:

```
peso(w)          peso da natureza w no YAML (não mapeada → peso_padrao, com aviso)

w_c(d)           Σ peso(w) dos registros do distrito d na categoria c
                 (ocorrências ponderadas pela severidade)
taxa_ponderada_c(d)   w_c(d) / pop(d) × 100.000
taxa_c(d)        occ_c(d) / pop(d) × 100.000   (bruta, sem peso)

elegível_c(d)    pop(d) presente ∧ (occ_c(d) == 0 ∨ occ_c(d) >= 25)

pct_c(d)         percentil de taxa_ponderada_c(d) entre os distritos elegíveis
                 da categoria c (`rank(method="average", pct=True)`; menor = mais seguro)

peso_c           Σ peso(w) das naturezas observadas na categoria c **cidade inteira**
                 (um distrito com 0 ocorrências não perde peso)

score(d)         Σ_c peso_c · pct_c(d) / Σ_c peso_c        (dos percentis disponíveis)
                 disponível ⇔ Σ pesos disponíveis >= 0,60 × Σ pesos totais

posto(d)         rank(score) ascendente; 1º = mais seguro do conjunto com score
"de N"           N = nº de distritos com score disponível
```

### Regras de `n/d` (nada é fabricado)

1. **Sem população** na referência: taxas `n/d`, distrito fora de todos os
   percentis, score indisponível com nota.
2. **Família `occ == 0`**: categoria com exatamente 0 ocorrências é
   observação real e permanece no percentil (taxa 0). Protege o topo do
   ranking, que poderia ser excluído por "n pequeno".
3. **`1 <= occ < 25`**: a categoria fica fora do percentil e do score daquele
   distrito; os pesos remanescentes são renormalizados; nota na saída.
4. **Cobertura de peso < 60%**: score indisponível, com nota.
5. **Naturezas fora da tabela de pesos**: usam `peso_padrao` (1) e a saída
   lista as 5 mais frequentes com contagens.
6. **Pesos não declarados** (bloco `pesos` ausente): todas as naturezas
   ficam com peso 1 (composto trata homicídio como furto); nota na saída.
7. Sem reingestão: os pesos são aplicados na análise, não no cache.

### Limitações declaradas (ficam em cada saída)

- Pesos provisórios, pendentes da sessão de metodologia.
- População/domicílios do Censo 2022, estáticos para 2024–2026.
- Score é **relativo à cidade na janela**: comparar janelas diferentes é
  proibido; com janelas parciais o posto pode mudar.
- Taxas por 100 mil não corrigem composição do território (terminal, comércio,
  circulação). O score **não é** "risco de imóvel" nem "quantos crimes vão me
  acontecer"; os percentis por categoria ficam sempre visíveis.
- 2024 não traz `DESCR_TIPOLOCAL`, então "Invasão de residência" fica
  subestimada nesse ano (nota automática).

## Grão rua (`spseg rua`)

Sem denominador: não há taxa per capita/domicílio. Em vez disso:

| Métrica | Fórmula | Nota |
|---|---|---|
| `share_of_district(c)` | ocorrências da categoria c na rua / visíveis da categoria c **no distrito** | denominador = distrito com rua atribuível |
| `share_of_street(c)` | ocorrências da c na rua / ocorrências da rua | composição interna |
| `coverage` | registros do distrito com rua / registros do distrito | piso declarado |
| exclusões | `invasao_residencia`, `violencia_sexual` têm logradouro suprimido em 100% → nunca existem no grão rua | só no contexto do distrito |

Ver também: avisos de equipamento (`tipo_local`) e de rua atravessando
distritos no README.

## `spseg compare`

- 2–6 distritos por execução, na **mesma janela** (`--anos`,
  `--desde`/`--ate` resolvem uma única vez).
- Mesmo resolvedor do `spseg bairro` (exato, alias, fuzzy com sugestões);
  distrito inexistente → código 2.
- Saída: tabela lado a lado (contagem, taxa/100k, percentil), score/posto,
  qualidade por distrito, aviso de taxonomia provisória.
- JSON completo para `jq`; exit codes: 0 ok, 1 uso inválido, 2 distrito não
  encontrado, 3 cache ausente.

## Referências

- Statistics Canada — *Crime Severity Index and Contributions to Tier 1 Crime Severity Index* (ponderar crimes por gravidade com penas).
- ONS — *User guide to crime statistics in England and Wales: severity scores*.
- CDC/ATSDR — *Social Vulnerability Index 2020 Documentation* (percentis por território e índice composto).
- UNODC/ONU — indicador **ODS 16.1.1** (homicídio doloso por 100 mil hab.) e *Framework for the Prevention of Crime*.

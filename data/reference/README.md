# Referência

Arquivos pequenos e versionados que enriquecem o cache. Nenhum é obrigatório
para o tool rodar, mas sem eles não há taxas por habitante/domicílio nem
fallback por coordenadas.

## `crime_taxonomy.yml`

Regras de agrupamento das naturezas e pesos de severidade. **Provisório** até
a sessão de metodologia.

```yaml
categorias:
  - id: crime_violento
    rotulo: Crimes violentos
    prioridade: 30
    regras:
      - natureza: [ROUBO - OUTROS, HOMICÍDIO DOLOSO]
        tipo_local: [Via Pública]      # opcional
        conduta_contem: [ARMA]         # opcional
  - id: outros
    rotulo: Outros
    prioridade: 999
    padrao: true
```

Cada registro entra em **uma** categoria: vence a regra de menor `prioridade`.
A categoria com `padrao: true` recebe o que não casar.

### Bloco `pesos` (opcional)

Pesos por natureza para o score relativo à cidade (`spseg bairro`/`compare`).
Somados na análise — **não** exige reingestão nem mudam o cache.

```yaml
pesos:
  peso_padrao: 1                    # natureza fora da tabela cai aqui (com aviso)
  por_natureza:
    HOMICIDIO DOLOSO: 10
    FURTO - OUTROS: 2
```

- A chave é a natureza **normalizada**: sem acento, maiúscula, espaços
  colapsados; o hífen (`-`) é mantido (`HOMICÍDIO DOLOSO` → `HOMICIDIO DOLOSO`,
  `ROUBO - OUTROS` → `ROUBO - OUTROS`).
- Valor inteiro positivo; quanto maior, mais pesa na taxa ponderada da
  categoria.
- Sem o bloco `pesos`, o score fica com peso 1 para todas as naturezas
  (homicídio pesaria como furto) e as saídas avisam.
- Pesos originais no YAML podem usar acentos; a normalização cuida disso.

## `distritos_sp.geojson`

`FeatureCollection` com os 96 polígonos de distrito da capital. `properties`:

- `bairro_id` (ou `id`, `codigo`)
- `bairro_nome` (ou `nome`, `name`)
- `distrito_id` (ou `distrito`) — **obrigatório** para as taxas por
  habitante/domicílio; sem ele o denominador fica `n/d`.
- `nivel`: `distrito`

Fonte: `geoportal:distrito_municipal` (WFS do GeoSampa, Lei 11.220/1992).
Hoje `bairro_id == distrito_id`; o par de colunas é mantido para o futuro
recorte por bairro. Se `bairro_id` não vier nas propriedades, ele é derivado do
nome normalizado.

## `populacao_bairro.csv` e `domicilios_bairro.csv`

```csv
bairro_id,bairro_nome,populacao,ano,fonte,nivel
355030862,Pinheiros,65145,2022,IBGE Censo 2022 (universo),distrito
```

- `populacao_bairro.csv` usa a coluna de valor `populacao`.
- `domicilios_bairro.csv` usa a coluna de valor `domicilios`.
- `nivel` é `bairro` (padrão) ou `distrito`. Com `distrito`, o identificador em
  `bairro_id` é o `distrito_id` do GeoJSON, e o valor é usado como fallback
  quando não existe denominador por bairro.
- `ano` e `fonte` são informativos e aparecem no resumo.

Fonte: IBGE Censo 2022, agregados por distrito. `populacao = v0001`;
`domicilios = v0007` (domicílios particulares ocupados). `v0002` (total de
domicílios) fica como alternativa documentada.

## `bairro_aliases.csv`

```csv
bairro_raw,bairro_id,fonte
JD PAULISTA,355030862,"derivado:geo n=482 share=0.97"
```

Mapeia grafias brutas do campo `BAIRRO` para o `bairro_id` canônico. A chave é
normalizada (sem acento, maiúscula, abreviações expandidas) antes da comparação.
Aliases derivados dos registros geolocalizados trazem `n` e `share` em `fonte`.
Só entram grafias com `n >= 5` e share do distrito modal `>= 0.85`; nomes
ambíguos ficam `unresolved` de propósito. Aliases com `fonte` diferente de
`derivado:geo` são tratados como curados e preservados pelo script.

## Construção

`scripts/build_reference.py` baixa o WFS do GeoSampa e o ZIP do IBGE, casa os
dois pelo nome normalizado e escreve o GeoJSON, os CSVs e `SOURCES.md`.
`scripts/build_aliases.py` lê o cache geolocalizado e grava
`bairro_aliases.csv` (use `--dry-run` para auditar antes). Depois de gerar ou
editar a referência, rode `uv run spseg ingest`; o fingerprint da referência
dispara o rebuild do estágio 2 sozinho (`--force` só relê o Excel).

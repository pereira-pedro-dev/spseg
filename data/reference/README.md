# Referência

Arquivos pequenos e versionados que enriquecem o cache. Nenhum é obrigatório
para o tool rodar, mas sem eles não há taxas por habitante/domicílio nem
fallback por coordenadas.

## `crime_taxonomy.yml`

Regras de agrupamento das naturezas. **Provisório** até a sessão de metodologia.

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

## `bairros_sp.geojson`

`FeatureCollection` com polígonos oficiais. `properties` aceitos:

- `bairro_id` (ou `id`, `codigo`)
- `bairro_nome` (ou `nome`, `name`)
- `distrito_id` (ou `distrito`) — opcional

Fonte sugerida: GeoSampa (bairros/distritos do município de São Paulo).
Se `bairro_id` não vier nas propriedades, ele é derivado do nome normalizado.

## `populacao_bairro.csv` e `domicilios_bairro.csv`

```csv
bairro_id,bairro_nome,populacao,ano,fonte,nivel
3550308-pinheiros,Pinheiros,112000,2022,IBGE Censo 2022,bairro
```

- `populacao_bairro.csv` usa a coluna de valor `populacao`.
- `domicilios_bairro.csv` usa a coluna de valor `domicilios`.
- `nivel` é `bairro` (padrão) ou `distrito`. Com `distrito`, o identificador em
  `bairro_id` é o `distrito_id` do GeoJSON, e o valor é usado como fallback
  quando não existe denominador por bairro.
- `ano` e `fonte` são informativos e aparecem no resumo.

Sugestão: IBGE Censo 2022 (agregados por setores censitários) somado por bairro
oficial; ou a base de população por distrito/bairro da Prefeitura de São Paulo.

## `bairro_aliases.csv`

```csv
bairro_raw,bairro_id,fonte
JD SAO LUIS,jardim-sao-luis,curado
```

Mapeia grafias brutas do campo `BAIRRO` para o `bairro_id` canônico. A chave é
normalizada (sem acento, maiúscula, abreviações expandidas) antes da comparação.

## Construção

Os scripts `scripts/build_reference.py` e `scripts/build_aliases.py` consolidam
as fontes acima. Eles ainda não estão implementados; até lá, coloque os arquivos
manualmente neste diretório e rode `uv run spseg ingest --force` para aplicar.

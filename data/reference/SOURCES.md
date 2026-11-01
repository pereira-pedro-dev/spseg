# Fontes da referência

Gerado por `scripts/build_reference.py`. Não editar à mão.

| Arquivo cru | URL | SHA-256 | Bytes | Baixado em |
|---|---|---|---|---|
| `distritos_geosampa.geojson` | https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs?service=WFS&version=2.0.0&request=GetFeature&typeName=geoportal:distrito_municipal&outputFormat=application/json&srsName=EPSG:4326 | `b3fb7df2d6266e80a3173bac4054c021707e50bc47256801b553108b80459f0d` | 3.832.607 | 2026-11-01 |
| `distritos_ibge_2022.zip` | https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/Agregados_por_Distrito_csv/Agregados_por_distritos_basico_BR_20260520.zip | `c0ce6f26d8dd8dd3d724b11d7b157b5e9392da78edf037971e84005a9dd4d33b` | 604.488 | 2026-11-01 |

## Camadas e variáveis

- **Distritos (polígonos):** `geoportal:distrito_municipal` no WFS do GeoSampa,
  EPSG:4326. Limites definidos pela Lei Municipal 11.220/1992.
- **População e domicílios:** Censo Demográfico 2022, agregados por distrito.
  `v0001` = total de pessoas; `v0007` = domicílios particulares ocupados (DPO).
  `v0002` (total de domicílios) existe como alternativa.
- **Dicionário:** https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx
- **Metadados GeoSampa:** https://metadados.geosampa.prefeitura.sp.gov.br/

Geometrias sem simplificação (6 casas decimais).

## Licenças

- GeoSampa / Prefeitura de São Paulo: Creative Commons Atribuição (CC-BY).
- IBGE: dados abertos, com atribuição.

## Regenerar

```bash
uv run python scripts/build_reference.py            # baixa e monta
uv run python scripts/build_reference.py --check    # valida sem rede
```

O cache de fatos detecta a mudança pelo fingerprint da referência e refaz o
estágio 2 no próximo `uv run spseg ingest`.

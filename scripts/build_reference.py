#!/usr/bin/env python
"""Gera a referência oficial por distrito (GeoSampa + IBGE Censo 2022).

Uso:
    uv run python scripts/build_reference.py
    uv run python scripts/build_reference.py --offline
    uv run python scripts/build_reference.py --check

O script baixa o GeoJSON de distritos do WFS do GeoSampa e os agregados por
distrito do Censo 2022 (IBGE), casa os dois pelo nome normalizado e escreve:

    data/reference/distritos_sp.geojson
    data/reference/populacao_bairro.csv
    data/reference/domicilios_bairro.csv
    data/reference/SOURCES.md

A fonte crua fica em data/reference/downloads/ (ignorada pelo git).
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import zipfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from shapely.geometry import mapping, shape

from spseg.geo.text import normalize_key

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = PROJECT_ROOT / "data" / "reference"

MUNICIPIO_CODE = "3550308"
EXPECTED_UNITS = 96
CENSO_ANO = 2022

WFS_DISTRITOS_URL = (
    "https://wfs.geosampa.prefeitura.sp.gov.br/geoserver/geoportal/wfs"
    "?service=WFS&version=2.0.0&request=GetFeature"
    "&typeName=geoportal:distrito_municipal"
    "&outputFormat=application/json&srsName=EPSG:4326"
)
IBGE_DISTRITOS_URL = (
    "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/"
    "Agregados_por_Distrito_csv/Agregados_por_distritos_basico_BR_20260520.zip"
)
IBGE_DICTIONARY_URL = (
    "https://ftp.ibge.gov.br/Censos/Censo_Demografico_2022/Agregados_por_Setores_Censitarios/"
    "dicionario_de_dados_agregados_por_setores_censitarios_20260520.xlsx"
)
GEOSAMPA_METADATA_URL = "https://metadados.geosampa.prefeitura.sp.gov.br/"

WFS_DOWNLOAD = "distritos_geosampa.geojson"
IBGE_DOWNLOAD = "distritos_ibge_2022.zip"

GEOJSON_FILE = "distritos_sp.geojson"
POPULACAO_FILE = "populacao_bairro.csv"
DOMICILIOS_FILE = "domicilios_bairro.csv"
SOURCES_FILE = "SOURCES.md"

USER_AGENT = "spseg-reference-builder/1.0"


@dataclass(frozen=True)
class Source:
    filename: str
    url: str
    sha256: str
    size: int
    downloaded_at: str


@dataclass(frozen=True)
class Distrito:
    distrito_id: str
    nome: str
    populacao: int
    domicilios: int


@dataclass(frozen=True)
class Joining:
    nome_geosampa: str
    geometry: dict
    distrito: Distrito


# --------------------------------------------------------------------- download


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source(path: Path, url: str) -> Source:
    stat = path.stat()
    return Source(
        filename=path.name,
        url=url,
        sha256=_sha256(path),
        size=stat.st_size,
        downloaded_at=date.fromtimestamp(stat.st_mtime).isoformat(),
    )


def download(url: str, destination: Path, *, force: bool, offline: bool) -> Source:
    if destination.exists() and not force:
        return _source(destination, url)
    if offline:
        raise SystemExit(
            f"[erro] {destination.name} não existe e --offline foi usado. "
            "Rode sem --offline para baixar."
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    print(f"baixando {url}")
    request = Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urlopen(request, timeout=180) as response:
            payload = response.read()
    except (URLError, OSError) as exc:
        raise SystemExit(f"[erro] falha ao baixar {url}: {exc}") from exc
    destination.write_bytes(payload)
    return _source(destination, url)


# ----------------------------------------------------------------------- fontes


def load_geosampa(path: Path) -> list[tuple[str, dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    features = payload.get("features") or []
    if len(features) != EXPECTED_UNITS:
        raise SystemExit(
            f"[erro] {path.name}: esperava {EXPECTED_UNITS} distritos, encontrei {len(features)}."
        )
    units: list[tuple[str, dict]] = []
    seen: set[str] = set()
    for feature in features:
        properties = feature.get("properties") or {}
        nome = str(properties.get("nm_distrito_municipal") or "").strip()
        geometry = feature.get("geometry")
        if not nome or not geometry:
            raise SystemExit(f"[erro] {path.name}: feature sem nome ou geometria.")
        key = normalize_key(nome)
        if key in seen:
            raise SystemExit(f"[erro] {path.name}: distrito duplicado '{nome}'.")
        seen.add(key)
        units.append((nome, geometry))
    return units


def _parse_int(value: object) -> int | None:
    text = str(value or "").strip().replace("\xa0", "").replace(" ", "")
    if not text or text in {"-", "..", "..."}:
        return None
    # Nos agregados do IBGE o ponto é separador de milhar e a vírgula é decimal.
    text = text.replace(".", "").replace(",", ".")
    try:
        return int(float(text))
    except ValueError:
        return None


def load_ibge(path: Path) -> dict[str, Distrito]:
    with zipfile.ZipFile(path) as archive:
        candidates = [name for name in archive.namelist() if name.lower().endswith(".csv")]
        if len(candidates) != 1:
            raise SystemExit(f"[erro] {path.name}: esperava um CSV, encontrei {len(candidates)}.")
        text = archive.read(candidates[0]).decode("latin-1")

    reader = csv.DictReader(io.StringIO(text), delimiter=";")
    required = {"CD_MUN", "CD_DIST", "NM_DIST", "v0001", "v0007"}
    missing = required.difference(reader.fieldnames or [])
    if missing:
        raise SystemExit(f"[erro] {path.name}: colunas ausentes {sorted(missing)}.")

    distritos: dict[str, Distrito] = {}
    for row in reader:
        if str(row.get("CD_MUN") or "").strip() != MUNICIPIO_CODE:
            continue
        distrito_id = str(row.get("CD_DIST") or "").strip()
        nome = str(row.get("NM_DIST") or "").strip()
        populacao = _parse_int(row.get("v0001"))
        domicilios = _parse_int(row.get("v0007"))
        if not distrito_id or not nome:
            continue
        if populacao is None or domicilios is None:
            raise SystemExit(f"[erro] {path.name}: distrito '{nome}' sem população ou domicílios.")
        distritos[normalize_key(nome)] = Distrito(distrito_id, nome, populacao, domicilios)

    if len(distritos) != EXPECTED_UNITS:
        raise SystemExit(
            f"[erro] {path.name}: esperava {EXPECTED_UNITS} distritos da capital, "
            f"encontrei {len(distritos)}."
        )
    return distritos


def join_sources(geosampa: list[tuple[str, dict]], ibge: dict[str, Distrito]) -> list[Joining]:
    joined: list[Joining] = []
    seen: set[str] = set()
    missing: list[str] = []
    for nome, geometry in geosampa:
        key = normalize_key(nome)
        distrito = ibge.get(key)
        if distrito is None:
            missing.append(nome)
            continue
        seen.add(key)
        joined.append(Joining(nome_geosampa=nome, geometry=geometry, distrito=distrito))
    extra = sorted(set(ibge) - seen)
    if missing or extra:
        lines = ["[erro] o GeoJSON e o CSV do IBGE não batem por nome."]
        if missing:
            lines.append(f"  no GeoJSON sem par no IBGE: {', '.join(missing)}")
        if extra:
            lines.append(f"  no IBGE sem par no GeoJSON: {', '.join(extra)}")
        raise SystemExit("\n".join(lines))
    if len(joined) != EXPECTED_UNITS:
        raise SystemExit(f"[erro] esperava {EXPECTED_UNITS} pares, montei {len(joined)}.")
    return joined


# ---------------------------------------------------------------------- escrita


def _round_coordinates(value: object, digits: int = 6) -> object:
    if isinstance(value, (list, tuple)):
        return [_round_coordinates(item, digits) for item in value]
    if isinstance(value, float):
        return round(value, digits)
    return value


def _geometry_for(geometry: dict, simplify: float) -> dict:
    if simplify > 0:
        simplified = shape(geometry).simplify(simplify, preserve_topology=True)
        geometry = mapping(simplified)
    rounded = dict(geometry)
    rounded["coordinates"] = _round_coordinates(geometry.get("coordinates"))
    return rounded


def write_geojson(path: Path, joined: list[Joining], simplify: float) -> None:
    features = []
    for item in joined:
        distrito = item.distrito
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "bairro_id": distrito.distrito_id,
                    "bairro_nome": distrito.nome,
                    "distrito_id": distrito.distrito_id,
                    "nivel": "distrito",
                    "fonte": "GeoSampa (WFS) + IBGE Censo 2022",
                },
                "geometry": _geometry_for(item.geometry, simplify),
            }
        )
    features.sort(key=lambda feature: feature["properties"]["bairro_nome"])
    payload = {"type": "FeatureCollection", "features": features}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )


def write_denominators(path: Path, joined: list[Joining], column: str, fonte: str) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["bairro_id", "bairro_nome", column, "ano", "fonte", "nivel"])
        for item in sorted(joined, key=lambda current: current.distrito.nome):
            distrito = item.distrito
            value = distrito.populacao if column == "populacao" else distrito.domicilios
            writer.writerow(
                [distrito.distrito_id, distrito.nome, value, CENSO_ANO, fonte, "distrito"]
            )


def write_sources(path: Path, sources: list[Source], simplify: float) -> None:
    rows = "\n".join(
        f"| `{source.filename}` | {source.url} | `{source.sha256}` | "
        f"{source.size:,} | {source.downloaded_at} |".replace(",", ".")
        for source in sources
    )
    simplify_note = (
        f"Geometrias simplificadas com tolerância {simplify} (graus)."
        if simplify > 0
        else "Geometrias sem simplificação (6 casas decimais)."
    )
    path.write_text(
        f"""# Fontes da referência

Gerado por `scripts/build_reference.py`. Não editar à mão.

| Arquivo cru | URL | SHA-256 | Bytes | Baixado em |
|---|---|---|---|---|
{rows}

## Camadas e variáveis

- **Distritos (polígonos):** `geoportal:distrito_municipal` no WFS do GeoSampa,
  EPSG:4326. Limites definidos pela Lei Municipal 11.220/1992.
- **População e domicílios:** Censo Demográfico 2022, agregados por distrito.
  `v0001` = total de pessoas; `v0007` = domicílios particulares ocupados (DPO).
  `v0002` (total de domicílios) existe como alternativa.
- **Dicionário:** {IBGE_DICTIONARY_URL}
- **Metadados GeoSampa:** {GEOSAMPA_METADATA_URL}

{simplify_note}

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
""",
        encoding="utf-8",
    )


# ------------------------------------------------------------------- validação


def check(output_dir: Path) -> int:
    errors: list[str] = []
    geojson_path = output_dir / GEOJSON_FILE
    if not geojson_path.exists():
        print(f"[erro] {geojson_path} não existe.")
        return 1
    try:
        payload = json.loads(geojson_path.read_text(encoding="utf-8"))
        features = payload.get("features") or []
    except (OSError, json.JSONDecodeError) as exc:
        print(f"[erro] {GEOJSON_FILE}: não foi possível ler ({exc}).")
        return 1

    if len(features) != EXPECTED_UNITS:
        errors.append(f"{GEOJSON_FILE}: {len(features)} features (esperado {EXPECTED_UNITS}).")

    ids: set[str] = set()
    for feature in features:
        properties = feature.get("properties") or {}
        identifier = str(properties.get("bairro_id") or "")
        nome = str(properties.get("bairro_nome") or "")
        distrito_id = str(properties.get("distrito_id") or "")
        if not identifier or not nome:
            errors.append(f"{GEOJSON_FILE}: feature sem bairro_id/bairro_nome.")
            continue
        if identifier in ids:
            errors.append(f"{GEOJSON_FILE}: id duplicado '{identifier}'.")
        ids.add(identifier)
        if not distrito_id:
            errors.append(f"{GEOJSON_FILE}: '{nome}' sem distrito_id (taxas ficariam n/d).")
        if properties.get("nivel") != "distrito":
            errors.append(f"{GEOJSON_FILE}: '{nome}' com nivel != distrito.")

    for filename, column in (
        (POPULACAO_FILE, "populacao"),
        (DOMICILIOS_FILE, "domicilios"),
    ):
        path = output_dir / filename
        if not path.exists():
            errors.append(f"{filename}: ausente.")
            continue
        with path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        if len(rows) != EXPECTED_UNITS:
            errors.append(f"{filename}: {len(rows)} linhas (esperado {EXPECTED_UNITS}).")
        file_ids = {str(row.get("bairro_id") or "") for row in rows}
        if file_ids != ids:
            errors.append(f"{filename}: ids diferentes do GeoJSON.")
        for row in rows:
            value = _parse_int(row.get(column))
            if value is None or value <= 0:
                errors.append(f"{filename}: valor inválido em '{row.get('bairro_nome')}'.")
            if row.get("nivel") != "distrito":
                errors.append(f"{filename}: '{row.get('bairro_nome')}' com nivel != distrito.")

    if errors:
        for error in errors:
            print(f"[erro] {error}")
        return 1
    print(f"[ok] {EXPECTED_UNITS} distritos; GeoJSON e denominadores consistentes.")
    return 0


# ------------------------------------------------------------------------ main


def build(output_dir: Path, *, offline: bool, force: bool, simplify: float) -> None:
    downloads = output_dir / "downloads"
    output_dir.mkdir(parents=True, exist_ok=True)

    wfs_source = download(WFS_DISTRITOS_URL, downloads / WFS_DOWNLOAD, force=force, offline=offline)
    ibge_source = download(
        IBGE_DISTRITOS_URL, downloads / IBGE_DOWNLOAD, force=force, offline=offline
    )

    geosampa = load_geosampa(downloads / WFS_DOWNLOAD)
    ibge = load_ibge(downloads / IBGE_DOWNLOAD)
    joined = join_sources(geosampa, ibge)

    write_geojson(output_dir / GEOJSON_FILE, joined, simplify)
    write_denominators(
        output_dir / POPULACAO_FILE,
        joined,
        "populacao",
        "IBGE Censo 2022 (universo)",
    )
    write_denominators(
        output_dir / DOMICILIOS_FILE,
        joined,
        "domicilios",
        "IBGE Censo 2022 (DPO)",
    )
    write_sources(output_dir / SOURCES_FILE, [wfs_source, ibge_source], simplify)

    size = (output_dir / GEOJSON_FILE).stat().st_size / (1024 * 1024)
    print(f"[ok] {len(joined)} distritos")
    print(f"[ok] {GEOJSON_FILE} ({size:.2f} MB)")
    print(f"[ok] {POPULACAO_FILE} e {DOMICILIOS_FILE}")
    print(f"[ok] {SOURCES_FILE}")
    if simplify > 0:
        print(
            "[aviso] geometrias simplificadas: pontos muito próximos da divisa "
            "podem cair no distrito vizinho."
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REFERENCE_DIR,
        help=f"diretório de saída (padrão: {REFERENCE_DIR})",
    )
    parser.add_argument("--offline", action="store_true", help="usa apenas downloads já feitos")
    parser.add_argument("--force", action="store_true", help="baixa de novo mesmo se já existir")
    parser.add_argument(
        "--simplify",
        type=float,
        default=0.0,
        metavar="GRAUS",
        help="simplifica as geometrias (ex.: 0.00005 ≈ 5 m); padrão: sem simplificação",
    )
    parser.add_argument("--check", action="store_true", help="valida as saídas sem baixar nada")
    args = parser.parse_args(argv)

    if args.simplify < 0:
        parser.error("--simplify deve ser >= 0")

    output_dir = args.output_dir.expanduser().resolve()
    if args.check:
        return check(output_dir)
    build(
        output_dir,
        offline=args.offline,
        force=args.force,
        simplify=args.simplify,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

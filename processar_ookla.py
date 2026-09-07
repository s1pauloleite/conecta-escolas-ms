"""
processar_ookla.py
--------------------
Filtra o Ookla Open Data (Speedtest by Ookla) para a região de Mato
Grosso do Sul e calcula uma velocidade/latência média REAL por
município, usada por `etl.py` para calibrar a simulação de medições por
escola (ver docstring de `_popular_medicoes` em `etl.py`).

Fonte: "Speedtest by Ookla Global Fixed Broadband Performance Tiles",
trimestre 2026-Q2 (https://github.com/teamookla/ookla-open-data).
Licença: CC BY-NC-SA 4.0 — atribuição obrigatória, uso não comercial,
compartilhamento pela mesma licença. Adequado para este projeto
acadêmico; **não** redistribuir/usar comercialmente sem rever a licença.

⚠️ O que este dado É: a velocidade média de todos os testes de Speedtest
feitos por usuários reais dentro de um quadrado de ~600m x 600m
("tile"), num trimestre. O que NÃO é: a velocidade medida dentro de uma
escola específica — o Ookla não sabe o que é escola, é só quem testou a
internet perto dali. Por isso o resultado deste script vira um valor
"real, mas regional" por MUNICÍPIO (não por escola), usado como âncora
para calibrar a simulação por escola em vez de números arbitrários.

Pré-requisitos (não versionados — ver data/raw/README.md):
    data/raw/ookla_fixed_tiles_2026q2.parquet
    data/raw/municipios_brasileiros_coords.csv

Uso:
    python processar_ookla.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq

from tile_math import lat_lon_para_tile_xy, quadkeys_vizinhos_por_distancia

DATA_RAW_DIR = Path(__file__).resolve().parent / "data" / "raw"
PARQUET_OOKLA = DATA_RAW_DIR / "ookla_fixed_tiles_2026q2.parquet"
CSV_COORDS_MUNICIPIOS = DATA_RAW_DIR / "municipios_brasileiros_coords.csv"
CSV_SAIDA = DATA_RAW_DIR / "conectividade_municipio_ookla.csv"

CO_UF_MS = 50
ZOOM = 16  # zoom dos tiles do Ookla (~610m x 610m no equador)

# Bounding box de MS com margem: municípios grandes (ex.: Corumbá, na
# fronteira com a Bolívia) se estendem bem além da coordenada da sede.
LAT_MIN, LAT_MAX = -25.5, -16.0
LON_MIN, LON_MAX = -59.5, -49.5

RAIO_MAXIMO_TILES = 20  # ~12 km nessa latitude — teto antes de desistir
TESTES_MINIMOS_DESEJADOS = 30  # acumula tiles vizinhos até juntar esse tanto de testes


def carregar_tiles_ms() -> pd.DataFrame:
    """Lê só os tiles do Ookla dentro do bounding box de MS.

    O arquivo é global (~6,4 milhões de tiles); projeta só as colunas
    necessárias (sem a geometria WKT) para manter o uso de memória baixo,
    e filtra localmente pelo bounding box logo em seguida.
    """
    tabela = pq.read_table(
        PARQUET_OOKLA,
        columns=["quadkey", "tile_x", "tile_y", "avg_d_kbps", "avg_u_kbps", "avg_lat_ms", "tests"],
    )
    df = tabela.to_pandas()
    dentro_do_bbox = df["tile_y"].between(LAT_MIN, LAT_MAX) & df["tile_x"].between(LON_MIN, LON_MAX)
    df = df[dentro_do_bbox].drop_duplicates(subset="quadkey").set_index("quadkey")
    print(f"  {len(df)} tiles do Ookla dentro do bounding box de MS (de {len(tabela)} no mundo todo).")
    return df


def carregar_municipios_ms() -> pd.DataFrame:
    coords = pd.read_csv(CSV_COORDS_MUNICIPIOS, dtype={"codigo_ibge": "Int64"})
    return coords[coords["codigo_uf"] == CO_UF_MS][["codigo_ibge", "nome", "latitude", "longitude"]]


def _buscar_tiles_proximos(tiles_ms: pd.DataFrame, latitude: float, longitude: float) -> pd.DataFrame | None:
    """Acumula os tiles mais próximos de (latitude, longitude) até juntar
    testes suficientes, expandindo o raio de busca só o quanto for preciso.

    Retorna `None` se nem no raio máximo houver dado nenhum (município
    numa região sem nenhum teste de Speedtest registrado no trimestre).
    """
    tile_x, tile_y = lat_lon_para_tile_xy(latitude, longitude, ZOOM)
    candidatos_por_distancia = quadkeys_vizinhos_por_distancia(tile_x, tile_y, ZOOM, RAIO_MAXIMO_TILES)

    linhas_encontradas = []
    testes_acumulados = 0
    for quadkey in candidatos_por_distancia:
        if quadkey not in tiles_ms.index:
            continue
        linha = tiles_ms.loc[quadkey]
        linhas_encontradas.append(linha)
        testes_acumulados += int(linha["tests"])
        if testes_acumulados >= TESTES_MINIMOS_DESEJADOS:
            break

    if not linhas_encontradas:
        return None
    return pd.DataFrame(linhas_encontradas)


def calcular_conectividade_por_municipio(tiles_ms: pd.DataFrame, municipios: pd.DataFrame) -> pd.DataFrame:
    linhas = []
    for municipio in municipios.itertuples(index=False):
        tiles_proximos = _buscar_tiles_proximos(tiles_ms, municipio.latitude, municipio.longitude)

        if tiles_proximos is None:
            linhas.append(
                {
                    "co_municipio": municipio.codigo_ibge,
                    "no_municipio": municipio.nome,
                    "avg_download_mbps": None,
                    "avg_upload_mbps": None,
                    "avg_latencia_ms": None,
                    "num_tiles_ookla": 0,
                    "num_testes_ookla": 0,
                }
            )
            continue

        pesos = tiles_proximos["tests"]
        total_testes = pesos.sum()
        media_download_mbps = (tiles_proximos["avg_d_kbps"] * pesos).sum() / total_testes / 1000
        media_upload_mbps = (tiles_proximos["avg_u_kbps"] * pesos).sum() / total_testes / 1000
        media_latencia_ms = (tiles_proximos["avg_lat_ms"] * pesos).sum() / total_testes

        linhas.append(
            {
                "co_municipio": municipio.codigo_ibge,
                "no_municipio": municipio.nome,
                "avg_download_mbps": round(media_download_mbps, 2),
                "avg_upload_mbps": round(media_upload_mbps, 2),
                "avg_latencia_ms": round(media_latencia_ms, 1),
                "num_tiles_ookla": len(tiles_proximos),
                "num_testes_ookla": int(total_testes),
            }
        )

    return pd.DataFrame(linhas)


def main() -> None:
    if not PARQUET_OOKLA.exists():
        raise SystemExit(
            f"Não encontrei {PARQUET_OOKLA}.\n"
            "Baixe o parquet de performance fixa do trimestre em "
            "https://github.com/teamookla/ookla-open-data (URL direto documentado em "
            "data/raw/README.md) e salve com esse nome antes de rodar este script."
        )
    if not CSV_COORDS_MUNICIPIOS.exists():
        raise SystemExit(f"Não encontrei {CSV_COORDS_MUNICIPIOS} — rode processar_censo_escolar.py primeiro.")

    print("Lendo tiles do Ookla (arquivo grande, pode levar um instante)...")
    tiles_ms = carregar_tiles_ms()

    municipios = carregar_municipios_ms()
    print(f"Calculando conectividade para {len(municipios)} municípios de MS...")
    resultado = calcular_conectividade_por_municipio(tiles_ms, municipios)

    sem_cobertura = resultado["avg_download_mbps"].isna().sum()
    if sem_cobertura:
        print(f"  aviso: {sem_cobertura} município(s) sem nenhum tile do Ookla no raio de busca.")

    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    resultado.to_csv(CSV_SAIDA, index=False, encoding="utf-8")
    print(f"\nGravado: {CSV_SAIDA} ({len(resultado) - sem_cobertura}/{len(resultado)} municípios com dado real)")
    print(resultado.sort_values("avg_download_mbps", ascending=False).head(10).to_string(index=False))


if __name__ == "__main__":
    main()

"""
processar_censo_escolar.py
----------------------------
Extrai, do microdado nacional do Censo Escolar (INEP), apenas as escolas
de Mato Grosso do Sul em atividade, e grava um CSV pronto para `etl.py`
em `data/raw/escolas_censo_ms.csv`.

Por que um script separado de `fetch_dados_oficiais.py`: aquele fala com
APIs (chamadas pequenas, ao vivo); este processa um arquivo estático já
baixado localmente (o zip de ~512 MB do INEP, que não cabe numa chamada
de API e não faz sentido re-baixar a cada execução do ETL).

Pré-requisito (não versionado — veja `data/raw/README.md`):
    data/raw/microdados_censo_escolar_2025.zip
    (baixado de https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/censo-escolar)

    data/raw/municipios_brasileiros_coords.csv
    (https://github.com/kelvins/municipios-brasileiros — usado só para
    aproximar a localização das escolas pela sede do município; ver nota
    de transparência abaixo)

⚠️ Transparência sobre geolocalização: o microdado aberto do Censo Escolar
NÃO publica latitude/longitude por escola (removido por política de
proteção de dados). Este script posiciona cada escola nas proximidades da
sede do seu município (coordenada do município + um pequeno deslocamento
aleatório determinístico, só para as escolas não ficarem todas empilhadas
no mesmo ponto do mapa). Isso é suficiente para a análise agregada por
município deste painel, mas **não** deve ser lido como a localização real
da escola — cada registro carrega `geo_aproximada = 1` para deixar isso
explícito também no banco de dados.

Uso:
    python processar_censo_escolar.py
"""

from __future__ import annotations

import random
import zipfile
from pathlib import Path

import pandas as pd

DATA_RAW_DIR = Path(__file__).resolve().parent / "data" / "raw"
ZIP_CENSO = DATA_RAW_DIR / "microdados_censo_escolar_2025.zip"
CSV_COORDS_MUNICIPIOS = DATA_RAW_DIR / "municipios_brasileiros_coords.csv"
CSV_SAIDA = DATA_RAW_DIR / "escolas_censo_ms.csv"

NOME_ARQUIVO_ESCOLA = "microdados_censo_escolar_2025_v2/dados/Tabela_Escola_2025_V2.csv"
NOME_ARQUIVO_MATRICULA = "microdados_censo_escolar_2025_v2/dados/Tabela_Matricula_2025_V2.csv"

CO_UF_MS = 50
SITUACAO_EM_ATIVIDADE = 1
LOCALIZACAO_URBANA, LOCALIZACAO_RURAL = 1, 2

# TP_REDE_LOCAL (dicionário de dados do INEP): 0=nenhuma, 1=a cabo,
# 2=wireless, 3=a cabo e wireless, 9=não informado.
MAPA_REDE_LOCAL = {
    0: "Nenhuma",
    1: "A cabo",
    2: "Wireless",
    3: "A cabo e Wireless",
    9: "Não informado",
}

# TP_DEPENDENCIA (dicionário de dados do INEP): 1=federal, 2=estadual,
# 3=municipal, 4=privada.
MAPA_DEPENDENCIA = {
    1: "Federal",
    2: "Estadual",
    3: "Municipal",
    4: "Privada",
}

JITTER_GRAUS = 0.05  # ~5 km, só para espalhar visualmente escolas do mesmo município
SEED_JITTER = 42


def _ler_csv_do_zip(caminho_zip: Path, nome_interno: str, colunas: list[str]) -> pd.DataFrame:
    with zipfile.ZipFile(caminho_zip) as zip_arquivo:
        with zip_arquivo.open(nome_interno) as arquivo:
            return pd.read_csv(
                arquivo,
                sep=";",
                encoding="cp1252",
                usecols=colunas,
                dtype={"CO_ENTIDADE": "Int64", "CO_MUNICIPIO": "Int64"},
                low_memory=False,
            )


def extrair_escolas_ms() -> pd.DataFrame:
    print(f"Lendo escolas de {NOME_ARQUIVO_ESCOLA} (isso lê ~135 MB, pode levar um instante)...")
    escolas = _ler_csv_do_zip(
        ZIP_CENSO,
        NOME_ARQUIVO_ESCOLA,
        [
            "CO_UF",
            "CO_ENTIDADE",
            "NO_ENTIDADE",
            "CO_MUNICIPIO",
            "NO_MUNICIPIO",
            "TP_LOCALIZACAO",
            "TP_DEPENDENCIA",
            "TP_SITUACAO_FUNCIONAMENTO",
            "IN_INTERNET",
            "IN_BANDA_LARGA",
            "IN_INTERNET_ALUNOS",
            "TP_REDE_LOCAL",
        ],
    )
    escolas_ms = escolas[
        (escolas["CO_UF"] == CO_UF_MS) & (escolas["TP_SITUACAO_FUNCIONAMENTO"] == SITUACAO_EM_ATIVIDADE)
    ].copy()
    print(f"  {len(escolas_ms)} escolas de MS em atividade (de {len(escolas)} escolas no Brasil).")
    return escolas_ms


def extrair_matriculas_ms(codigos_entidade_ms: pd.Series) -> pd.DataFrame:
    print(f"Lendo matrículas de {NOME_ARQUIVO_MATRICULA} (~118 MB)...")
    matriculas = _ler_csv_do_zip(
        ZIP_CENSO, NOME_ARQUIVO_MATRICULA, ["CO_ENTIDADE", "QT_MAT_BAS"]
    )
    matriculas_ms = matriculas[matriculas["CO_ENTIDADE"].isin(codigos_entidade_ms)]
    print(f"  {len(matriculas_ms)} registros de matrícula casados com escolas de MS.")
    return matriculas_ms


def carregar_coordenadas_municipios() -> pd.DataFrame:
    coords = pd.read_csv(CSV_COORDS_MUNICIPIOS, dtype={"codigo_ibge": "Int64"})
    coords_ms = coords[coords["codigo_uf"] == CO_UF_MS][["codigo_ibge", "latitude", "longitude"]]
    coords_ms = coords_ms.rename(columns={"codigo_ibge": "CO_MUNICIPIO"})
    return coords_ms


def aplicar_localizacao_aproximada(df: pd.DataFrame, coords_municipios: pd.DataFrame) -> pd.DataFrame:
    df = df.merge(coords_municipios, on="CO_MUNICIPIO", how="left")

    sem_coordenada = df["latitude"].isna().sum()
    if sem_coordenada:
        print(f"  aviso: {sem_coordenada} escola(s) em município sem coordenada de referência.")

    rng = random.Random(SEED_JITTER)

    def _jitter(valor: float | None) -> float | None:
        if pd.isna(valor):
            return None
        return round(valor + rng.uniform(-JITTER_GRAUS, JITTER_GRAUS), 6)

    df["latitude"] = df["latitude"].apply(_jitter)
    df["longitude"] = df["longitude"].apply(_jitter)
    df["geo_aproximada"] = 1
    return df


def montar_tabela_final(escolas_ms: pd.DataFrame, matriculas_ms: pd.DataFrame, coords_municipios: pd.DataFrame) -> pd.DataFrame:
    tabela = escolas_ms.merge(matriculas_ms, on="CO_ENTIDADE", how="left")
    tabela["QT_MAT_BAS"] = tabela["QT_MAT_BAS"].fillna(0).astype(int)

    # IN_BANDA_LARGA vem em branco quando a escola não tem internet (o
    # questionário nem pergunta sobre banda larga nesse caso) — sem
    # internet nenhuma implica sem banda larga, então 0 é a leitura
    # correta do dado ausente, não um valor inventado.
    tabela["IN_INTERNET"] = tabela["IN_INTERNET"].fillna(0).astype(int)
    tabela["IN_BANDA_LARGA"] = tabela["IN_BANDA_LARGA"].fillna(0).astype(int)
    tabela["IN_INTERNET_ALUNOS"] = tabela["IN_INTERNET_ALUNOS"].fillna(0).astype(int)
    # TP_REDE_LOCAL vem em branco pelo mesmo motivo de IN_BANDA_LARGA (sem
    # internet, o questionário nem pergunta) — tratado como "Não informado"
    # (9), não como "Nenhuma" (0), já que a ausência de rede local não é a
    # mesma coisa que ausência de resposta.
    tabela["rede_local"] = tabela["TP_REDE_LOCAL"].fillna(9).astype(int).map(MAPA_REDE_LOCAL)

    tabela["tp_localizacao"] = tabela["TP_LOCALIZACAO"].map(
        {LOCALIZACAO_URBANA: "Urbana", LOCALIZACAO_RURAL: "Rural"}
    )
    tabela = tabela.dropna(subset=["tp_localizacao"])  # descarta códigos de localização não mapeados/ausentes

    tabela["dependencia_administrativa"] = tabela["TP_DEPENDENCIA"].map(MAPA_DEPENDENCIA)
    tabela = tabela.dropna(subset=["dependencia_administrativa"])  # idem, para dependência administrativa

    tabela = aplicar_localizacao_aproximada(tabela, coords_municipios)

    tabela = tabela.rename(
        columns={
            "CO_ENTIDADE": "co_entidade",
            "NO_ENTIDADE": "no_entidade",
            "CO_MUNICIPIO": "co_municipio",
            "IN_INTERNET": "in_internet",
            "IN_BANDA_LARGA": "in_banda_larga",
            "IN_INTERNET_ALUNOS": "in_internet_alunos",
            "QT_MAT_BAS": "qt_matriculas",
        }
    )

    return tabela[
        [
            "co_entidade",
            "no_entidade",
            "co_municipio",
            "tp_localizacao",
            "dependencia_administrativa",
            "in_internet",
            "in_banda_larga",
            "in_internet_alunos",
            "rede_local",
            "qt_matriculas",
            "latitude",
            "longitude",
            "geo_aproximada",
        ]
    ].sort_values(["co_municipio", "no_entidade"])


def main() -> None:
    if not ZIP_CENSO.exists():
        raise SystemExit(
            f"Não encontrei {ZIP_CENSO}.\n"
            "Baixe o microdado do Censo Escolar em "
            "https://www.gov.br/inep/pt-br/acesso-a-informacao/dados-abertos/microdados/censo-escolar "
            "e salve o zip com esse nome antes de rodar este script."
        )
    if not CSV_COORDS_MUNICIPIOS.exists():
        raise SystemExit(
            f"Não encontrei {CSV_COORDS_MUNICIPIOS}.\n"
            "Baixe https://raw.githubusercontent.com/kelvins/municipios-brasileiros/main/csv/municipios.csv "
            "e salve com esse nome antes de rodar este script."
        )

    escolas_ms = extrair_escolas_ms()
    matriculas_ms = extrair_matriculas_ms(escolas_ms["CO_ENTIDADE"])
    coords_municipios = carregar_coordenadas_municipios()

    tabela_final = montar_tabela_final(escolas_ms, matriculas_ms, coords_municipios)

    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    tabela_final.to_csv(CSV_SAIDA, index=False, encoding="utf-8")
    print(f"\nGravado: {CSV_SAIDA} ({len(tabela_final)} escolas)")

    print("\nResumo por localização:")
    print(tabela_final["tp_localizacao"].value_counts().to_string())
    print("\nResumo por dependência administrativa:")
    print(tabela_final["dependencia_administrativa"].value_counts().to_string())
    print("\nResumo de conectividade (in_internet):")
    print(tabela_final["in_internet"].value_counts().to_string())
    print("\nResumo de rede local (wifi/cabo):")
    print(tabela_final["rede_local"].value_counts().to_string())


if __name__ == "__main__":
    main()

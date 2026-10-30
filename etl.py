"""
etl.py
-------
Pipeline de extração, transformação e carga (ETL) de dados do ConectaEscolas MS.

Este script é OFFLINE por design: ele lê o que já estiver em `data/raw/`
(gerado por `fetch_dados_oficiais.py` e `processar_censo_escolar.py`) e
carrega no banco. Se um desses arquivos não existir, cada camada volta
sozinha para uma amostra sintética/determinística equivalente — assim o
painel sempre roda, mesmo sem internet ou sem ter rodado a busca de dados
oficiais ainda (por exemplo, na hora da apresentação).

Camadas e suas fontes nesta versão:
    municípios → REAL, se `data/raw/municipios_oficiais.csv` existir
                 (IBGE: municípios/população · Siconfi: investimento em
                 educação); senão, amostra sintética de 13 municípios.
    escolas    → REAL, se `data/raw/escolas_censo_ms.csv` existir (INEP
                 Censo Escolar 2025, filtrado a MS); senão, amostra
                 sintética de 18 escolas. A geolocalização é REAL (do
                 NIC.br — ver abaixo) para as escolas cobertas por aquele
                 arquivo; para as demais, aproximada pela sede do
                 município — ver `geo_aproximada` na tabela.
    medições   → três níveis de procedência, do melhor para o pior:
                 (1) REAL, se `data/raw/medicoes_reais_nicbr.csv` existir
                 (medição SIMET de verdade, exportada manualmente do
                 painel Conectividade na Educação do NIC.br — ver
                 `processar_nicbr_simet.py`); (2) estimativa ANCORADA na
                 velocidade real do Ookla Speedtest para o município, se
                 `data/raw/conectividade_municipio_ookla.csv` existir
                 (ver `logic.simular_medicao_calibrada`); (3) faixa
                 genérica sintética, se nenhuma das duas anteriores
                 estiver disponível para aquela escola/município.
    provedores → sempre um levantamento de mercado ilustrativo (Fase 3).

A origem efetivamente usada em cada carga fica registrada na tabela
`metadata_execucao`, que `app.py` lê para mostrar a procedência dos dados
na interface em vez de deixar isso implícito.

Uso:
    python etl.py
"""

from __future__ import annotations

import csv
import random
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from database import get_connection
from logic import simular_medicao_calibrada

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_RAW_DIR = DATA_DIR / "raw"
SEED = 42  # garante que a amostra sintética seja sempre a mesma entre execuções

CSV_MUNICIPIOS_OFICIAIS = DATA_RAW_DIR / "municipios_oficiais.csv"
CSV_ESCOLAS_CENSO = DATA_RAW_DIR / "escolas_censo_ms.csv"
CSV_CONECTIVIDADE_OOKLA = DATA_RAW_DIR / "conectividade_municipio_ookla.csv"
CSV_MEDICOES_REAIS_NICBR = DATA_RAW_DIR / "medicoes_reais_nicbr.csv"

INSERT_MUNICIPIOS_SQL = """
INSERT INTO municipios
    (co_municipio, no_municipio, nota_transparencia_ebt,
     investimento_per_capita_educacao, conselho_educacao_ativo, populacao_estimada)
VALUES (?, ?, ?, ?, ?, ?);
"""

INSERT_ESCOLAS_SQL = """
INSERT INTO escolas
    (co_entidade, no_entidade, co_municipio, tp_localizacao,
     dependencia_administrativa, in_internet, in_banda_larga,
     in_internet_alunos, rede_local, qt_matriculas, latitude, longitude,
     geo_aproximada)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
"""
# Índice (0-based) de geo_aproximada dentro das tuplas montadas com
# INSERT_ESCOLAS_SQL acima — usado para contar quantas escolas ficaram
# com geolocalização real vs. aproximada, sem duplicar a lista de campos.
INDICE_GEO_APROXIMADA = 12


def _limpar_tabelas(cursor: sqlite3.Cursor) -> None:
    """Remove dados de execuções anteriores, tornando a carga idempotente."""
    for tabela in ("medicoes_simet", "escolas", "municipios", "alternativas_mercado", "metadata_execucao"):
        cursor.execute(f"DELETE FROM {tabela};")


def _nulo_se_vazio(valor):
    """Converte NaN/None (célula ausente no CSV) em `None`, preservando o valor caso contrário."""
    return None if pd.isna(valor) else valor


# --------------------------------------------------------------------------- #
# Municípios
# --------------------------------------------------------------------------- #


def _popular_municipios_oficiais(cursor: sqlite3.Cursor) -> list[tuple]:
    """Carrega `data/raw/municipios_oficiais.csv` (IBGE + Siconfi — ver fetch_dados_oficiais.py)."""
    df = pd.read_csv(CSV_MUNICIPIOS_OFICIAIS)
    registros = [
        (
            int(linha.co_municipio),
            linha.no_municipio,
            _nulo_se_vazio(linha.nota_transparencia_ebt),
            _nulo_se_vazio(linha.investimento_per_capita_educacao),
            _nulo_se_vazio(linha.conselho_educacao_ativo),
            _nulo_se_vazio(linha.populacao_estimada),
        )
        for linha in df.itertuples(index=False)
    ]
    cursor.executemany(INSERT_MUNICIPIOS_SQL, registros)
    return registros


def _popular_municipios_sinteticos(cursor: sqlite3.Cursor) -> list[tuple]:
    """Municípios de MS (código IBGE real); indicadores de governança sintéticos.

    Amostra de apoio, usada só quando `data/raw/municipios_oficiais.csv`
    não está disponível (ex.: sem internet para rodar `fetch_dados_oficiais.py`).
    """
    municipios_ms = [
        (5002704, "Campo Grande", 9.8, 1200.50, 1, 900000),
        (5003702, "Dourados", 8.5, 950.80, 1, 225000),
        (5003207, "Corumbá", 7.2, 850.40, 1, 112000),
        (5008305, "Três Lagoas", 8.9, 1100.20, 1, 125000),
        (5006606, "Ponta Porã", 6.8, 790.15, 1, 92000),
        (5001102, "Aquidauana", 7.0, 810.00, 1, 48000),
        (5001904, "Bataguassu", 8.2, 1350.00, 1, 23000),
        (5002407, "Caarapó", 7.5, 900.00, 1, 30000),
        (5003157, "Corguinho", 6.0, 720.00, 0, 6000),
        (5004304, "Guia Lopes da Laguna", 6.2, 740.00, 1, 10000),
        (5005004, "Itaporã", 7.8, 880.00, 1, 24000),
        (5006200, "Nova Alvorada do Sul", 7.1, 920.00, 1, 22000),
        (5007307, "Rio Negro", 5.9, 680.00, 0, 5000),
    ]
    cursor.executemany(INSERT_MUNICIPIOS_SQL, municipios_ms)
    return municipios_ms


def _popular_municipios(cursor: sqlite3.Cursor) -> tuple[list[tuple], str]:
    if CSV_MUNICIPIOS_OFICIAIS.exists():
        try:
            registros = _popular_municipios_oficiais(cursor)
            return registros, "oficial (IBGE: municípios/população · Siconfi: investimento em educação)"
        except Exception as erro:  # dado externo mal-formado não deve derrubar o ETL
            print(f"  aviso: falha ao carregar {CSV_MUNICIPIOS_OFICIAIS.name} ({erro}); usando amostra sintética.")
            cursor.execute("DELETE FROM municipios;")  # desfaz qualquer inserção parcial

    registros = _popular_municipios_sinteticos(cursor)
    return registros, "sintético (13 municípios de demonstração)"


# --------------------------------------------------------------------------- #
# Escolas
# --------------------------------------------------------------------------- #


def _carregar_nicbr_simet() -> dict[int, dict]:
    """Lê `data/raw/medicoes_reais_nicbr.csv` (ver processar_nicbr_simet.py).

    Retorna um dict `co_entidade -> {...}` com geolocalização real e,
    quando disponível, medição SIMET real de verdade — exportada
    manualmente do painel Conectividade na Educação do NIC.br (não existe
    API pública; ver README.md). Escolas fora deste dict (ex.: privadas,
    não cobertas por aquele painel) simplesmente não aparecem, e quem
    chama trata isso como "sem dado real do NIC.br disponível".
    """
    if not CSV_MEDICOES_REAIS_NICBR.exists():
        return {}

    df = pd.read_csv(CSV_MEDICOES_REAIS_NICBR)
    return {
        int(linha.co_entidade): {
            "latitude": _nulo_se_vazio(linha.latitude),
            "longitude": _nulo_se_vazio(linha.longitude),
            "tem_medicao_propria": bool(linha.tem_medicao_propria),
            "velocidade_download_mbps": _nulo_se_vazio(linha.velocidade_download_mbps),
            "velocidade_upload_mbps": _nulo_se_vazio(linha.velocidade_upload_mbps),
            "latencia_ms": _nulo_se_vazio(linha.latencia_ms),
            "perda_pacotes_pct": _nulo_se_vazio(linha.perda_pacotes_pct),
            "jitter_download_ms": _nulo_se_vazio(linha.jitter_download_ms),
            "jitter_upload_ms": _nulo_se_vazio(linha.jitter_upload_ms),
        }
        for linha in df.itertuples(index=False)
    }


def _popular_escolas_oficiais(
    cursor: sqlite3.Cursor, municipios_validos: set[int], nicbr_por_escola: dict[int, dict]
) -> list[tuple]:
    """Carrega `data/raw/escolas_censo_ms.csv` (INEP Censo Escolar — ver processar_censo_escolar.py).

    Quando a escola também aparece em `nicbr_por_escola` com lat/lon
    preenchidos, usa essa geolocalização REAL no lugar da aproximação
    pela sede do município (`geo_aproximada` vira 0 nesse caso).
    """
    df = pd.read_csv(CSV_ESCOLAS_CENSO)

    fora_do_cadastro = ~df["co_municipio"].isin(municipios_validos)
    if fora_do_cadastro.any():
        # Defensivo: garante integridade referencial mesmo se o Censo Escolar
        # e a lista de municípios carregada divergirem em algum código.
        print(f"  aviso: {fora_do_cadastro.sum()} escola(s) com município fora do cadastro; ignoradas.")
        df = df[~fora_do_cadastro]

    registros = []
    for linha in df.itertuples(index=False):
        co_entidade = int(linha.co_entidade)
        latitude = _nulo_se_vazio(linha.latitude)
        longitude = _nulo_se_vazio(linha.longitude)
        geo_aproximada = int(linha.geo_aproximada)

        dado_nicbr = nicbr_por_escola.get(co_entidade)
        if dado_nicbr and dado_nicbr["latitude"] is not None and dado_nicbr["longitude"] is not None:
            latitude = float(dado_nicbr["latitude"])
            longitude = float(dado_nicbr["longitude"])
            geo_aproximada = 0  # geolocalização real (NIC.br), não aproximação por município

        registros.append(
            (
                co_entidade,
                linha.no_entidade,
                int(linha.co_municipio),
                linha.tp_localizacao,
                linha.dependencia_administrativa,
                int(linha.in_internet),
                int(linha.in_banda_larga),
                int(linha.in_internet_alunos),
                linha.rede_local,
                int(linha.qt_matriculas),
                latitude,
                longitude,
                geo_aproximada,
            )
        )

    cursor.executemany(INSERT_ESCOLAS_SQL, registros)
    return registros


def _popular_escolas_sinteticas(cursor: sqlite3.Cursor) -> list[tuple]:
    """Duas escolas (1 urbana + 1 rural) por município, com coordenadas fictícias.

    Amostra de apoio, usada só quando `data/raw/escolas_censo_ms.csv` não
    está disponível (ex.: o Censo Escolar ainda não foi baixado/processado).
    """
    rng = random.Random(SEED)

    escolas_nomes = [
        ("EE Maria Constança", "Urbana", 5002704, -20.464, -54.612),
        ("EM Agrícola Gov. Arnaldo Estevão de Figueiredo", "Rural", 5002704, -20.621, -54.380),
        ("EE Presidente Vargas", "Urbana", 5003702, -22.223, -54.808),
        ("EE Rural Castro Alves", "Rural", 5003702, -22.140, -54.610),
        ("EE Júlia Gonçalves Passarinho", "Urbana", 5003207, -19.005, -57.653),
        ("EM Rural Carlos Carone", "Rural", 5003207, -19.220, -57.410),
        ("EE JOMAP", "Urbana", 5008305, -20.785, -51.705),
        ("EM Rural Arapuá", "Rural", 5008305, -20.640, -51.920),
        ("EE Adê Marques", "Urbana", 5006606, -22.535, -55.725),
        ("EM Rural Nova Conquista", "Rural", 5006606, -22.680, -55.910),
        ("EE Marechal Deodoro", "Urbana", 5001102, -20.472, -55.789),
        ("EM Rural Pantaneira", "Rural", 5001102, -20.210, -56.120),
        ("EE Marechal Rondon", "Urbana", 5003157, -19.829, -54.829),
        ("EM Rural de Corguinho", "Rural", 5003157, -19.710, -54.910),
        ("EE Salustiano Azevedo", "Urbana", 5004304, -21.428, -56.115),
        ("EM Rural Santa Maria", "Rural", 5004304, -21.550, -55.980),
        ("EE Olívia de Paula", "Urbana", 5007307, -19.447, -54.991),
        ("EM Rural Rio Negro", "Rural", 5007307, -19.320, -55.120),
    ]

    escolas_ms = []
    for i, (nome, localizacao, cod_mun, lat, lon) in enumerate(escolas_nomes):
        cod_escola = 50000000 + i
        vagas = rng.randint(80, 600)
        tem_internet = 1 if rng.random() > 0.1 else 0
        tem_banda_larga = 1 if tem_internet == 1 and rng.random() > 0.3 else 0
        tem_internet_alunos = tem_internet  # simplificação: mesma info nesta amostra sintética
        # O prefixo do nome fictício já carrega a dependência administrativa
        # (convenção real do Censo Escolar): "EE" = Escola Estadual, "EM" =
        # Escola Municipal — evita inventar mais um valor aleatório solto.
        dependencia_administrativa = "Estadual" if nome.startswith("EE ") else "Municipal"

        if tem_internet:
            rede_local = rng.choices(["A cabo e Wireless", "A cabo", "Wireless"], weights=[0.6, 0.25, 0.15])[0]
        else:
            rede_local = "Nenhuma"

        escolas_ms.append(
            (
                cod_escola, nome, cod_mun, localizacao, dependencia_administrativa,
                tem_internet, tem_banda_larga, tem_internet_alunos, rede_local,
                vagas, lat, lon, 0,
            )
        )

    cursor.executemany(INSERT_ESCOLAS_SQL, escolas_ms)
    return escolas_ms


def _popular_escolas(
    cursor: sqlite3.Cursor, municipios_validos: set[int], nicbr_por_escola: dict[int, dict]
) -> tuple[list[tuple], str]:
    if CSV_ESCOLAS_CENSO.exists():
        try:
            registros = _popular_escolas_oficiais(cursor, municipios_validos, nicbr_por_escola)
            com_geo_real = sum(1 for r in registros if r[INDICE_GEO_APROXIMADA] == 0)
            return registros, (
                "oficial (INEP, Censo Escolar 2025 — geolocalização real do NIC.br para "
                f"{com_geo_real}/{len(registros)} escolas, sede do município para o restante)"
            )
        except Exception as erro:
            print(f"  aviso: falha ao carregar {CSV_ESCOLAS_CENSO.name} ({erro}); usando amostra sintética.")
            cursor.execute("DELETE FROM escolas;")

    registros = _popular_escolas_sinteticas(cursor)
    return registros, "sintético (18 escolas de demonstração)"


# --------------------------------------------------------------------------- #
# Medições SIMET (sempre sintéticas — ver docstring do módulo)
# --------------------------------------------------------------------------- #


def _carregar_baseline_ookla() -> dict[int, dict[str, float]]:
    """Lê `data/raw/conectividade_municipio_ookla.csv` (gerado por processar_ookla.py).

    Retorna um dict `co_municipio -> {"download", "upload", "latencia"}` só
    com os municípios em que o Ookla realmente tinha tile(s) com dado —
    municípios sem cobertura simplesmente não entram no dict, e quem
    chama trata isso como "sem baseline real disponível".
    """
    if not CSV_CONECTIVIDADE_OOKLA.exists():
        return {}

    df = pd.read_csv(CSV_CONECTIVIDADE_OOKLA).dropna(subset=["avg_download_mbps"])
    return {
        int(linha.co_municipio): {
            "download": linha.avg_download_mbps,
            "upload": linha.avg_upload_mbps,
            "latencia": linha.avg_latencia_ms,
        }
        for linha in df.itertuples(index=False)
    }


def _popular_medicoes(
    cursor: sqlite3.Cursor, escolas_ms: list[tuple], data_medicao: str, nicbr_por_escola: dict[int, dict]
) -> str:
    """Grava uma medição por escola (só para as que têm internet), na melhor
    procedência disponível — nesta ordem de preferência:

        1. Medição SIMET REAL da própria escola (NIC.br, via `nicbr_por_escola`).
        2. Estimativa ANCORADA na velocidade real do Ookla Speedtest para o
           município (`logic.simular_medicao_calibrada`).
        3. Faixa genérica sintética, quando nenhuma das anteriores está
           disponível para aquela escola/município.

    Funciona sobre `escolas_ms` seja ele a amostra oficial ou a sintética —
    as duas tuplas mantêm a mesma ordem de campos nas 6 primeiras posições
    (cod_escola, nome, cod_mun, localizacao, dependencia_administrativa,
    tem_internet).

    Retorna uma descrição da(s) fonte(s) efetivamente usada(s), para
    `metadata_execucao`.
    """
    baseline_por_municipio = _carregar_baseline_ookla()
    rng = random.Random(SEED + 1)
    medicoes = []
    contagem_fonte = {"nicbr_simet_real": 0, "ookla": 0, "sintetico_generico": 0}

    for cod_escola, _nome, cod_mun, localizacao, _dependencia, tem_internet, *_resto in escolas_ms:
        if not tem_internet:
            continue  # escola sem internet não tem o que medir

        rural = localizacao != "Urbana"
        jitter_down = jitter_up = None
        dado_real = nicbr_por_escola.get(cod_escola)

        if dado_real and dado_real["tem_medicao_propria"] and dado_real["velocidade_download_mbps"] is not None:
            vel_down = float(dado_real["velocidade_download_mbps"])
            vel_up = dado_real["velocidade_upload_mbps"]
            vel_up = float(vel_up) if vel_up is not None else None
            latencia = dado_real["latencia_ms"]
            latencia = float(latencia) if latencia is not None else None
            perda = dado_real["perda_pacotes_pct"]
            perda = float(perda) if perda is not None else None
            jitter_down = dado_real["jitter_download_ms"]
            jitter_down = float(jitter_down) if jitter_down is not None else None
            jitter_up = dado_real["jitter_upload_ms"]
            jitter_up = float(jitter_up) if jitter_up is not None else None
            fonte = "nicbr_simet_real"
        else:
            baseline = baseline_por_municipio.get(cod_mun)
            if baseline is not None:
                vel_down, vel_up, latencia, perda = simular_medicao_calibrada(
                    baseline["download"], baseline["upload"], baseline["latencia"], rural, rng
                )
                fonte = "ookla"
            else:
                # Sem baseline real para o município: faixa genérica fixa
                # (urbana mais rápida/estável, rural mais lenta e instável —
                # rádio ou satélite geoestacionário tradicional).
                if not rural:
                    vel_down = round(rng.uniform(20.0, 100.0), 2)
                    vel_up = round(vel_down * rng.uniform(0.3, 0.8), 2)
                    latencia = round(rng.uniform(15.0, 50.0), 1)
                    perda = round(rng.uniform(0.0, 1.5), 2)
                else:
                    vel_down = round(rng.uniform(2.0, 15.0), 2)
                    vel_up = round(vel_down * rng.uniform(0.2, 0.5), 2)
                    latencia = round(rng.uniform(60.0, 600.0), 1)
                    perda = round(rng.uniform(1.0, 5.0), 2)
                fonte = "sintetico_generico"

        contagem_fonte[fonte] += 1
        medicoes.append((cod_escola, vel_down, vel_up, latencia, perda, jitter_down, jitter_up, data_medicao, fonte))

    cursor.executemany(
        """
        INSERT INTO medicoes_simet
            (co_entidade, velocidade_download_real, velocidade_upload_real,
             latencia, perda_pacotes, jitter_download, jitter_upload, data_medicao, fonte_medicao)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
        """,
        medicoes,
    )

    usando_real = contagem_fonte["nicbr_simet_real"]
    usando_ookla = contagem_fonte["ookla"]
    usando_generico = contagem_fonte["sintetico_generico"]

    partes = []
    if usando_real:
        partes.append(f"medição real (NIC.br/SIMET) para {usando_real} escola(s)")
    if usando_ookla:
        partes.append(f"estimativa calibrada com Ookla Speedtest para {usando_ookla} escola(s)")
    if usando_generico:
        partes.append(f"faixa genérica sintética para {usando_generico} escola(s)")

    if not partes:
        return "sem escolas com internet nesta carga"
    return "; ".join(partes)


def _popular_alternativas_mercado(cursor: sqlite3.Cursor) -> None:
    """Provedores/tecnologias usados pelo recomendador da Fase 3 (levantamento ilustrativo)."""
    provedores = [
        ("Fibra Óptica", "Telecom MS S/A", 100.0, 149.90, 0),
        ("Fibra Óptica", "Provedor Regional MS", 200.0, 199.90, 0),
        ("Satélite LEO", "Starlink Brasil", 220.0, 235.00, 1),
        ("Satélite LEO", "HughesNet", 25.0, 289.00, 1),
        ("Rádio WISP", "Rádio Rural MS", 15.0, 120.00, 1),
    ]
    cursor.executemany(
        """
        INSERT INTO alternativas_mercado
            (tecnologia, no_provedor, velocidade_oferta, custo_mensal, viabilidade_rural)
        VALUES (?, ?, ?, ?, ?);
        """,
        provedores,
    )


def _registrar_metadata(
    cursor: sqlite3.Cursor, fonte_municipios: str, fonte_escolas: str, fonte_medicoes: str
) -> None:
    """Grava a procedência de cada camada, para `app.py` exibir na interface."""
    agora_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    registros = [
        ("fonte_municipios", fonte_municipios),
        ("fonte_escolas", fonte_escolas),
        ("fonte_medicoes_simet", fonte_medicoes),
        ("fonte_alternativas_mercado", "levantamento de mercado ilustrativo"),
        ("data_carga_utc", agora_utc),
    ]
    cursor.executemany(
        "INSERT OR REPLACE INTO metadata_execucao (chave, valor) VALUES (?, ?);", registros
    )


def _exportar_para_csv(conexao: sqlite3.Connection) -> None:
    """Exporta o conteúdo recém-carregado para `data/*.csv` como trilha de auditoria."""
    DATA_DIR.mkdir(exist_ok=True)
    for tabela in ("municipios", "escolas", "medicoes_simet", "alternativas_mercado", "metadata_execucao"):
        cursor = conexao.execute(f"SELECT * FROM {tabela};")
        colunas = [descricao[0] for descricao in cursor.description]
        linhas = cursor.fetchall()

        with open(DATA_DIR / f"{tabela}.csv", "w", newline="", encoding="utf-8") as arquivo:
            escritor = csv.writer(arquivo)
            escritor.writerow(colunas)
            escritor.writerows(linhas)


def carregar_dados_iniciais(data_medicao: str = "2026-09-03") -> None:
    """Popula o banco, preferindo dados oficiais e recuando para a amostra sintética."""
    conexao = get_connection()
    try:
        cursor = conexao.cursor()
        _limpar_tabelas(cursor)

        nicbr_por_escola = _carregar_nicbr_simet()  # carregado uma vez, usado por escolas e medições

        municipios_ms, fonte_municipios = _popular_municipios(cursor)
        municipios_validos = {linha[0] for linha in municipios_ms}
        escolas_ms, fonte_escolas = _popular_escolas(cursor, municipios_validos, nicbr_por_escola)
        fonte_medicoes = _popular_medicoes(cursor, escolas_ms, data_medicao, nicbr_por_escola)
        _popular_alternativas_mercado(cursor)
        _registrar_metadata(cursor, fonte_municipios, fonte_escolas, fonte_medicoes)

        conexao.commit()
        _exportar_para_csv(conexao)

        print(
            "Massa de dados carregada com sucesso! "
            f"({len(municipios_ms)} municípios, {len(escolas_ms)} escolas)\n"
            f"  fonte municípios: {fonte_municipios}\n"
            f"  fonte escolas:    {fonte_escolas}\n"
            f"  fonte medições:   {fonte_medicoes}"
        )
    except sqlite3.Error as erro:
        conexao.rollback()
        print(f"Erro ao carregar os dados: {erro}")
        raise
    finally:
        conexao.close()


if __name__ == "__main__":
    carregar_dados_iniciais()

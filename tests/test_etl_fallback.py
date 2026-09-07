"""Testes de integração do fallback sintético do ETL.

No dia a dia, `data/raw/` sempre existe (foi buscado uma vez), então o
caminho sintético de `etl.py` só roda de novo se alguém apagar esses
arquivos ou apresentar o projeto num ambiente sem eles — exatamente a
situação em que uma regressão silenciosa seria mais dolorosa de descobrir
(no meio de uma demonstração). Este teste força esse caminho isolando
`etl.py`/`database.py` num banco temporário, sem tocar em `govtech_ms.db`
nem em `data/*.csv` do projeto.
"""

import sqlite3
from pathlib import Path

import database
import etl


def test_fallback_sintetico_quando_raw_nao_existe(tmp_path, monkeypatch):
    monkeypatch.setattr(database, "DB_PATH", tmp_path / "teste.db")
    monkeypatch.setattr(etl, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(etl, "CSV_MUNICIPIOS_OFICIAIS", tmp_path / "nao-existe-municipios.csv")
    monkeypatch.setattr(etl, "CSV_ESCOLAS_CENSO", tmp_path / "nao-existe-escolas.csv")
    # Sem isto, o teste pegaria o data/raw/conectividade_municipio_ookla.csv
    # de verdade do projeto (quando presente) e deixaria de exercitar o
    # fallback — o resultado dependeria do que já foi baixado na máquina.
    monkeypatch.setattr(etl, "CSV_CONECTIVIDADE_OOKLA", tmp_path / "nao-existe-ookla.csv")
    monkeypatch.setattr(etl, "CSV_MEDICOES_REAIS_NICBR", tmp_path / "nao-existe-nicbr.csv")

    database.criar_banco_dados()
    etl.carregar_dados_iniciais()

    conexao = sqlite3.connect(database.DB_PATH)
    try:
        (total_municipios,) = conexao.execute("SELECT COUNT(*) FROM municipios;").fetchone()
        (total_escolas,) = conexao.execute("SELECT COUNT(*) FROM escolas;").fetchone()
        metadados = dict(conexao.execute("SELECT chave, valor FROM metadata_execucao;").fetchall())
    finally:
        conexao.close()

    assert total_municipios == 13  # tamanho da amostra sintética em _popular_municipios_sinteticos
    assert total_escolas == 18     # tamanho da amostra sintética em _popular_escolas_sinteticas
    assert metadados["fonte_municipios"].startswith("sintético")
    assert metadados["fonte_escolas"].startswith("sintético")
    assert metadados["fonte_medicoes_simet"].startswith("faixa genérica sintética")


def test_modo_oficial_quando_raw_existe(tmp_path, monkeypatch):
    """Confirma o caminho oposto: com os CSVs de `data/raw/` presentes, o
    ETL carrega dado oficial e registra isso em `metadata_execucao`."""
    municipios_csv = tmp_path / "municipios_oficiais.csv"
    municipios_csv.write_text(
        "co_municipio,no_municipio,populacao_estimada,investimento_per_capita_educacao,"
        "nota_transparencia_ebt,conselho_educacao_ativo\n"
        "5002704,Campo Grande,970843,1726.35,,\n",
        encoding="utf-8",
    )

    escolas_csv = tmp_path / "escolas_censo_ms.csv"
    escolas_csv.write_text(
        "co_entidade,no_entidade,co_municipio,tp_localizacao,in_internet,in_banda_larga,"
        "in_internet_alunos,rede_local,qt_matriculas,latitude,longitude,geo_aproximada\n"
        "50011774,EE MAL CASTELO BRANCO,5002704,Urbana,1,1,1,A cabo e Wireless,881,-20.43,-52.90,1\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "teste_oficial.db")
    monkeypatch.setattr(etl, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(etl, "CSV_MUNICIPIOS_OFICIAIS", municipios_csv)
    monkeypatch.setattr(etl, "CSV_ESCOLAS_CENSO", escolas_csv)
    monkeypatch.setattr(etl, "CSV_CONECTIVIDADE_OOKLA", tmp_path / "nao-existe-ookla.csv")
    monkeypatch.setattr(etl, "CSV_MEDICOES_REAIS_NICBR", tmp_path / "nao-existe-nicbr.csv")

    database.criar_banco_dados()
    etl.carregar_dados_iniciais()

    conexao = sqlite3.connect(database.DB_PATH)
    try:
        (total_escolas,) = conexao.execute("SELECT COUNT(*) FROM escolas;").fetchone()
        metadados = dict(conexao.execute("SELECT chave, valor FROM metadata_execucao;").fetchall())
    finally:
        conexao.close()

    assert total_escolas == 1
    assert metadados["fonte_municipios"].startswith("oficial")
    assert metadados["fonte_escolas"].startswith("oficial")
    assert metadados["fonte_medicoes_simet"].startswith("faixa genérica sintética")  # sem baseline Ookla neste teste


def test_medicoes_usam_baseline_ookla_quando_disponivel(tmp_path, monkeypatch):
    """Com um `conectividade_municipio_ookla.csv` de teste, a medição da
    escola deve ficar marcada como calibrada com Ookla, não sintética."""
    municipios_csv = tmp_path / "municipios_oficiais.csv"
    municipios_csv.write_text(
        "co_municipio,no_municipio,populacao_estimada,investimento_per_capita_educacao,"
        "nota_transparencia_ebt,conselho_educacao_ativo\n"
        "5002704,Campo Grande,970843,1726.35,,\n",
        encoding="utf-8",
    )

    escolas_csv = tmp_path / "escolas_censo_ms.csv"
    escolas_csv.write_text(
        "co_entidade,no_entidade,co_municipio,tp_localizacao,in_internet,in_banda_larga,"
        "in_internet_alunos,rede_local,qt_matriculas,latitude,longitude,geo_aproximada\n"
        "50011774,EE MAL CASTELO BRANCO,5002704,Urbana,1,1,1,A cabo e Wireless,881,-20.43,-52.90,1\n",
        encoding="utf-8",
    )

    ookla_csv = tmp_path / "conectividade_municipio_ookla.csv"
    ookla_csv.write_text(
        "co_municipio,no_municipio,avg_download_mbps,avg_upload_mbps,avg_latencia_ms,"
        "num_tiles_ookla,num_testes_ookla\n"
        "5002704,Campo Grande,250.0,180.0,12.0,10,500\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "teste_ookla.db")
    monkeypatch.setattr(etl, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(etl, "CSV_MUNICIPIOS_OFICIAIS", municipios_csv)
    monkeypatch.setattr(etl, "CSV_ESCOLAS_CENSO", escolas_csv)
    monkeypatch.setattr(etl, "CSV_CONECTIVIDADE_OOKLA", ookla_csv)
    monkeypatch.setattr(etl, "CSV_MEDICOES_REAIS_NICBR", tmp_path / "nao-existe-nicbr.csv")

    database.criar_banco_dados()
    etl.carregar_dados_iniciais()

    conexao = sqlite3.connect(database.DB_PATH)
    try:
        fonte_medicao, velocidade = conexao.execute(
            "SELECT fonte_medicao, velocidade_download_real FROM medicoes_simet;"
        ).fetchone()
        metadados = dict(conexao.execute("SELECT chave, valor FROM metadata_execucao;").fetchall())
    finally:
        conexao.close()

    assert fonte_medicao == "ookla"
    assert 0 < velocidade < 250.0 * 1.30  # dentro da faixa que simular_medicao_calibrada pode gerar
    assert metadados["fonte_medicoes_simet"].startswith("estimativa calibrada com Ookla")


def test_medicoes_usam_dado_real_nicbr_quando_disponivel(tmp_path, monkeypatch):
    """Com um `medicoes_reais_nicbr.csv` de teste, a medição da escola deve
    usar o valor real (não a estimativa Ookla nem a faixa sintética) e a
    geolocalização real deve substituir a aproximação pela sede do município."""
    municipios_csv = tmp_path / "municipios_oficiais.csv"
    municipios_csv.write_text(
        "co_municipio,no_municipio,populacao_estimada,investimento_per_capita_educacao,"
        "nota_transparencia_ebt,conselho_educacao_ativo\n"
        "5002704,Campo Grande,970843,1726.35,,\n",
        encoding="utf-8",
    )

    escolas_csv = tmp_path / "escolas_censo_ms.csv"
    escolas_csv.write_text(
        "co_entidade,no_entidade,co_municipio,tp_localizacao,in_internet,in_banda_larga,"
        "in_internet_alunos,rede_local,qt_matriculas,latitude,longitude,geo_aproximada\n"
        "50011774,EE MAL CASTELO BRANCO,5002704,Urbana,1,1,1,A cabo e Wireless,881,-20.43,-52.90,1\n",
        encoding="utf-8",
    )

    nicbr_csv = tmp_path / "medicoes_reais_nicbr.csv"
    nicbr_csv.write_text(
        "co_entidade,latitude,longitude,tem_medicao_propria,velocidade_download_mbps,"
        "velocidade_upload_mbps,latencia_ms,perda_pacotes_pct,jitter_download_ms,"
        "jitter_upload_ms,tecnologia_conexao\n"
        "50011774,-20.431257,-52.839296,True,120.5,80.3,18.2,0.4,3.1,2.8,Fibra\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(database, "DB_PATH", tmp_path / "teste_nicbr.db")
    monkeypatch.setattr(etl, "DATA_DIR", tmp_path / "data")
    monkeypatch.setattr(etl, "CSV_MUNICIPIOS_OFICIAIS", municipios_csv)
    monkeypatch.setattr(etl, "CSV_ESCOLAS_CENSO", escolas_csv)
    monkeypatch.setattr(etl, "CSV_CONECTIVIDADE_OOKLA", tmp_path / "nao-existe-ookla.csv")
    monkeypatch.setattr(etl, "CSV_MEDICOES_REAIS_NICBR", nicbr_csv)

    database.criar_banco_dados()
    etl.carregar_dados_iniciais()

    conexao = sqlite3.connect(database.DB_PATH)
    try:
        fonte_medicao, velocidade, jitter_down = conexao.execute(
            "SELECT fonte_medicao, velocidade_download_real, jitter_download FROM medicoes_simet;"
        ).fetchone()
        latitude, geo_aproximada = conexao.execute(
            "SELECT latitude, geo_aproximada FROM escolas;"
        ).fetchone()
        metadados = dict(conexao.execute("SELECT chave, valor FROM metadata_execucao;").fetchall())
    finally:
        conexao.close()

    assert fonte_medicao == "nicbr_simet_real"
    assert velocidade == 120.5
    assert jitter_down == 3.1
    assert latitude == -20.431257  # geolocalização real do NIC.br, não a do CSV do Censo Escolar (-20.43)
    assert geo_aproximada == 0
    assert metadados["fonte_medicoes_simet"].startswith("medição real (NIC.br/SIMET)")

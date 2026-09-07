"""
database.py
------------
Cria e inicializa o esquema (DDL) do banco de dados SQLite do GovTech MS.

Este módulo cuida exclusivamente da ESTRUTURA das tabelas. A carga de
dados (DML) é responsabilidade de `etl.py` — separar as duas coisas evita
que rodar o pipeline de dados de novo precise recriar (ou arrisque
corromper) o esquema, e vice-versa.

Uso:
    python database.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Caminho do banco sempre relativo à localização deste arquivo, para que
# `python database.py`, `streamlit run app.py` etc. funcionem
# independentemente do diretório de onde o comando é chamado.
DB_PATH = Path(__file__).resolve().parent / "govtech_ms.db"


def get_connection() -> sqlite3.Connection:
    """Abre uma conexão com o banco já com integridade referencial ativa.

    O SQLite não aplica FOREIGN KEY por padrão — é preciso habilitar a
    PRAGMA em cada conexão.
    """
    conexao = sqlite3.connect(DB_PATH)
    conexao.execute("PRAGMA foreign_keys = ON;")
    return conexao


def criar_banco_dados() -> None:
    """Cria (se ainda não existirem) as tabelas do modelo de dados do GovTech MS."""
    conexao = get_connection()
    try:
        cursor = conexao.cursor()

        # 1. Municípios — dados de governança (Ranking Connected Smart Cities)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS municipios (
            co_municipio INTEGER PRIMARY KEY,
            no_municipio TEXT NOT NULL,
            nota_transparencia_ebt REAL,               -- Escala Brasil Transparente (CGU)
            investimento_per_capita_educacao REAL,     -- Siconfi (Tesouro Nacional)
            conselho_educacao_ativo INTEGER DEFAULT 1, -- MUNIC (IBGE)
            populacao_estimada INTEGER
        );
        """)

        # 2. Escolas — Microdados do Censo Escolar (INEP)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS escolas (
            co_entidade INTEGER PRIMARY KEY,
            no_entidade TEXT NOT NULL,
            co_municipio INTEGER NOT NULL,
            tp_localizacao TEXT CHECK (tp_localizacao IN ('Urbana', 'Rural')),
            in_internet INTEGER DEFAULT 0,
            in_banda_larga INTEGER DEFAULT 0,
            in_internet_alunos INTEGER, -- internet disponível especificamente para uso dos alunos (não só administrativo)
            rede_local TEXT,             -- 'Nenhuma' / 'A cabo' / 'Wireless' / 'A cabo e Wireless' / 'Não informado'
            qt_matriculas INTEGER DEFAULT 0,
            latitude REAL,
            longitude REAL,
            -- 1 quando lat/lon é uma aproximação (sede do município), não a
            -- posição real da escola. 0 quando é geolocalização real (do
            -- Censo Escolar/esforços de geolocalização do NIC.br). Ver
            -- processar_censo_escolar.py e processar_nicbr_simet.py.
            geo_aproximada INTEGER DEFAULT 0,
            FOREIGN KEY (co_municipio) REFERENCES municipios (co_municipio)
        );
        """)

        # 3. Medições de qualidade de conexão por escola. Três níveis de
        #    procedência, do melhor para o pior (ver `fonte_medicao`):
        #      'nicbr_simet_real'   — medição SIMET de verdade, exportada
        #                             manualmente de conectividadenaeducacao.nic.br
        #                             (não há API — ver README.md)
        #      'ookla'              — sem medição própria; estimativa
        #                             calibrada com a média real do Ookla
        #                             Speedtest para o município
        #      'sintetico_generico' — sem nenhum dado real disponível;
        #                             faixa genérica sintética
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS medicoes_simet (
            co_medicao INTEGER PRIMARY KEY AUTOINCREMENT,
            co_entidade INTEGER NOT NULL,
            velocidade_download_real REAL, -- Mbps
            velocidade_upload_real REAL,   -- Mbps
            latencia REAL,                  -- ms
            perda_pacotes REAL,             -- %
            jitter_download REAL,           -- ms (só preenchido quando fonte_medicao = 'nicbr_simet_real')
            jitter_upload REAL,             -- ms (idem)
            data_medicao TEXT,
            fonte_medicao TEXT CHECK (fonte_medicao IN ('nicbr_simet_real', 'ookla', 'sintetico_generico')) DEFAULT 'sintetico_generico',
            FOREIGN KEY (co_entidade) REFERENCES escolas (co_entidade)
        );
        """)

        # 4. Alternativas de mercado — provedores e tecnologias (Fase 3)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS alternativas_mercado (
            co_provedor INTEGER PRIMARY KEY AUTOINCREMENT,
            tecnologia TEXT CHECK (tecnologia IN ('Fibra Óptica', 'Satélite LEO', 'Rádio WISP')),
            no_provedor TEXT NOT NULL,
            velocidade_oferta REAL, -- Mbps
            custo_mensal REAL,      -- R$
            viabilidade_rural INTEGER DEFAULT 0
        );
        """)

        # 5. Metadados da carga — de onde veio cada tabela (oficial ou
        # sintética) e quando rodou, para o painel exibir a procedência dos
        # dados em vez de deixar isso implícito.
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS metadata_execucao (
            chave TEXT PRIMARY KEY,
            valor TEXT
        );
        """)

        # Índices para os agrupamentos por município/escola usados no painel.
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_escolas_municipio ON escolas (co_municipio);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_medicoes_entidade ON medicoes_simet (co_entidade);")

        conexao.commit()
        print(f"Banco de dados '{DB_PATH.name}' criado e estruturado com sucesso!")
    except sqlite3.Error as erro:
        conexao.rollback()
        print(f"Erro ao criar o banco de dados: {erro}")
        raise
    finally:
        conexao.close()


if __name__ == "__main__":
    criar_banco_dados()

"""
app.py
-------
ConectaEscolas MS — Painel Integrado de Conectividade Escolar.

Interface Streamlit organizada nas 3 fases da metodologia do projeto:
    Fase 1 — Mapeamento de infraestrutura (mapa + KPIs)
    Fase 2 — Comparativo técnico de banda por aluno
    Fase 3 — Engenharia de soluções de mercado (IPI, recomendador e SWOT)

Uso (após `python database.py` e `python etl.py`):
    streamlit run app.py
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import folium
import pandas as pd
import plotly.express as px
import streamlit as st
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from database import DB_PATH
from logic import (
    CLASSIFICACAO_CORES,
    calcular_banda_por_aluno,
    calcular_ipi,
    classificar_banda,
    recomendar_tecnologia,
)

PROFESSOR = "Prof. Dr. Marcelo Augusto Santos Turine"

AUTORES = [
    "Paulo Henrique da Silva Leite",
    "Gabriel Angeramis Vargas Goulart",
]

TODOS_OS_MUNICIPIOS = "Todos os Municípios"


# --------------------------------------------------------------------------- #
# Acesso a dados (cacheado para não reabrir/reconsultar o SQLite a cada clique)
# --------------------------------------------------------------------------- #


@st.cache_resource
def obter_conexao() -> sqlite3.Connection | None:
    """Abre (uma única vez por sessão) a conexão com o SQLite, se ele existir."""
    if not DB_PATH.exists():
        return None
    return sqlite3.connect(DB_PATH, check_same_thread=False)


@st.cache_data
def carregar_tabelas(
    _conexao: sqlite3.Connection,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame, dict[str, str]]:
    """Lê as tabelas do banco como DataFrames, mais os metadados de procedência.

    O prefixo `_` em `_conexao` instrui o `st.cache_data` a não tentar
    fazer hash do objeto de conexão (não é serializável de forma estável).
    """
    municipios = pd.read_sql_query("SELECT * FROM municipios ORDER BY no_municipio;", _conexao)
    escolas = pd.read_sql_query("SELECT * FROM escolas;", _conexao)
    medicoes = pd.read_sql_query("SELECT * FROM medicoes_simet;", _conexao)
    alternativas = pd.read_sql_query("SELECT * FROM alternativas_mercado;", _conexao)
    try:
        metadados = dict(
            pd.read_sql_query("SELECT chave, valor FROM metadata_execucao;", _conexao).values
        )
    except pd.errors.DatabaseError:
        metadados = {}  # banco criado antes da tabela metadata_execucao existir
    return municipios, escolas, medicoes, alternativas, metadados


def _formatar_numero_br(valor: float) -> str:
    """Formata um número no padrão brasileiro (milhar com ponto, decimal com vírgula)."""
    return f"{valor:,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")


def _sem_nan(valor):
    """Converte NaN (float do pandas para célula ausente) em `None`.

    `logic.py` é deliberadamente independente de pandas e trata ausência
    de dado como `None` — mas `None` vindo de um LEFT JOIN do pandas chega
    como `NaN`, que passa despercebido por checagens `is None` (e é
    "truthy" em testes booleanos ingênuos como `valor or 0`). Sem esta
    conversão na fronteira entre pandas e as regras de negócio, o
    recomendador da Fase 3 deixaria de sugerir tecnologia justamente para
    as escolas sem nenhuma medição — as mais vulneráveis.
    """
    return None if pd.isna(valor) else valor


def montar_base_escolas(
    municipios: pd.DataFrame, escolas: pd.DataFrame, medicoes: pd.DataFrame
) -> pd.DataFrame:
    """Junta escolas + município + medição mais recente em uma única tabela larga."""
    base = escolas.merge(
        municipios[["co_municipio", "no_municipio"]], on="co_municipio", how="left"
    )

    if not medicoes.empty:
        medicao_recente = medicoes.sort_values("data_medicao").drop_duplicates(
            subset="co_entidade", keep="last"
        )
        base = base.merge(
            medicao_recente[
                ["co_entidade", "velocidade_download_real", "velocidade_upload_real", "latencia", "perda_pacotes"]
            ],
            on="co_entidade",
            how="left",
        )
    else:
        for coluna in ("velocidade_download_real", "velocidade_upload_real", "latencia", "perda_pacotes"):
            base[coluna] = pd.NA

    base["qt_matriculas"] = base["qt_matriculas"].fillna(0).astype(int)
    return base


# --------------------------------------------------------------------------- #
# Fase 1 — Mapeamento
# --------------------------------------------------------------------------- #


def construir_mapa(df: pd.DataFrame) -> tuple[folium.Map, int]:
    """Monta o mapa de MS com marcadores por escola, agrupados em cluster.

    Azul = urbana, laranja = rural; ícone de "remover" quando a escola não
    tem internet. Escolas com coordenadas ausentes são contadas à parte em
    vez de derrubar a renderização do mapa. Com dado oficial (INEP), o
    volume passa de dezenas para milhares de escolas — os marcadores são
    agrupados em cluster tanto por desempenho do navegador quanto porque,
    nesse modo, a posição de cada escola já é só uma aproximação pela sede
    do município (ver `geo_aproximada`): "várias escolas empilhadas"
    reflete melhor a natureza do dado do que pinos espalhados
    artificialmente por um local exato que não temos.
    """
    # OpenStreetMap é usado por não exigir chave de API (o CartoDB passou a
    # exigir uma para os tiles "positron"/"dark_matter").
    mapa = folium.Map(location=[-20.5, -54.6], zoom_start=6, tiles="OpenStreetMap")
    cluster = MarkerCluster(name="Escolas").add_to(mapa)
    sem_coordenadas = 0

    for escola in df.itertuples(index=False):
        lat, lon = escola.latitude, escola.longitude
        if pd.isna(lat) or pd.isna(lon):
            sem_coordenadas += 1
            continue

        cor = "blue" if escola.tp_localizacao == "Urbana" else "orange"
        icone = "remove" if escola.in_internet == 0 else "ok-sign"
        nota_geo = (
            "<br><i>📍 localização aproximada (sede do município)</i>"
            if getattr(escola, "geo_aproximada", 0)
            else "<br><i>📍 geolocalização real (NIC.br)</i>"
        )
        rede_local = getattr(escola, "rede_local", None) or "Não informado"

        folium.Marker(
            location=[lat, lon],
            tooltip=f"{escola.no_entidade} ({escola.no_municipio})",
            popup=folium.Popup(
                (
                    f"<b>{escola.no_entidade}</b><br>"
                    f"Município: {escola.no_municipio}<br>"
                    f"Localização: {escola.tp_localizacao}<br>"
                    f"Matrículas: {int(escola.qt_matriculas)}<br>"
                    f"Internet: {'Sim' if escola.in_internet else 'Não'}<br>"
                    f"Rede local: {rede_local}"
                    f"{nota_geo}"
                ),
                max_width=250,
            ),
            icon=folium.Icon(color=cor, icon=icone, prefix="glyphicon"),
        ).add_to(cluster)

    return mapa, sem_coordenadas


def grafico_discrepancia_rural_urbana(df: pd.DataFrame):
    """Taxa de conectividade (rural x urbana) agrupada por município."""
    resumo = (
        df.groupby(["no_municipio", "tp_localizacao"])["in_internet"]
        .mean()
        .mul(100)
        .round(1)
        .reset_index(name="pct_conectividade")
    )
    return px.bar(
        resumo,
        x="no_municipio",
        y="pct_conectividade",
        color="tp_localizacao",
        barmode="group",
        labels={
            "no_municipio": "Município",
            "pct_conectividade": "Conectividade (%)",
            "tp_localizacao": "Localização",
        },
        color_discrete_map={"Urbana": "#1B5E20", "Rural": "#F9A825"},
        title="Conectividade: Rural vs. Urbana por Município",
    )


def renderizar_contexto_governanca(municipios: pd.DataFrame, municipio_selecionado: str) -> None:
    """Mostra os indicadores de governança municipal (Siconfi/IBGE) reunidos na Fase 1.

    `nota_transparencia_ebt` e `conselho_educacao_ativo` podem vir `None`
    do banco (ver etl.py/fetch_dados_oficiais.py) — exibidos como "N/D" em
    vez de um zero/False enganoso, para não confundir "sem dado" com
    "reprovado"/"inativo".
    """
    st.subheader("Contexto de governança municipal")
    st.caption(
        "Investimento per capita: despesa liquidada com Educação (Siconfi/RREO, 2024) "
        "dividida pela população do próprio relatório. Nota de transparência (CGU) e "
        "conselho municipal de educação (IBGE/MUNIC) ainda não integrados nesta versão — ver README."
    )

    if municipio_selecionado == TODOS_OS_MUNICIPIOS:
        tabela = municipios[
            ["no_municipio", "populacao_estimada", "investimento_per_capita_educacao", "nota_transparencia_ebt"]
        ].rename(
            columns={
                "no_municipio": "Município",
                "populacao_estimada": "População (IBGE)",
                "investimento_per_capita_educacao": "Investimento educação (R$/hab.)",
                "nota_transparencia_ebt": "Nota transparência (CGU)",
            }
        )
        st.dataframe(
            tabela.sort_values("Investimento educação (R$/hab.)", ascending=False, na_position="last"),
            width="stretch",
            hide_index=True,
        )
        return

    linha = municipios[municipios["no_municipio"] == municipio_selecionado]
    if linha.empty:
        return
    linha = linha.iloc[0]

    col1, col2, col3 = st.columns(3)
    populacao = linha["populacao_estimada"]
    col1.metric(
        "População estimada (IBGE)",
        _formatar_numero_br(populacao).split(",")[0] if pd.notna(populacao) else "N/D",
    )

    investimento = linha["investimento_per_capita_educacao"]
    col2.metric(
        "Investimento em educação",
        f"R$ {_formatar_numero_br(investimento)}/hab." if pd.notna(investimento) else "N/D",
    )

    nota_ebt = linha["nota_transparencia_ebt"]
    col3.metric("Nota transparência (CGU)", f"{nota_ebt:.1f}" if pd.notna(nota_ebt) else "N/D")


def renderizar_fase1(df: pd.DataFrame, municipios: pd.DataFrame, municipio_selecionado: str) -> None:
    st.header("🗺️ Fase 1 — Mapeamento de Infraestrutura")

    total_escolas = len(df)
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Escolas mapeadas", total_escolas)

    if total_escolas > 0:
        col2.metric("Conectividade geral", f"{df['in_internet'].mean() * 100:.1f}%")
        col3.metric("Com banda larga", f"{df['in_banda_larga'].mean() * 100:.1f}%")
        tem_wifi = df["rede_local"].isin(["Wireless", "A cabo e Wireless"])
        col4.metric("Com wifi", f"{tem_wifi.mean() * 100:.1f}%")
    else:
        col2.metric("Conectividade geral", "—")
        col3.metric("Com banda larga", "—")
        col4.metric("Com wifi", "—")
        st.info("Nenhuma escola encontrada para o filtro selecionado.")
        return

    st.subheader("Mapa de escolas")
    st.caption("🔵 Urbana · 🟠 Rural · ícone de bloqueio = sem internet · marcadores agrupados em cluster")
    mapa, sem_coordenadas = construir_mapa(df)
    st_folium(mapa, use_container_width=True, height=480, returned_objects=[])
    if sem_coordenadas:
        st.caption(f"⚠️ {sem_coordenadas} escola(s) sem coordenadas cadastradas não aparecem no mapa.")

    st.subheader("Discrepância Rural vs. Urbana")
    st.plotly_chart(grafico_discrepancia_rural_urbana(df), width="stretch")

    renderizar_contexto_governanca(municipios, municipio_selecionado)


# --------------------------------------------------------------------------- #
# Fase 2 — Banda por aluno
# --------------------------------------------------------------------------- #


def renderizar_fase2(df: pd.DataFrame) -> None:
    st.header("📶 Fase 2 — Comparativo Técnico de Banda por Aluno")
    st.caption(
        "Banda por aluno no turno de pico = (velocidade medida em kbps) / "
        "(matrículas totais × 40%). Meta de referência (ENEC): 1000 kbps/aluno. "
        "Velocidade estimada por escola, calibrada com a média real do Ookla "
        "Speedtest para o município (ver barra lateral e README.md)."
    )

    if df.empty:
        st.info("Nenhuma escola encontrada para o filtro selecionado.")
        return

    df = df.copy()
    df["banda_kbps_aluno"] = df.apply(
        lambda linha: calcular_banda_por_aluno(_sem_nan(linha["velocidade_download_real"]), linha["qt_matriculas"]),
        axis=1,
    )
    df["classificacao"] = df["banda_kbps_aluno"].apply(classificar_banda)

    velocidade_media = df["velocidade_download_real"].mean()
    pct_adequada = (df["classificacao"] == "Adequada").mean() * 100

    col1, col2, col3 = st.columns(3)
    col1.metric("Escolas nesta seleção", len(df))
    col2.metric(
        "Velocidade média medida",
        f"{velocidade_media:.1f} Mbps" if pd.notna(velocidade_media) else "N/D",
    )
    col3.metric("Com banda adequada (≥1000 kbps/aluno)", f"{pct_adequada:.1f}%")

    col_esquerda, col_direita = st.columns([1, 2])

    with col_esquerda:
        distribuicao = df["classificacao"].value_counts().reset_index()
        distribuicao.columns = ["classificacao", "quantidade"]
        fig_pizza = px.pie(
            distribuicao,
            names="classificacao",
            values="quantidade",
            color="classificacao",
            color_discrete_map=CLASSIFICACAO_CORES,
            title="Distribuição da Qualidade de Conexão",
            hole=0.4,
        )
        st.plotly_chart(fig_pizza, width="stretch")

    with col_direita:
        st.subheader("Escolas filtradas")
        tabela = df[
            [
                "no_entidade",
                "no_municipio",
                "tp_localizacao",
                "qt_matriculas",
                "velocidade_download_real",
                "banda_kbps_aluno",
                "classificacao",
            ]
        ].rename(
            columns={
                "no_entidade": "Escola",
                "no_municipio": "Município",
                "tp_localizacao": "Localização",
                "qt_matriculas": "Matrículas",
                "velocidade_download_real": "Vel. download (Mbps)",
                "banda_kbps_aluno": "Banda/aluno (kbps)",
                "classificacao": "Classificação",
            }
        )
        st.dataframe(
            tabela.sort_values("Banda/aluno (kbps)", na_position="last"),
            width="stretch",
            hide_index=True,
        )

    st.subheader("Discrepância: matrículas × velocidade medida")
    st.caption(
        "Cada ponto é uma escola. O objetivo é mostrar que ter internet "
        "'rápida' não basta: escolas populosas (à direita) frequentemente "
        "caem em Parcial/Insuficiente por aluno mesmo com velocidade nominal "
        "razoável — o gargalo é dividir a mesma banda entre muito mais gente."
    )
    dispersao = df.dropna(subset=["velocidade_download_real"])
    if dispersao.empty:
        st.info("Nenhuma escola com velocidade medida para plotar nesta seleção.")
    else:
        fig_dispersao = px.scatter(
            dispersao,
            x="qt_matriculas",
            y="velocidade_download_real",
            color="classificacao",
            color_discrete_map=CLASSIFICACAO_CORES,
            hover_name="no_entidade",
            hover_data={"no_municipio": True, "banda_kbps_aluno": ":.0f"},
            labels={
                "qt_matriculas": "Matrículas",
                "velocidade_download_real": "Velocidade de download medida (Mbps)",
                "classificacao": "Classificação",
            },
        )
        st.plotly_chart(fig_dispersao, width="stretch")


# --------------------------------------------------------------------------- #
# Fase 3 — IPI, recomendador e SWOT
# --------------------------------------------------------------------------- #


def calcular_ranking_ipi(df: pd.DataFrame, maior_matricula_ms: int) -> pd.DataFrame:
    df = df.copy()
    df["ipi"] = df.apply(
        lambda linha: calcular_ipi(
            possui_banda_larga=bool(linha["in_banda_larga"]),
            localizacao_rural=linha["tp_localizacao"] == "Rural",
            qt_matriculas=linha["qt_matriculas"],
            maior_matricula_ms=maior_matricula_ms,
        ),
        axis=1,
    )
    return df.sort_values("ipi", ascending=False)


def montar_tabela_recomendacoes(df: pd.DataFrame, alternativas: pd.DataFrame) -> pd.DataFrame:
    alternativas_dicts = alternativas.to_dict("records")
    linhas = []
    for _, escola in df.iterrows():
        recomendacao = recomendar_tecnologia(
            localizacao_rural=escola["tp_localizacao"] == "Rural",
            velocidade_atual_mbps=_sem_nan(escola["velocidade_download_real"]),
            alternativas=alternativas_dicts,
        )
        if recomendacao is None:
            continue
        linhas.append(
            {
                "Escola": escola["no_entidade"],
                "Município": escola["no_municipio"],
                "Vel. atual (Mbps)": _sem_nan(escola["velocidade_download_real"]) or 0.0,
                "Tecnologia sugerida": recomendacao.tecnologia,
                "Provedor": recomendacao.provedor,
                "Custo mensal (R$)": recomendacao.custo_mensal,
                "Ganho estimado (Mbps)": recomendacao.ganho_mbps,
            }
        )
    return pd.DataFrame(linhas)


def renderizar_swot() -> None:
    st.subheader("Matriz SWOT do Projeto ConectaEscolas MS")

    linha1_esq, linha1_dir = st.columns(2)
    linha2_esq, linha2_dir = st.columns(2)

    with linha1_esq:
        st.markdown("#### 💪 Forças")
        st.markdown(
            "- Cruza fontes oficiais reais (INEP, IBGE, Siconfi) com medição "
            "SIMET real por escola (NIC.br) e velocidade real por região "
            "(Ookla) onde não há medição própria — todos os 79 municípios "
            "de MS com algum dado real de conectividade\n"
            "- Substitui o indicador estático e autodeclarado do Ranking Connected "
            "Smart Cities por uma medição técnica georreferenciada\n"
            "- Metodologia e ferramenta replicáveis para outros estados"
        )

    with linha1_dir:
        st.markdown("#### 🧩 Fraquezas")
        st.markdown(
            "- Depende da qualidade e da atualização dos microdados oficiais\n"
            "- O NIC.br não tem API pública para as medições do SIMET — a "
            "cobertura real (1.377 escolas públicas, 1.105 com medição "
            "própria) veio de uma planilha exportada manualmente pela "
            "equipe, não de um pipeline automatizável; escolas privadas e "
            "sem medidor instalado recaem para a estimativa via Ookla\n"
            "- Nota de transparência (CGU) e conselho municipal de educação "
            "(MUNIC/IBGE) ainda não integrados nesta versão"
        )

    with linha2_esq:
        st.markdown("#### 🚀 Oportunidades")
        st.markdown(
            "- Priorização objetiva de recursos de editais e fundos (ex.: FUST, PROINFO)\n"
            "- Parcerias com provedores regionais e novas tecnologias (satélites LEO)\n"
            "- Extensível a outros estados e a outros indicadores de governança"
        )

    with linha2_dir:
        st.markdown("#### 🔥 Ameaças")
        st.markdown(
            "- Restrições orçamentárias municipais para contratar novas conexões\n"
            "- Gargalo físico de última milha em áreas rurais remotas\n"
            "- Descontinuidade da política pública entre gestões municipais"
        )


def renderizar_fase3(df: pd.DataFrame, df_completo: pd.DataFrame, alternativas: pd.DataFrame) -> None:
    st.header("🛠️ Fase 3 — Engenharia de Soluções de Mercado")

    aba_ipi, aba_swot = st.tabs(["📊 IPI e Recomendações", "🧭 Matriz SWOT"])

    with aba_ipi:
        if df.empty:
            st.info("Nenhuma escola encontrada para o filtro selecionado.")
        else:
            st.caption(
                "IPI = [0,50 × (1 − possui banda larga) + 0,30 × é rural "
                "+ 0,20 × (matrículas / maior matrícula de MS)] × 100. "
                "A normalização por matrículas usa sempre a maior escola do "
                "estado inteiro, mesmo com filtro de município ativo, para "
                "manter o índice comparável entre execuções."
            )
            # Normaliza pelo porte da MAIOR escola do estado (não da seleção
            # filtrada) para que o IPI não mude de escala conforme o filtro.
            maior_matricula_ms = int(df_completo["qt_matriculas"].max() or 0)
            ranking = calcular_ranking_ipi(df, maior_matricula_ms)

            top10 = ranking.head(10)
            fig_ipi = px.bar(
                top10.sort_values("ipi"),
                x="ipi",
                y="no_entidade",
                orientation="h",
                color="no_municipio",
                labels={"ipi": "IPI (0–100)", "no_entidade": "Escola", "no_municipio": "Município"},
                title="Top 10 escolas por Índice de Prioridade de Intervenção",
            )
            st.plotly_chart(fig_ipi, width="stretch")

            st.dataframe(
                ranking[["no_entidade", "no_municipio", "tp_localizacao", "qt_matriculas", "ipi"]].rename(
                    columns={
                        "no_entidade": "Escola",
                        "no_municipio": "Município",
                        "tp_localizacao": "Localização",
                        "qt_matriculas": "Matrículas",
                        "ipi": "IPI",
                    }
                ),
                width="stretch",
                hide_index=True,
            )

            st.subheader("Recomendador de tecnologia")
            st.caption(
                "Sugestão automática para escolas rurais com velocidade medida "
                "abaixo de 10 Mbps (ou sem internet), priorizando a melhor "
                "relação Mbps/R$ entre satélite LEO e rádio WISP."
            )
            recomendacoes = montar_tabela_recomendacoes(df, alternativas)
            if recomendacoes.empty:
                st.success("Nenhuma escola do filtro atual precisa de intervenção imediata.")
            else:
                st.dataframe(recomendacoes, width="stretch", hide_index=True)

    with aba_swot:
        renderizar_swot()


# --------------------------------------------------------------------------- #
# Fontes de dados e metodologia (aba de referência para a apresentação)
# --------------------------------------------------------------------------- #


def renderizar_fontes_e_metodologia(
    municipios: pd.DataFrame, escolas: pd.DataFrame, metadados: dict[str, str]
) -> None:
    """Resumo do projeto para consulta rápida na apresentação: de onde vem
    cada dado, o que ainda não é oficial (e por quê) e como cada métrica é
    calculada — sem precisar abrir o código ou o README.

    As tabelas de procedência são montadas a partir de `metadados`
    (lido de `metadata_execucao`, gravado por `etl.py`), então refletem
    exatamente a carga atual em vez de um texto fixo que pode ficar
    desatualizado.
    """
    st.header("📚 Fontes de Dados e Metodologia")
    st.markdown(
        "Resumo de onde vem cada dado usado no ConectaEscolas MS e como cada "
        "métrica é calculada — para consulta rápida na apresentação."
    )

    st.subheader("O projeto em 3 fases")
    st.markdown(
        "1. **Mapeamento** — localização das escolas de MS (urbana/rural) e "
        "indicadores de governança municipal.\n"
        "2. **Comparativo técnico** — cruza matrículas (INEP) com a "
        "velocidade real medida na região (Ookla) para calcular a banda por "
        "aluno no turno de pico.\n"
        "3. **Engenharia de soluções** — calcula o Índice de Prioridade de "
        "Intervenção (IPI) e recomenda tecnologia alternativa para escolas "
        "rurais vulneráveis."
    )

    st.subheader("Procedência desta carga de dados")
    st.caption(
        "Lido direto do banco (`metadata_execucao`) — reflete exatamente o "
        "que está carregado agora, não um texto fixo no código."
    )
    procedencia = pd.DataFrame(
        [
            {"Camada": "Municípios (código, população, investimento em educação)", "Procedência": metadados.get("fonte_municipios", "desconhecida")},
            {"Camada": "Escolas (localização, matrículas, internet, banda larga)", "Procedência": metadados.get("fonte_escolas", "desconhecida")},
            {"Camada": "Velocidade por escola", "Procedência": metadados.get("fonte_medicoes_simet", "desconhecida")},
            {"Camada": "Alternativas de mercado (Fase 3)", "Procedência": metadados.get("fonte_alternativas_mercado", "desconhecida")},
        ]
    )
    st.dataframe(procedencia, width="stretch", hide_index=True)
    st.caption(
        f"Carregado em {metadados.get('data_carga_utc', 'data desconhecida')} (UTC) · "
        f"{len(municipios)} municípios · {len(escolas)} escolas."
    )

    st.subheader("Fontes de dados, uma a uma")
    fontes = pd.DataFrame(
        [
            {
                "Fonte": "IBGE — Localidades e Agregados (SIDRA)",
                "Usado para": "Lista oficial dos 79 municípios de MS e população estimada (2026)",
                "Acesso": "API pública, sem chave (servicodados.ibge.gov.br)",
            },
            {
                "Fonte": "Siconfi — Tesouro Nacional",
                "Usado para": "Investimento em educação por município (RREO, Anexo 02, 2024)",
                "Acesso": "API pública, sem chave (apidatalake.tesouro.gov.br)",
            },
            {
                "Fonte": "Censo Escolar 2025 — INEP",
                "Usado para": "Escolas de MS em atividade: urbana/rural, internet (geral e para alunos), banda larga, rede local (wifi/cabo), matrículas",
                "Acesso": "Microdado público, filtrado localmente para MS",
            },
            {
                "Fonte": "Conectividade na Educação — NIC.br",
                "Usado para": "Velocidade, latência, jitter e perda de pacotes REAIS por escola (medição SIMET) e geolocalização real",
                "Acesso": "Sem API pública — planilha exportada manualmente pela equipe através do próprio painel interativo",
            },
            {
                "Fonte": "Speedtest by Ookla (2026-Q2)",
                "Usado para": "Velocidade/latência real por região, usada quando a escola não tem medição própria no NIC.br",
                "Acesso": "Download público, sem chave — licença CC BY-NC-SA 4.0",
            },
            {
                "Fonte": "kelvins/municipios-brasileiros (GitHub)",
                "Usado para": "Coordenada de referência (sede) de cada município, para escolas sem geolocalização real",
                "Acesso": "Repositório público",
            },
        ]
    )
    st.dataframe(fontes, width="stretch", hide_index=True)

    st.subheader("O que ainda não é dado oficial (e por quê)")
    st.markdown(
        "- **Velocidade por escola sem medição própria** (~40% das escolas "
        "com internet): o painel `conectividadenaeducacao.nic.br` do NIC.br "
        "não tem API pública nem download em massa — é um app R Shiny com "
        "sessão via WebSocket, sem endpoint programável. A equipe exportou "
        "manualmente a planilha completa através do próprio painel (ação "
        "humana, não automação), cobrindo 1.377 escolas públicas de MS — "
        "mas nem toda escola tem o medidor instalado (é opt-in). Para essas, "
        "a estimativa recua para a média real do Ookla Speedtest do "
        "município; para escolas privadas (fora do escopo do painel do "
        "NIC.br) e municípios sem tile do Ookla, recua mais uma vez para "
        "uma faixa genérica sintética.\n"
        "- **Nota de transparência (CGU/Escala Brasil Transparente)**: "
        "portal fora do ar para manutenção (checado em 06/09/2026) e só "
        "avalia municípios com mais de 50 mil habitantes — a maioria dos "
        "municípios de MS ficaria de fora mesmo com o portal no ar.\n"
        "- **Conselho municipal de educação ativo (IBGE/MUNIC)**: publicado "
        "como base de microdados completa, exige processamento à parte — "
        "fica para uma próxima iteração."
    )

    st.subheader("Fontes investigadas, mas não integradas (ou só parcialmente)")
    st.caption(
        "Documentado para deixar claro o processo de decisão, não só o "
        "resultado final."
    )
    investigadas = pd.DataFrame(
        [
            {
                "Fonte": "conectividadenaeducacao.nic.br (mapa de escolas)",
                "Status": "🟡 Integrado via export manual",
                "Detalhe": "Sem API — app R Shiny com sessão via WebSocket. A planilha (download/upload/latência/jitter/perda de pacotes/geolocalização reais) foi exportada manualmente pela equipe através do próprio painel, não por automação",
            },
            {
                "Fonte": "qualidadedainternet.nic.br",
                "Status": "⚪ Não integrado",
                "Detalhe": "Mesma limitação técnica (Shiny/sessão) e granularidade só por estado — pior que os 79 municípios já cobertos pelo Ookla, ou as 1.377 escolas já cobertas pelo painel acima",
            },
            {
                "Fonte": "Giga Maps (UNICEF/ITU)",
                "Status": "⚪ Não integrado",
                "Detalhe": "Conectividade real de +80 mil escolas brasileiras, mas API exige cadastro e permissão por país (protocolo Delta Sharing) — não é self-serve",
            },
            {
                "Fonte": "CGU — Escala Brasil Transparente",
                "Status": "⚪ Não integrado",
                "Detalhe": "Portal fora do ar para manutenção; só cobre municípios com mais de 50 mil habitantes",
            },
        ]
    )
    st.dataframe(investigadas, width="stretch", hide_index=True)

    st.subheader("Fórmulas usadas")
    with st.expander("Banda por aluno no turno de pico (Fase 2)"):
        st.latex(
            r"\text{Banda por aluno (kbps)} = "
            r"\frac{\text{Velocidade de download (Mbps)} \times 1000}"
            r"{\text{Matrículas totais} \times 0{,}40}"
        )
        st.markdown(
            "Turno de pico estimado em 40% das matrículas totais. "
            "Classificação: **Adequada** ≥ 1000 kbps/aluno · **Parcial** "
            "100–999 · **Insuficiente** < 100 (referência: Meta ENEC de "
            "1 Mbps/aluno)."
        )
    with st.expander("Índice de Prioridade de Intervenção — IPI (Fase 3)"):
        st.latex(
            r"IPI = \left[0{,}50 \times (1 - \text{possui banda larga}) + "
            r"0{,}30 \times \text{é rural} + 0{,}20 \times "
            r"\frac{\text{matrículas}}{\text{maior matrícula de MS}}"
            r"\right] \times 100"
        )
        st.markdown(
            "Escala de 0 a 100; quanto maior, mais prioritária a "
            "intervenção. A normalização por matrículas usa sempre a maior "
            "escola do estado inteiro, não da seleção filtrada, para o "
            "índice não mudar de escala conforme o filtro de município."
        )
    with st.expander("Velocidade estimada por escola (calibração com Ookla)"):
        st.markdown(
            "Sem medição real por escola disponível, cada leitura é "
            "simulada ancorada na média REAL do Ookla Speedtest para o "
            "município: escolas urbanas ficam entre 0,80x–1,30x dessa "
            "média; rurais, entre 0,15x–0,45x (suposição qualitativa "
            "documentada, não uma proporção medida). Um município sem "
            "nenhum tile do Ookla próximo recua para uma faixa genérica "
            "sintética — ver a coluna `fonte_medicao` por registro."
        )

    st.subheader("Ficha técnica")
    st.markdown(
        f"**Professor:** {PROFESSOR}  \n"
        f"**Autores:** {', '.join(AUTORES)}  \n"
        "**Disciplina:** Governança, Empreendedorismo e Inovação  \n"
        "**Curso:** Mestrado em Computação Aplicada — UFMS"
    )


# --------------------------------------------------------------------------- #
# Layout geral / ponto de entrada
# --------------------------------------------------------------------------- #


def renderizar_sidebar(municipios: pd.DataFrame, metadados: dict[str, str]) -> str:
    st.sidebar.title("📡 ConectaEscolas MS")
    st.sidebar.markdown(
        "**Mestrado em Computação Aplicada — UFMS**  \n"
        "Disciplina: Governança, Empreendedorismo e Inovação"
    )
    st.sidebar.markdown(f"**Professor:** {PROFESSOR}")
    st.sidebar.markdown("**Autores:**")
    for autor in AUTORES:
        st.sidebar.markdown(f"- {autor}")

    st.sidebar.divider()
    opcoes = [TODOS_OS_MUNICIPIOS] + municipios["no_municipio"].tolist()
    municipio_selecionado = st.sidebar.selectbox("Filtro Geral por Município", opcoes)

    if st.sidebar.button("🔄 Recarregar dados"):
        st.cache_data.clear()
        st.rerun()

    st.sidebar.divider()
    st.sidebar.markdown("**Procedência dos dados desta carga:**")
    # Lido de `metadata_execucao` (gravado por etl.py) em vez de um texto
    # fixo — assim o aviso reflete o que a carga REALMENTE usou (oficial ou
    # sintética), sem depender de manter comentário e código sincronizados.
    rotulos = {
        "fonte_municipios": "Municípios",
        "fonte_escolas": "Escolas",
        "fonte_medicoes_simet": "Velocidade",
    }
    for chave, rotulo in rotulos.items():
        valor = metadados.get(chave, "desconhecida (rode `python etl.py`)")
        if valor.startswith("oficial") or "medição real" in valor:
            emoji = "🟢"
        elif "estimativa calibrada" in valor:
            emoji = "🟡"
        else:
            emoji = "🟠"
        st.sidebar.caption(f"{emoji} **{rotulo}:** {valor}")
    st.sidebar.caption(
        "🟢 = fonte oficial ou medição real (NIC.br/SIMET) · 🟡 = estimativa "
        "por escola calibrada com dado real (Ookla) · 🟠 = amostra "
        "sintética/ilustrativa. Ver README.md para as fontes e limitações "
        "de cada uma."
    )
    return municipio_selecionado


def main() -> None:
    st.set_page_config(page_title="ConectaEscolas MS", page_icon="📡", layout="wide")

    conexao = obter_conexao()
    if conexao is None:
        st.error("Banco de dados não encontrado.")
        st.markdown("Rode os passos abaixo no terminal, na pasta do projeto, e recarregue a página:")
        st.code("python database.py\npython etl.py", language="bash")
        st.stop()

    municipios, escolas, medicoes, alternativas, metadados = carregar_tabelas(conexao)
    if escolas.empty:
        st.warning("O banco de dados existe, mas está vazio.")
        st.markdown("Rode a carga inicial de dados e recarregue a página:")
        st.code("python etl.py", language="bash")
        st.stop()

    base_completa = montar_base_escolas(municipios, escolas, medicoes)
    municipio_selecionado = renderizar_sidebar(municipios, metadados)

    if municipio_selecionado == TODOS_OS_MUNICIPIOS:
        base_filtrada = base_completa
    else:
        base_filtrada = base_completa[base_completa["no_municipio"] == municipio_selecionado]

    st.title("ConectaEscolas MS — Painel Integrado de Conectividade Escolar")
    st.markdown(
        "Diagnóstico dinâmico da conectividade nas escolas de Mato Grosso do Sul, "
        "cruzando matrículas (INEP) com velocidade real medida na região "
        "(Ookla Speedtest) para priorizar intervenções de infraestrutura."
    )

    aba1, aba2, aba3, aba4 = st.tabs(
        [
            "🗺️ Fase 1 — Mapeamento",
            "📶 Fase 2 — Banda por Aluno",
            "🛠️ Fase 3 — Soluções & SWOT",
            "📚 Fontes & Metodologia",
        ]
    )
    with aba1:
        renderizar_fase1(base_filtrada, municipios, municipio_selecionado)
    with aba2:
        renderizar_fase2(base_filtrada)
    with aba3:
        renderizar_fase3(base_filtrada, base_completa, alternativas)
    with aba4:
        renderizar_fontes_e_metodologia(municipios, escolas, metadados)


if __name__ == "__main__":
    main()

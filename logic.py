"""
logic.py
---------
Regras de negócio do GovTech MS: cálculo de banda por aluno, classificação
de qualidade de conexão, Índice de Prioridade de Intervenção (IPI) e
recomendação de tecnologia alternativa para escolas rurais vulneráveis.

Este módulo não depende de Streamlit, pandas nem SQLite de propósito:
mantê-lo puro (funções recebendo tipos simples e devolvendo tipos
simples) permite testá-lo isoladamente (`tests/test_logic.py`) e
reaproveitar as regras fora do painel, se necessário.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Optional

# Parcela das matrículas totais em uso simultâneo no horário de pico.
TURNO_PICO_PCT = 0.40

# Limiares de classificação, em kbps por aluno (referência: Meta ENEC de 1 Mbps/aluno).
LIMIAR_ADEQUADA = 1000.0
LIMIAR_PARCIAL = 100.0

CLASSIFICACAO_CORES = {
    "Adequada": "#2E7D32",       # verde
    "Parcial": "#F9A825",        # amarelo
    "Insuficiente": "#C62828",   # vermelho
    "Sem medição": "#9E9E9E",    # cinza — escola sem internet/sem medição SIMET
}


def calcular_banda_por_aluno(
    velocidade_download_mbps: Optional[float],
    qt_matriculas: Optional[int],
    turno_pico_pct: float = TURNO_PICO_PCT,
) -> Optional[float]:
    """Calcula a banda disponível por aluno no turno de pico, em kbps/aluno.

    Fórmula: (velocidade em kbps) / (matrículas totais * % turno de pico)

    Retorna `None` quando o cálculo não é possível (sem medição de
    velocidade ou sem matrículas cadastradas) em vez de lançar
    `ZeroDivisionError` — cabe ao chamador decidir como exibir a ausência
    de dado (ex.: rótulo "Sem medição").
    """
    if velocidade_download_mbps is None or qt_matriculas is None:
        return None
    if qt_matriculas <= 0:
        return None

    alunos_no_pico = qt_matriculas * turno_pico_pct
    if alunos_no_pico <= 0:
        return None

    velocidade_kbps = velocidade_download_mbps * 1000
    return velocidade_kbps / alunos_no_pico


def classificar_banda(banda_kbps_aluno: Optional[float]) -> str:
    """Classifica a banda por aluno segundo a meta ENEC (1 Mbps/aluno)."""
    if banda_kbps_aluno is None:
        return "Sem medição"
    if banda_kbps_aluno >= LIMIAR_ADEQUADA:
        return "Adequada"
    if banda_kbps_aluno >= LIMIAR_PARCIAL:
        return "Parcial"
    return "Insuficiente"


def calcular_ipi(
    possui_banda_larga: bool,
    localizacao_rural: bool,
    qt_matriculas: int,
    maior_matricula_ms: int,
    peso_status: float = 0.50,
    peso_rural: float = 0.30,
    peso_porte: float = 0.20,
) -> float:
    """Índice de Prioridade de Intervenção (0 a 100) de uma escola.

        IPI = [0.50 * (1 - Status_Internet_Banda_Larga)
               + 0.30 * Peso_Rural
               + 0.20 * (Matrículas / Maior_Matrícula_MS)] * 100

    Nota de correção em relação ao rascunho original da especificação:
    lá, `* 100` aparecia apenas ao lado do último termo
    (`a + b + c * 100`), o que, pela precedência de operadores do Python,
    multiplicava só a parcela de porte por 100 em vez do índice inteiro.
    Aqui a soma completa é escalada para a faixa 0–100, como pretendido
    pela definição do índice.

    `maior_matricula_ms` <= 0 (base vazia) não gera erro: o termo de
    porte relativo é tratado como zero nesse caso.
    """
    status_banda_larga = 1 if possui_banda_larga else 0
    peso_rural_valor = 1 if localizacao_rural else 0

    if maior_matricula_ms and maior_matricula_ms > 0:
        porte_relativo = min(qt_matriculas, maior_matricula_ms) / maior_matricula_ms
    else:
        porte_relativo = 0.0

    ipi = (
        peso_status * (1 - status_banda_larga)
        + peso_rural * peso_rural_valor
        + peso_porte * porte_relativo
    ) * 100

    return round(min(max(ipi, 0.0), 100.0), 2)


@dataclass
class Recomendacao:
    tecnologia: str
    provedor: str
    velocidade_oferta_mbps: float
    custo_mensal: float
    ganho_mbps: float


def recomendar_tecnologia(
    localizacao_rural: bool,
    velocidade_atual_mbps: Optional[float],
    alternativas: list[dict],
    limite_mbps: float = 10.0,
) -> Optional[Recomendacao]:
    """Sugere um provedor/tecnologia para escolas rurais com baixa velocidade.

    Critério de elegibilidade: escola RURAL com velocidade medida abaixo de
    `limite_mbps` (uma escola sem internet, ou seja, sem medição, é tratada
    como 0 Mbps). Entre as alternativas viáveis em área rural, escolhe a de
    melhor custo-benefício (maior velocidade ofertada por real investido).

    `alternativas` é uma lista de dicts com as colunas da tabela
    `alternativas_mercado` — assim este módulo não precisa conhecer pandas
    nem SQLite.
    """
    if not localizacao_rural:
        return None

    velocidade_atual = velocidade_atual_mbps if velocidade_atual_mbps is not None else 0.0
    if velocidade_atual >= limite_mbps:
        return None

    candidatas = [
        alt
        for alt in alternativas
        if alt.get("viabilidade_rural")
        and alt.get("tecnologia") in ("Satélite LEO", "Rádio WISP")
        and (alt.get("custo_mensal") or 0) > 0
    ]
    if not candidatas:
        return None

    melhor = max(candidatas, key=lambda alt: alt["velocidade_oferta"] / alt["custo_mensal"])

    return Recomendacao(
        tecnologia=melhor["tecnologia"],
        provedor=melhor["no_provedor"],
        velocidade_oferta_mbps=melhor["velocidade_oferta"],
        custo_mensal=melhor["custo_mensal"],
        ganho_mbps=round(melhor["velocidade_oferta"] - velocidade_atual, 2),
    )


# Fatores aplicados sobre a média REAL do Ookla Speedtest para o município
# (que mistura testes urbanos e rurais, dominados pelos urbanos) para
# simular a leitura de uma escola específica. A suposição de que escolas
# rurais tendem a ficar numa fração bem menor da média do município é
# qualitativa — não uma proporção medida — e está documentada no README.
FATOR_DOWNLOAD_URBANA = (0.80, 1.30)
FATOR_DOWNLOAD_RURAL = (0.15, 0.45)
FATOR_LATENCIA_URBANA = (0.90, 1.20)
FATOR_LATENCIA_RURAL = (1.50, 4.00)


def simular_medicao_calibrada(
    baseline_download_mbps: float,
    baseline_upload_mbps: float,
    baseline_latencia_ms: float,
    localizacao_rural: bool,
    rng: random.Random,
) -> tuple[float, float, float, float]:
    """Simula a medição de uma escola ancorada numa média REAL (Ookla) do município.

    Isso não é uma medição real da escola — não existe dataset aberto de
    velocidade por escola (ver README.md) — mas também deixa de ser um
    número arbitrário: o centro da distribuição é a velocidade média de
    verdade medida na região pelo Speedtest (Ookla), ajustada só pelo
    fator urbano/rural qualitativo acima.

    Retorna (velocidade_download_mbps, velocidade_upload_mbps, latencia_ms, perda_pacotes_pct).
    """
    fator_download_min, fator_download_max = FATOR_DOWNLOAD_RURAL if localizacao_rural else FATOR_DOWNLOAD_URBANA
    fator_latencia_min, fator_latencia_max = FATOR_LATENCIA_RURAL if localizacao_rural else FATOR_LATENCIA_URBANA

    fator_download = rng.uniform(fator_download_min, fator_download_max)
    velocidade_download = round(baseline_download_mbps * fator_download, 2)
    # Upload tende a ser uma fração do download (assimetria típica de banda
    # larga residencial/fibra GPON); aplica o mesmo fator de porte da
    # escola sobre o baseline de upload, com uma variação própria pequena.
    velocidade_upload = round(baseline_upload_mbps * fator_download * rng.uniform(0.85, 1.0), 2)
    latencia = round(baseline_latencia_ms * rng.uniform(fator_latencia_min, fator_latencia_max), 1)
    perda_pacotes = round(rng.uniform(1.0, 5.0) if localizacao_rural else rng.uniform(0.0, 1.5), 2)

    return velocidade_download, velocidade_upload, latencia, perda_pacotes

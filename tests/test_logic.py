"""Testes unitários das regras de negócio em `logic.py`.

Cobrem, em especial, os casos de borda que a especificação original não
tratava explicitamente: divisão por zero (matrículas = 0, maior matrícula
do estado = 0) e os limiares exatos de classificação da banda por aluno.
"""

import random

from logic import (
    calcular_banda_por_aluno,
    calcular_ipi,
    classificar_banda,
    recomendar_tecnologia,
    simular_medicao_calibrada,
)


def test_banda_por_aluno_formula_basica():
    # 100 Mbps para 500 matrículas -> pico de 200 alunos -> 500 kbps/aluno
    assert calcular_banda_por_aluno(100.0, 500) == 500.0


def test_banda_por_aluno_sem_matriculas_retorna_none():
    assert calcular_banda_por_aluno(50.0, 0) is None


def test_banda_por_aluno_matriculas_negativas_retorna_none():
    assert calcular_banda_por_aluno(50.0, -10) is None


def test_banda_por_aluno_sem_medicao_retorna_none():
    assert calcular_banda_por_aluno(None, 300) is None


def test_classificacao_nos_limiares_exatos():
    assert classificar_banda(1500) == "Adequada"
    assert classificar_banda(1000) == "Adequada"       # limite inclusivo
    assert classificar_banda(999.9) == "Parcial"
    assert classificar_banda(100) == "Parcial"          # limite inclusivo
    assert classificar_banda(99.9) == "Insuficiente"
    assert classificar_banda(None) == "Sem medição"


def test_ipi_escola_urbana_com_banda_larga_e_pequeno_porte_fica_perto_de_zero():
    ipi = calcular_ipi(
        possui_banda_larga=True, localizacao_rural=False, qt_matriculas=10, maior_matricula_ms=600
    )
    # apenas o termo de porte contribui: 0.20 * (10/600) * 100 ≈ 0.33
    assert 0 <= ipi < 1


def test_ipi_escola_rural_sem_banda_larga_e_maior_porte_atinge_maximo():
    ipi = calcular_ipi(
        possui_banda_larga=False, localizacao_rural=True, qt_matriculas=600, maior_matricula_ms=600
    )
    assert ipi == 100.0


def test_ipi_com_maior_matricula_zero_nao_gera_erro_de_divisao():
    ipi = calcular_ipi(
        possui_banda_larga=False, localizacao_rural=True, qt_matriculas=100, maior_matricula_ms=0
    )
    assert ipi == 80.0  # 0.50 (sem banda larga) + 0.30 (rural); termo de porte zerado


def test_recomendacao_escolhe_melhor_custo_beneficio_e_so_para_rural_lenta():
    alternativas = [
        {"tecnologia": "Fibra Óptica", "no_provedor": "X", "velocidade_oferta": 100, "custo_mensal": 150, "viabilidade_rural": 0},
        {"tecnologia": "Satélite LEO", "no_provedor": "Starlink Brasil", "velocidade_oferta": 220, "custo_mensal": 235, "viabilidade_rural": 1},
        {"tecnologia": "Rádio WISP", "no_provedor": "Rádio Rural MS", "velocidade_oferta": 15, "custo_mensal": 120, "viabilidade_rural": 1},
    ]

    assert recomendar_tecnologia(False, 2.0, alternativas) is None   # nunca recomenda p/ escola urbana
    assert recomendar_tecnologia(True, 20.0, alternativas) is None   # já é rápida o suficiente

    recomendacao = recomendar_tecnologia(True, 5.0, alternativas)
    assert recomendacao is not None
    assert recomendacao.provedor == "Starlink Brasil"  # maior Mbps por R$ investido (220/235 > 15/120)
    assert recomendacao.ganho_mbps == 215.0


def test_recomendacao_trata_escola_sem_internet_como_velocidade_zero():
    alternativas = [
        {"tecnologia": "Rádio WISP", "no_provedor": "Rádio Rural MS", "velocidade_oferta": 15, "custo_mensal": 120, "viabilidade_rural": 1},
    ]
    recomendacao = recomendar_tecnologia(True, None, alternativas)
    assert recomendacao is not None
    assert recomendacao.ganho_mbps == 15.0


def test_medicao_calibrada_urbana_fica_perto_do_baseline_real():
    rng = random.Random(1)
    vel_down, vel_up, latencia, perda = simular_medicao_calibrada(
        baseline_download_mbps=200.0, baseline_upload_mbps=150.0, baseline_latencia_ms=10.0,
        localizacao_rural=False, rng=rng,
    )
    assert 160.0 <= vel_down <= 260.0  # 0.80x-1.30x do baseline
    assert vel_up <= vel_down  # upload nunca ultrapassa a fração de download aplicada
    assert 0.0 <= perda <= 1.5


def test_medicao_calibrada_rural_fica_bem_abaixo_do_baseline_real():
    rng = random.Random(2)
    vel_down, _vel_up, latencia, perda = simular_medicao_calibrada(
        baseline_download_mbps=200.0, baseline_upload_mbps=150.0, baseline_latencia_ms=10.0,
        localizacao_rural=True, rng=rng,
    )
    assert 30.0 <= vel_down <= 90.0  # 0.15x-0.45x do baseline
    assert latencia >= 10.0  # fator rural é sempre >= 1.5x
    assert 1.0 <= perda <= 5.0


def test_medicao_calibrada_e_deterministica_com_a_mesma_seed():
    resultado_a = simular_medicao_calibrada(100.0, 80.0, 15.0, False, random.Random(42))
    resultado_b = simular_medicao_calibrada(100.0, 80.0, 15.0, False, random.Random(42))
    assert resultado_a == resultado_b

"""
fetch_dados_oficiais.py
------------------------
Busca dados oficiais em APIs públicas (IBGE, Siconfi/Tesouro Nacional) e
grava snapshots em `data/raw/`, para uso por `etl.py`.

Este é o ÚNICO ponto do projeto que precisa de acesso à internet. Ele é
separado do `etl.py` de propósito: `etl.py` continua rodando offline (a
partir dos CSVs já baixados, ou da amostra sintética se nada tiver sido
baixado ainda), o que é importante para reproduzir a demonstração sem
depender da disponibilidade das APIs externas no momento da apresentação.

Fontes usadas nesta versão:
    - IBGE (API de Localidades)      → lista oficial dos 79 municípios de MS
    - IBGE (API de Agregados/SIDRA)  → população estimada 2026 por município
    - Siconfi (Tesouro Nacional)     → despesa liquidada com Educação (RREO,
                                        Anexo 02) por município, usada para
                                        calcular o investimento per capita

Fontes que NÃO entraram nesta versão (limitações reais, documentadas em vez
de contornadas com dado inventado):
    - CGU / Escala Brasil Transparente: o Mapa Brasil Transparente está fora
      do ar para manutenção (checado em 06/09/2026, previsão de volta em
      11/2026); além disso, a metodologia só avalia municípios com mais de
      50 mil habitantes — a maioria dos municípios de MS ficaria de fora de
      qualquer forma. `nota_transparencia_ebt` fica NULL.
    - IBGE MUNIC (conselho municipal de educação ativo): a pesquisa é
      publicada como base de microdados completa (não uma tabela SIDRA
      simples), exigindo um passo de processamento à parte. Fica para uma
      próxima iteração. `conselho_educacao_ativo` fica NULL.

Uso:
    python fetch_dados_oficiais.py
"""

from __future__ import annotations

import csv
import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DATA_RAW_DIR = Path(__file__).resolve().parent / "data" / "raw"

IBGE_MUNICIPIOS_MS_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/estados/50/municipios"
IBGE_POPULACAO_URL = (
    "https://servicodados.ibge.gov.br/api/v3/agregados/6579/periodos/-1/variaveis/9324"
    "?localidades=N6[N3[50]]"
)
SICONFI_RREO_URL = "https://apidatalake.tesouro.gov.br/ords/siconfi/tt/rreo"

# RREO é publicado por bimestre (nr_periodo 1 a 6); o período 6 é o
# fechamento do ano inteiro (jan-dez). Tenta o ano mais recente primeiro e
# recua um ano se o município ainda não tiver enviado a prestação de contas.
ANOS_TENTATIVA = (2025, 2024)

# Municípios acima de 50 mil habitantes publicam o demonstrativo "RREO"
# completo; a maioria dos municípios de MS, menor que isso, publica o
# "RREO Simplificado" (mesma estrutura de Anexo 02, mesmos nomes de conta).
# Como o corte populacional exato pode mudar, tenta os dois em vez de
# decidir por população.
TIPOS_DEMONSTRATIVO = ("RREO", "RREO Simplificado")

CONTA_ALVO = "Educação"  # nome exato da função no RREO-Anexo 02 (total, não subfunção)
# Distingue o total "de verdade" (todas as despesas) da subtotal de
# despesas intra-orçamentárias, que também aparece com conta="Educação"
# mas é uma fração pequena — sem este filtro o valor coletado ficaria
# ambíguo entre as duas linhas.
COD_CONTA_ALVO = "RREO2TotalDespesas"
COLUNA_ALVO = "DESPESAS LIQUIDADAS ATÉ O BIMESTRE (d)"


def _get_json(url: str, timeout: int = 30) -> dict:
    requisicao = urllib.request.Request(url, headers={"Accept-Encoding": "gzip"})
    with urllib.request.urlopen(requisicao, timeout=timeout) as resposta:
        corpo = resposta.read()
        if resposta.info().get("Content-Encoding") == "gzip":
            corpo = gzip.decompress(corpo)
        return json.loads(corpo.decode("utf-8"))


def buscar_municipios_ibge() -> list[dict]:
    """Lista oficial dos 79 municípios de MS, com código IBGE e nome."""
    dados = _get_json(IBGE_MUNICIPIOS_MS_URL)
    municipios = [{"co_municipio": item["id"], "no_municipio": item["nome"]} for item in dados]
    municipios.sort(key=lambda m: m["no_municipio"])
    print(f"IBGE: {len(municipios)} municípios de MS encontrados.")
    return municipios


def buscar_populacao_ibge() -> dict[int, int]:
    """População estimada mais recente (SIDRA, agregado 6579) por município."""
    dados = _get_json(IBGE_POPULACAO_URL)
    populacao_por_municipio: dict[int, int] = {}
    for serie in dados[0]["resultados"][0]["series"]:
        co_municipio = int(serie["localidade"]["id"])
        (valor_str,) = serie["serie"].values()
        populacao_por_municipio[co_municipio] = int(valor_str)
    print(f"IBGE: população estimada obtida para {len(populacao_por_municipio)} municípios.")
    return populacao_por_municipio


def _despesa_educacao_no_ano(co_municipio: int, ano: int, tipo_demonstrativo: str) -> tuple[float, int] | None:
    """Consulta o RREO-Anexo 02 de um município/ano; retorna (despesa, população do Siconfi).

    Retorna None se o município não tiver esse tipo de demonstrativo
    publicado para aquele ano (uso normal: um município usa "RREO" OU
    "RREO Simplificado", nunca os dois no mesmo ano).
    """
    tipo_codificado = urllib.parse.quote(tipo_demonstrativo)
    url = (
        f"{SICONFI_RREO_URL}?an_exercicio={ano}&nr_periodo=6"
        f"&co_tipo_demonstrativo={tipo_codificado}&no_anexo=RREO-Anexo%2002&id_ente={co_municipio}"
    )
    try:
        dados = _get_json(url, timeout=45)
    except urllib.error.URLError as erro:
        print(f"  aviso: falha ao consultar Siconfi para {co_municipio}/{ano}/{tipo_demonstrativo}: {erro}")
        return None

    itens = dados.get("items", [])
    for item in itens:
        if (
            item.get("conta") == CONTA_ALVO
            and item.get("cod_conta") == COD_CONTA_ALVO
            and item.get("coluna") == COLUNA_ALVO
        ):
            return float(item["valor"]), int(item["populacao"])
    return None


def buscar_investimento_educacao_siconfi(municipios: list[dict]) -> dict[int, float]:
    """Investimento per capita em Educação (R$/habitante) por município.

    Usa a população reportada no próprio RREO (mais coerente com o valor
    de despesa do mesmo relatório) para o cálculo do per capita; a
    população da tabela `municipios` no banco usa a estimativa IBGE mais
    recente, que pode diferir ligeiramente — ambas são oficiais, só de
    anos-base distintos.
    """
    investimento_por_municipio: dict[int, float] = {}
    for i, municipio in enumerate(municipios, start=1):
        co_municipio = municipio["co_municipio"]
        resultado = None
        for ano in ANOS_TENTATIVA:
            for tipo_demonstrativo in TIPOS_DEMONSTRATIVO:
                resultado = _despesa_educacao_no_ano(co_municipio, ano, tipo_demonstrativo)
                if resultado is not None:
                    break
            if resultado is not None:
                break
        if resultado is None:
            print(f"  [{i}/{len(municipios)}] {municipio['no_municipio']}: sem RREO disponível, ficará sem dado.")
        else:
            despesa, populacao_siconfi = resultado
            if populacao_siconfi > 0:
                per_capita = round(despesa / populacao_siconfi, 2)
                investimento_por_municipio[co_municipio] = per_capita
                print(f"  [{i}/{len(municipios)}] {municipio['no_municipio']}: R$ {per_capita}/hab.")

        time.sleep(0.2)  # cortesia com a API pública — evita rajada de requisições (sempre roda, inclusive sem RREO)

    print(
        f"Siconfi: investimento em educação obtido para "
        f"{len(investimento_por_municipio)}/{len(municipios)} municípios."
    )
    return investimento_por_municipio


def salvar_municipios_csv(
    municipios: list[dict],
    populacao_por_municipio: dict[int, int],
    investimento_por_municipio: dict[int, float],
) -> None:
    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    caminho = DATA_RAW_DIR / "municipios_oficiais.csv"

    with open(caminho, "w", newline="", encoding="utf-8") as arquivo:
        escritor = csv.writer(arquivo)
        escritor.writerow(
            [
                "co_municipio",
                "no_municipio",
                "populacao_estimada",
                "investimento_per_capita_educacao",
                "nota_transparencia_ebt",
                "conselho_educacao_ativo",
            ]
        )
        for municipio in municipios:
            co_municipio = municipio["co_municipio"]
            escritor.writerow(
                [
                    co_municipio,
                    municipio["no_municipio"],
                    populacao_por_municipio.get(co_municipio, ""),
                    investimento_por_municipio.get(co_municipio, ""),
                    "",  # nota_transparencia_ebt — CGU indisponível (ver docstring do módulo)
                    "",  # conselho_educacao_ativo — MUNIC não processado nesta versão
                ]
            )
    print(f"Gravado: {caminho}")


def main() -> None:
    print("=== Buscando municípios e população (IBGE) ===")
    municipios = buscar_municipios_ibge()
    populacao_por_municipio = buscar_populacao_ibge()

    print("\n=== Buscando investimento em Educação por município (Siconfi/RREO) ===")
    investimento_por_municipio = buscar_investimento_educacao_siconfi(municipios)

    print("\n=== Gravando snapshot em data/raw/ ===")
    salvar_municipios_csv(municipios, populacao_por_municipio, investimento_por_municipio)


if __name__ == "__main__":
    main()

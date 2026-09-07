"""
processar_nicbr_simet.py
--------------------------
Filtra, da planilha "Base de Escolas SIMET" do painel Conectividade na
Educação (NIC.br), as escolas de Mato Grosso do Sul, e grava um CSV
pronto para `etl.py` com medição REAL de velocidade e geolocalização
REAL por escola.

De onde vem esse arquivo: `conectividadenaeducacao.nic.br` não tem API
pública (é um app R Shiny com sessão via WebSocket — ver README.md e a
aba "Fontes & Metodologia" do painel para os detalhes de por que isso não
é automatizável). O arquivo foi exportado MANUALMENTE, por uma pessoa
interagindo com o painel ao vivo e usando o botão de download da própria
ferramenta — não é raspagem nem automação, e o `nu_ano_censo` e a janela
de medição (últimos 6 meses) ficam registrados no nome do arquivo.

O arquivo combina Censo Escolar (INEP), medições SIMET (NIC.br), dados de
provedores (Anatel) e conectividade via satélite (MEC/MCOM) — a aba
"dicionario" dentro do próprio .xlsx documenta a fonte de cada coluna.

⚠️ Cobertura: essa base cobre só escolas PÚBLICAS (municipal/estadual/
federal) — nem toda escola do Censo Escolar aparece aqui (as privadas,
por exemplo, ficam de fora). E nem toda escola pública tem medição SIMET
própria (é um medidor opt-in) — por isso a saída aqui tem duas coisas
independentes por escola: geolocalização real (quase sempre presente) e
medição real (só quando `simet_num_measures_school > 0`). `etl.py` trata
os dois casos separadamente: usa a geolocalização real sempre que
disponível, e só substitui a estimativa calibrada com Ookla pela medição
real quando ela de fato existir.

Pré-requisito (não versionado — veja `data/raw/README.md`):
    DownloadManual/base-escolas-simet-*.xlsx
    (exportado manualmente de https://conectividadenaeducacao.nic.br/#mapa-escolas)

Uso:
    python processar_nicbr_simet.py
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

RAIZ_PROJETO = Path(__file__).resolve().parent
DOWNLOAD_MANUAL_DIR = RAIZ_PROJETO / "DownloadManual"
DATA_RAW_DIR = RAIZ_PROJETO / "data" / "raw"
CSV_SAIDA = DATA_RAW_DIR / "medicoes_reais_nicbr.csv"

CO_UF_MS = 50


def _encontrar_planilha_mais_recente() -> Path:
    candidatos = sorted(DOWNLOAD_MANUAL_DIR.glob("base-escolas-simet-*.xlsx"))
    if not candidatos:
        raise SystemExit(
            f"Não encontrei nenhum 'base-escolas-simet-*.xlsx' em {DOWNLOAD_MANUAL_DIR}.\n"
            "Exporte a planilha em https://conectividadenaeducacao.nic.br/#mapa-escolas "
            "e salve nessa pasta (o nome do arquivo já vem com a data do export)."
        )
    return candidatos[-1]  # nome inclui a data (YYYY-MM-DD) — o último em ordem alfabética é o mais recente


def _parse_numero_br(valor) -> float | None:
    """Converte '63,47' (formato BR, vírgula decimal) em 63.47.

    Também absorve texto não numérico como "sem medidor"/"sem informação"
    (usado na planilha quando não há medição), retornando `None` em vez
    de lançar erro.
    """
    if pd.isna(valor):
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    try:
        return float(str(valor).strip().replace(",", "."))
    except ValueError:
        return None


COLUNAS_NUMERICAS_BR = [
    "simet_mean_tcp_down_mbps",
    "simet_mean_tcp_up_mbps",
    "simet_mean_rtt_ms",
    "simet_mean_rtt_lost_pct",
    "simet_mean_jitter_download_ms",
    "simet_mean_jitter_upload_ms",
]


def carregar_planilha_ms(caminho: Path) -> pd.DataFrame:
    print(f"Lendo {caminho.name} (arquivo grande, pode levar um instante)...")
    df = pd.read_excel(caminho, sheet_name="base_dados", engine="openpyxl")
    ms = df[df["escolar_co_uf"] == CO_UF_MS].copy()
    print(f"  {len(ms)} escolas públicas de MS na planilha (de {len(df)} no Brasil todo).")
    return ms


def montar_tabela_final(ms: pd.DataFrame) -> pd.DataFrame:
    for coluna in COLUNAS_NUMERICAS_BR:
        ms[coluna] = ms[coluna].apply(_parse_numero_br)

    ms["tem_medicao_propria"] = ms["simet_num_measures_school"].fillna(0) > 0

    tabela = ms.rename(
        columns={
            "escolar_co_entidade": "co_entidade",
            "simet_mean_tcp_down_mbps": "velocidade_download_mbps",
            "simet_mean_tcp_up_mbps": "velocidade_upload_mbps",
            "simet_mean_rtt_ms": "latencia_ms",
            "simet_mean_rtt_lost_pct": "perda_pacotes_pct",
            "simet_mean_jitter_download_ms": "jitter_download_ms",
            "simet_mean_jitter_upload_ms": "jitter_upload_ms",
            "escolar_tipo_tecnologia": "tecnologia_conexao",
        }
    )

    return tabela[
        [
            "co_entidade",
            "latitude",
            "longitude",
            "tem_medicao_propria",
            "velocidade_download_mbps",
            "velocidade_upload_mbps",
            "latencia_ms",
            "perda_pacotes_pct",
            "jitter_download_ms",
            "jitter_upload_ms",
            "tecnologia_conexao",
        ]
    ]


def main() -> None:
    caminho = _encontrar_planilha_mais_recente()
    ms = carregar_planilha_ms(caminho)
    tabela_final = montar_tabela_final(ms)

    DATA_RAW_DIR.mkdir(parents=True, exist_ok=True)
    tabela_final.to_csv(CSV_SAIDA, index=False, encoding="utf-8")

    com_medicao = int(tabela_final["tem_medicao_propria"].sum())
    print(f"\nGravado: {CSV_SAIDA} ({len(tabela_final)} escolas)")
    print(f"  {com_medicao} com medição SIMET própria real (últimos 6 meses).")
    print(f"  {len(tabela_final) - com_medicao} sem medição própria (mas com geolocalização real).")


if __name__ == "__main__":
    main()

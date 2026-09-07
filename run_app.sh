#!/usr/bin/env bash
# run_app.sh — sobe o painel GovTech MS no Linux/Mac.
# Cria o ambiente virtual e o banco de dados na primeira vez que roda;
# nas vezes seguintes, só reaproveita o que já existe e inicia o Streamlit.
set -e
cd "$(dirname "$0")"

echo "============================================"
echo "  GovTech MS - Painel de Conectividade Escolar"
echo "============================================"
echo

if ! command -v python3 >/dev/null 2>&1; then
    echo "[ERRO] python3 não foi encontrado no PATH. Instale o Python 3.10+ e tente novamente."
    exit 1
fi

if [ ! -f ".venv/bin/python" ]; then
    echo "[1/4] Criando ambiente virtual em .venv ..."
    python3 -m venv .venv
else
    echo "[1/4] Ambiente virtual já existe."
fi

echo "[2/4] Verificando dependências (pode demorar na primeira vez)..."
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r requirements.txt

if [ ! -f "govtech_ms.db" ]; then
    echo "[3/4] Banco de dados não encontrado. Inicializando..."
    .venv/bin/python database.py
    .venv/bin/python etl.py
else
    echo "[3/4] Banco de dados já existe (apague govtech_ms.db e rode este script de novo para recarregar)."
fi

# Evita o prompt de boas-vindas do Streamlit (pede e-mail na 1a vez que
# roda na máquina), que travaria o terminal esperando resposta.
if [ ! -f "$HOME/.streamlit/credentials.toml" ]; then
    mkdir -p "$HOME/.streamlit"
    printf '[general]\nemail = ""\n' > "$HOME/.streamlit/credentials.toml"
fi

echo "[4/4] Iniciando o painel em http://localhost:8501 ..."
echo "(Pressione Ctrl+C para encerrar o painel.)"
echo
.venv/bin/streamlit run app.py

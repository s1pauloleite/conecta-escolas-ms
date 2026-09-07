@echo off
REM run_app.bat — sobe o painel GovTech MS com um duplo clique.
REM Cria o ambiente virtual e o banco de dados na primeira vez que roda;
REM nas vezes seguintes, só reaproveita o que já existe e inicia o Streamlit.

setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   GovTech MS - Painel de Conectividade Escolar
echo ============================================
echo.

REM --- Localiza um interpretador Python (python ou, no Windows, o launcher py) ---
set "PYTHON_CMD="
where python >nul 2>nul
if not errorlevel 1 set "PYTHON_CMD=python"
if not defined PYTHON_CMD (
    where py >nul 2>nul
    if not errorlevel 1 set "PYTHON_CMD=py"
)
if not defined PYTHON_CMD (
    echo [ERRO] Python nao foi encontrado no PATH.
    echo Instale o Python 3.10+ em https://python.org e tente novamente.
    pause
    exit /b 1
)

REM --- Cria o ambiente virtual se ainda nao existir ---
if not exist ".venv\Scripts\python.exe" (
    echo [1/4] Criando ambiente virtual em .venv ...
    %PYTHON_CMD% -m venv .venv
    if errorlevel 1 (
        echo [ERRO] Falha ao criar o ambiente virtual.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Ambiente virtual ja existe.
)

REM --- Instala/atualiza as dependencias ---
echo [2/4] Verificando dependencias (pode demorar na primeira vez)...
".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
".venv\Scripts\python.exe" -m pip install --quiet -r requirements.txt
if errorlevel 1 (
    echo [ERRO] Falha ao instalar as dependencias. Veja a mensagem acima.
    pause
    exit /b 1
)

REM --- Cria o banco e carrega os dados na primeira vez ---
if not exist "govtech_ms.db" (
    echo [3/4] Banco de dados nao encontrado. Inicializando...
    ".venv\Scripts\python.exe" database.py
    ".venv\Scripts\python.exe" etl.py
) else (
    echo [3/4] Banco de dados ja existe ^(use o botao "Recarregar dados" no painel, ou apague govtech_ms.db e rode este script de novo, para recarregar^).
)

REM --- Evita o prompt de boas-vindas do Streamlit (pede e-mail na 1a vez
REM     que roda na maquina) travando a janela esperando resposta ---
if not exist "%USERPROFILE%\.streamlit\credentials.toml" (
    if not exist "%USERPROFILE%\.streamlit" mkdir "%USERPROFILE%\.streamlit"
    (
        echo [general]
        echo email = ""
    ) > "%USERPROFILE%\.streamlit\credentials.toml"
)

REM --- Sobe o painel ---
echo [4/4] Iniciando o painel em http://localhost:8501 ...
echo (Feche esta janela ou pressione Ctrl+C para encerrar o painel.)
echo.
".venv\Scripts\streamlit.exe" run app.py

pause

@echo off
TITLE Inteligencia Territorial - Launcher
cd /d "%~dp0"

IF NOT EXIST "venv" (
    echo Creando entorno virtual...
    python -m venv venv
    call venv\Scripts\activate
    echo Instalando dependencias...
    pip install -r requirements.txt
    cls
) ELSE (
    call venv\Scripts\activate
)

echo INICIANDO PLATAFORMA...
streamlit run app.py
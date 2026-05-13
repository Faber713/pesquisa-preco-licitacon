@echo off
title Pesquisa Inteligente LicitaCon
echo Iniciando interface web...
echo.
set "PYTHON_CMD=python"

if exist ".venv\Scripts\python.exe" (
    set "PYTHON_CMD=.venv\Scripts\python.exe"
) else (
    echo Ambiente virtual .venv nao encontrado.
    echo Usando o Python instalado no sistema.
    echo.
)

%PYTHON_CMD% -m streamlit run app_web.py
pause

@echo off
title Pesquisa Inteligente LicitaCon
echo Iniciando interface web...
echo.
if not exist ".venv\Scripts\python.exe" (
    echo Ambiente virtual nao encontrado em .venv
    echo Execute: python -m venv .venv
    echo Depois: .venv\Scripts\python.exe -m pip install -r requirements_web.txt
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m streamlit run app_web.py
pause

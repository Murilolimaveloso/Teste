@echo off
chcp 65001 >nul
cd /d "%~dp0"
title ORION
where python >nul 2>nul || (echo Python nao encontrado. Instale em https://www.python.org/downloads/ marcando "Add Python to PATH". & pause & exit /b)
if not exist .venv (
  echo Criando ambiente virtual...
  python -m venv .venv
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
if not exist .env (
  copy .env.example .env >nul
  echo.
  echo Abra o arquivo .env e coloque sua ANTHROPIC_API_KEY. Depois rode este arquivo de novo.
  notepad .env
  pause
  exit /b
)
python server.py
pause

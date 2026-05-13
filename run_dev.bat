@echo off
title OCR PDF - Modo Desenvolvimento

echo Instalando dependencias...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo Iniciando app...
python app.py

pause
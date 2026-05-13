@echo off
title Build OCR PDF

echo Limpando builds antigos...
rmdir /s /q build 2>nul
rmdir /s /q dist 2>nul
del /q app.spec 2>nul

echo.
echo Instalando dependencias...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo.
echo Gerando executavel...
python -m PyInstaller ^
  --name "OCR_PDF" ^
  --onefile ^
  --windowed ^
  app.py

echo.
echo Build finalizado.
echo O executavel esta em:
echo dist\OCR_PDF.exe

pause
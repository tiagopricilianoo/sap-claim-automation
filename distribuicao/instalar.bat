@echo off
chcp 65001 >nul
title Automação de Claims - instalação
pushd "%~dp0"
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERRO] Python não encontrado. Instale o Python e rode de novo.
    echo.
    popd
    pause
    exit /b 1
)
python "%~dp0instalar.py"
popd
echo.
pause

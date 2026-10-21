@echo off
chcp 65001 >nul
title Automação de Claims - instalação
setlocal
set "LOCAL=%LOCALAPPDATA%\AutomacaoClaims"

rem 1) Python embutido no servidor (não depende de Python instalado nem de internet)
if exist "%~dp0python\pythonw.exe" (
    echo.
    echo  Copiando o Python do programa ^(pode levar 1 ou 2 minutos^)...
    robocopy "%~dp0python" "%LOCAL%\python" /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS /NP >nul
    if errorlevel 8 (
        echo.
        echo  [ERRO] Não foi possível copiar o Python do servidor.
        echo.
        pause
        exit /b 1
    )
    "%LOCAL%\python\python.exe" "%~dp0instalar.py" --python-embutido
    goto fim
)

rem 2) Sem Python no servidor: usa o Python instalado no computador
python --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [ERRO] Python não encontrado neste computador e não há Python no servidor.
    echo         Peça ao responsável pela ferramenta.
    echo.
    pause
    exit /b 1
)
python "%~dp0instalar.py"

:fim
echo.
pause

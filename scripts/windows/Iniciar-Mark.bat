@echo off
rem Lanzador de Mark (OpenJarvis). Lo usa el acceso directo del escritorio.
setlocal
title Mark
cd /d "%~dp0..\.."

where uv >nul 2>nul
if errorlevel 1 (
    echo Instalando uv ^(gestor de Python^)...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
where uv >nul 2>nul
if errorlevel 1 (
    echo No se pudo instalar uv. Instalalo desde https://docs.astral.sh/uv/ y vuelve a intentar.
    pause
    exit /b 1
)

where npm >nul 2>nul
if errorlevel 1 goto texto

echo Iniciando Mark ^(interfaz grafica en el navegador^)...
uv run --extra desktop mark gui
goto fin

:texto
echo Node.js 22+ no esta instalado: Mark se abre en modo texto.
echo Instala Node.js desde https://nodejs.org para usar la interfaz grafica.
echo.
uv run mark

:fin
if errorlevel 1 (
    echo.
    echo Mark termino con un error. Diagnostico: uv run mark doctor
    pause
)
endlocal

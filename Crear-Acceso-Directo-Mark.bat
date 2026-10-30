@echo off
rem Instala o actualiza Mark y crea su acceso directo "Mark" en el escritorio.
rem Mark abre como su app de Windows (runtime\desktop\JarvisLocal.exe), con las
rem capacidades de OpenJarvis integradas. Todo corre local y sin inicio de sesion.
rem Puede ejecutarse desde la carpeta del repositorio o descargado suelto: en ese
rem caso usa (o clona) el repositorio en MARK_DIR y lo actualiza.
rem El trabajo lo hace scripts\Install-Mark.ps1 (deja un registro en data\logs).
setlocal EnableExtensions
title Instalar o actualizar Mark

set "REPO_URL=https://github.com/Srkorben/JarvisLocal-Mark.git"
set "FEATURE_BRANCH=claude/determined-ramanujan-1k1mlz"
if not defined MARK_DIR set "MARK_DIR=%USERPROFILE%\Documents\AI Local\JarvisLocal"

rem 1) Si este .bat esta dentro del repositorio nuevo, usarlo tal cual.
if exist "%~dp0scripts\Install-Mark.ps1" (
    set "MARK_DIR=%~dp0."
    goto instalar
)

where git >nul 2>nul
if errorlevel 1 (
    echo Git no esta instalado. Instalalo desde https://git-scm.com y vuelve a ejecutar este archivo.
    goto error
)

rem 2) Clonar si la carpeta no existe; si existe, traer la version nueva.
rem    Los datos locales (data, models, runtime, entornos de voz) no se tocan.
if not exist "%MARK_DIR%\.git" (
    echo Clonando Mark en "%MARK_DIR%"...
    git clone "%REPO_URL%" "%MARK_DIR%" || goto error
)
pushd "%MARK_DIR%" || goto error
git fetch origin || goto error_pop
set "BRANCH=%FEATURE_BRANCH%"
git cat-file -e origin/master:scripts/Install-Mark.ps1 2>nul && set "BRANCH=master"
echo Usando la rama %BRANCH%...
git checkout "%BRANCH%" || goto error_pop
git pull --ff-only origin "%BRANCH%" || goto error_pop
popd

:instalar
for %%I in ("%MARK_DIR%") do set "MARK_DIR=%%~fI"
powershell -NoProfile -ExecutionPolicy Bypass -File "%MARK_DIR%\scripts\Install-Mark.ps1"
if errorlevel 1 goto error
echo.
echo Listo. Abre Mark con el icono "Mark" del escritorio.
pause
exit /b 0

:error_pop
popd
:error
echo.
echo La instalacion no termino bien. Revisa el resumen y el registro en data\logs.
echo Si git no pudo actualizar, revisa si hay cambios locales en "%MARK_DIR%".
pause
exit /b 1

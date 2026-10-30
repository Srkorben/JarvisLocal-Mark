@echo off
rem Crea (o actualiza) el acceso directo "Mark" en el escritorio.
rem Puede ejecutarse desde la carpeta del repositorio o descargado suelto:
rem en ese caso usa (o clona) el repositorio en MARK_DIR.
setlocal EnableExtensions
title Crear acceso directo de Mark

set "REPO_URL=https://github.com/Srkorben/JarvisLocal-Mark.git"
set "FEATURE_BRANCH=claude/determined-ramanujan-1k1mlz"
if not defined MARK_DIR set "MARK_DIR=%USERPROFILE%\Documents\AI Local\JarvisLocal"

rem 1) Si este .bat esta dentro del repositorio nuevo, usarlo tal cual.
if exist "%~dp0src\openjarvis\speech\mark_voice\backend.py" (
    set "MARK_DIR=%~dp0."
    goto acceso
)

where git >nul 2>nul
if errorlevel 1 (
    echo Git no esta instalado. Instalalo desde https://git-scm.com y vuelve a ejecutar este archivo.
    pause
    exit /b 1
)

rem 2) Clonar si la carpeta no existe; si existe, traer la version nueva.
if not exist "%MARK_DIR%\.git" (
    echo Clonando Mark en "%MARK_DIR%"...
    git clone "%REPO_URL%" "%MARK_DIR%" || goto error
)
pushd "%MARK_DIR%" || goto error
git fetch origin || goto error_pop
rem Usar master si ya contiene el Mark nuevo; si no, la rama del cambio.
set "BRANCH=%FEATURE_BRANCH%"
git cat-file -e origin/master:src/openjarvis/speech/mark_voice/backend.py 2>nul && set "BRANCH=master"
echo Usando la rama %BRANCH%...
git checkout "%BRANCH%" || goto error_pop
git pull --ff-only origin "%BRANCH%" || goto error_pop
popd

:acceso
for %%I in ("%MARK_DIR%") do set "MARK_DIR=%%~fI"
if not exist "%MARK_DIR%\scripts\windows\Iniciar-Mark.bat" (
    echo No se encontro el lanzador en "%MARK_DIR%".
    goto error
)
set "MARK_DIR_PS=%MARK_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$dir = $env:MARK_DIR_PS;" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$lnk = Join-Path $desktop 'Mark.lnk';" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk);" ^
  "$s.TargetPath = Join-Path $dir 'scripts\windows\Iniciar-Mark.bat';" ^
  "$s.WorkingDirectory = $dir;" ^
  "$s.IconLocation = (Join-Path $dir 'assets\mark.ico') + ',0';" ^
  "$s.Description = 'Mark - asistente personal local (OpenJarvis)';" ^
  "$s.Save();" ^
  "Write-Host ('Acceso directo creado: ' + $lnk)"
if errorlevel 1 goto error
echo.
echo Listo. Abre Mark con el icono "Mark" del escritorio.
pause
exit /b 0

:error_pop
popd
:error
echo.
echo No se pudo crear el acceso directo. Revisa los mensajes anteriores.
pause
exit /b 1

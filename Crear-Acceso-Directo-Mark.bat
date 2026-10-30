@echo off
rem Prepara Mark y crea (o actualiza) el acceso directo "Mark" en el escritorio.
rem Mark abre como su programa de Windows de siempre (runtime\desktop\JarvisLocal.exe):
rem sin navegador y sin inicio de sesion. Su cerebro es OpenJarvis (via Ollama).
rem Puede ejecutarse desde la carpeta del repositorio o descargado suelto:
rem en ese caso usa (o clona) el repositorio en MARK_DIR.
setlocal EnableExtensions
title Preparar Mark

set "REPO_URL=https://github.com/Srkorben/JarvisLocal-Mark.git"
set "FEATURE_BRANCH=claude/determined-ramanujan-1k1mlz"
set "DEFAULT_MODEL=qwen3:8b"
if not defined MARK_DIR set "MARK_DIR=%USERPROFILE%\Documents\AI Local\JarvisLocal"

rem 1) Si este .bat esta dentro del repositorio nuevo, usarlo tal cual.
if exist "%~dp0src\jarvis_local\model_providers\openjarvis_engine.py" (
    set "MARK_DIR=%~dp0."
    goto dependencias
)

where git >nul 2>nul
if errorlevel 1 (
    echo Git no esta instalado. Instalalo desde https://git-scm.com y vuelve a ejecutar este archivo.
    goto error
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
git cat-file -e origin/master:src/jarvis_local/model_providers/openjarvis_engine.py 2>nul && set "BRANCH=master"
echo Usando la rama %BRANCH%...
git checkout "%BRANCH%" || goto error_pop
git pull --ff-only origin "%BRANCH%" || goto error_pop
popd

:dependencias
for %%I in ("%MARK_DIR%") do set "MARK_DIR=%%~fI"
cd /d "%MARK_DIR%" || goto error

rem 3) uv: gestor de Python (usa Python 3.12, fijado en .python-version).
where uv >nul 2>nul
if errorlevel 1 (
    echo Instalando uv...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://astral.sh/uv/install.ps1 | iex"
    set "PATH=%USERPROFILE%\.local\bin;%PATH%"
)
where uv >nul 2>nul
if errorlevel 1 (
    echo No se pudo instalar uv. Instalalo desde https://docs.astral.sh/uv/
    goto error
)
rem Cerrar instancias de Mark abiertas (bloquean mark.exe durante la instalacion).
rem Solo se detienen procesos que se ejecutan desde la .venv de esta carpeta.
set "MARK_VENV_PS=%MARK_DIR%\.venv\"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$venv = $env:MARK_VENV_PS;" ^
  "$all = Get-CimInstance Win32_Process;" ^
  "$ids = @($all | Where-Object { $_.ExecutablePath -and $_.ExecutablePath.StartsWith($venv, [StringComparison]::OrdinalIgnoreCase) } | ForEach-Object { $_.ProcessId });" ^
  "do { $n = $ids.Count; $ids = @($ids + @($all | Where-Object { $ids -contains $_.ParentProcessId } | ForEach-Object { $_.ProcessId }) | Select-Object -Unique) } while ($ids.Count -gt $n);" ^
  "$procs = @($all | Where-Object { $ids -contains $_.ProcessId });" ^
  "foreach ($p in $procs) { Write-Host ('Cerrando ' + $p.Name + ' (PID ' + $p.ProcessId + ')'); Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue };" ^
  "if ($procs.Count) { Start-Sleep -Seconds 2 }"

echo Instalando dependencias de Mark ^(la primera vez tarda unos minutos^)...
uv sync --extra mark-audio --extra server
if errorlevel 1 (
    echo Reintentando en 5 segundos...
    timeout /t 5 /nobreak >nul
    uv sync --extra mark-audio --extra server || goto error_bloqueo
)
if not exist "%MARK_DIR%\.venv\Scripts\pythonw.exe" (
    echo No se creo el entorno de Python de Mark ^(.venv^).
    goto error
)

rem 4) Interfaz completa de OpenJarvis (boton "OpenJarvis" dentro de Mark).
rem Se compila con Node.js solo cuando cambia el codigo de la interfaz.
set "OJ_STAMP=%MARK_DIR%\src\openjarvis\server\static\.mark-build"
set "OJ_TREE="
for /f %%H in ('git -C "%MARK_DIR%" rev-parse HEAD:frontend 2^>nul') do set "OJ_TREE=%%H"
set "OJ_BUILT="
if exist "%OJ_STAMP%" set /p OJ_BUILT=<"%OJ_STAMP%"
if exist "%MARK_DIR%\src\openjarvis\server\static\index.html" if defined OJ_TREE if "%OJ_BUILT%"=="%OJ_TREE%" goto ollama
where npm >nul 2>nul
if errorlevel 1 (
    echo Instalando Node.js ^(necesario para compilar la interfaz de OpenJarvis^)...
    winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
    set "PATH=%ProgramFiles%\nodejs;%PATH%"
)
where npm >nul 2>nul
if errorlevel 1 (
    echo No se pudo instalar Node.js. Instalalo desde https://nodejs.org y vuelve a ejecutar este archivo.
    goto error
)
echo Compilando la interfaz de OpenJarvis ^(solo cuando cambia, tarda un par de minutos^)...
pushd "%MARK_DIR%\frontend" || goto error
call npx -y npm@11 ci --no-audit --no-fund || goto error_pop
call npx -y npm@11 run build || goto error_pop
popd
if defined OJ_TREE (echo %OJ_TREE%>"%OJ_STAMP%")

:ollama
rem 5) Ollama: motor local de IA, con el modelo de Mark.
set "OLLAMA=ollama"
where ollama >nul 2>nul
if errorlevel 1 set "OLLAMA=%LOCALAPPDATA%\Programs\Ollama\ollama.exe"
if not exist "%OLLAMA%" if "%OLLAMA%" neq "ollama" (
    echo Instalando Ollama...
    winget install -e --id Ollama.Ollama --accept-source-agreements --accept-package-agreements
)
if "%OLLAMA%" neq "ollama" if not exist "%OLLAMA%" (
    echo No se pudo instalar Ollama. Instalalo desde https://ollama.com y vuelve a ejecutar este archivo.
    goto error
)
rem Si Ollama no esta corriendo, iniciarlo oculto (sin ventana de consola).
"%OLLAMA%" list >nul 2>nul
if errorlevel 1 (
    set "OLLAMA_PS=%OLLAMA%"
    powershell -NoProfile -ExecutionPolicy Bypass -Command "$exe = $env:OLLAMA_PS; if ($exe -eq 'ollama') { $exe = (Get-Command ollama).Source }; Start-Process -FilePath $exe -ArgumentList 'serve' -WindowStyle Hidden"
    timeout /t 5 /nobreak >nul
)
"%OLLAMA%" list 2>nul | findstr /b /i /c:"%DEFAULT_MODEL% " >nul
if errorlevel 1 (
    echo Descargando el modelo %DEFAULT_MODEL% ^(unos 5 GB, solo la primera vez^)...
    "%OLLAMA%" pull %DEFAULT_MODEL% || goto error
)

rem 6) La app de escritorio de Mark. Si no esta publicada, publicarla (.NET 8 SDK).
if not exist "%MARK_DIR%\runtime\desktop\JarvisLocal.exe" (
    echo Publicando la app de escritorio de Mark...
    powershell -NoProfile -ExecutionPolicy Bypass -File "%MARK_DIR%\scripts\Publish-Desktop.ps1"
)
if not exist "%MARK_DIR%\runtime\desktop\JarvisLocal.exe" (
    echo Falta runtime\desktop\JarvisLocal.exe. Instala .NET 8 SDK
    echo ^(https://dotnet.microsoft.com/download/dotnet/8.0^) y vuelve a ejecutar este archivo.
    goto error
)

rem 7) Acceso directo.
set "MARK_DIR_PS=%MARK_DIR%"
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$dir = $env:MARK_DIR_PS;" ^
  "$desktop = [Environment]::GetFolderPath('Desktop');" ^
  "$lnk = Join-Path $desktop 'Mark.lnk';" ^
  "$s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk);" ^
  "$s.TargetPath = Join-Path $dir 'runtime\desktop\JarvisLocal.exe';" ^
  "$s.WorkingDirectory = $dir;" ^
  "$s.IconLocation = (Join-Path $dir 'assets\mark-scout.ico') + ',0';" ^
  "$s.Description = 'Mark - asistente personal local';" ^
  "$s.Save();" ^
  "Write-Host ('Acceso directo creado: ' + $lnk)"
if errorlevel 1 goto error
echo.
echo Listo. Abre Mark con el icono "Mark" del escritorio.
pause
exit /b 0

:error_bloqueo
echo.
echo Algun archivo de Mark sigue en uso. Cierra cualquier ventana o consola de Mark
echo ^(o reinicia el PC^) y vuelve a ejecutar este archivo.
pause
exit /b 1

:error_pop
popd
:error
echo.
echo No se pudo completar la preparacion de Mark. Revisa los mensajes anteriores.
pause
exit /b 1

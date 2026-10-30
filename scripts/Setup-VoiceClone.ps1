[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python312 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
$VenvPath = Join-Path $ProjectRoot '.venv-chatterbox-cuda'
$PythonExe = Join-Path $VenvPath 'Scripts\python.exe'
$ModelPath = Join-Path $ProjectRoot 'models\chatterbox-es-latam'
$ChatterboxCommit = '5de7a54aa4e5e2baadb0182dde554908b48b85c2'
$PerthCommit = 'ff1c8ac55a976971245cdd53c18d6131ca00d993'

if (-not (Test-Path -LiteralPath $Python312)) {
    throw "Python 3.12 no está instalado en $Python312"
}

$drive = Get-PSDrive -Name ([System.IO.Path]::GetPathRoot($ProjectRoot).TrimEnd(':','\'))
if ($drive.Free -lt 10GB) {
    throw 'Se requieren al menos 10 GiB libres para entorno, caché y modelo.'
}

if (-not (Test-Path -LiteralPath $VenvPath)) {
    & $Python312 -m venv $VenvPath
}

& $PythonExe -m pip install --upgrade pip setuptools wheel
# RTX 50 (Blackwell/sm_120) necesita wheels modernos. Chatterbox fija todavía
# torch 2.6 en sus metadatos; se instala sin dependencias para conservar el
# wheel CUDA compatible y se fijan explícitamente las dependencias usadas.
& $PythonExe -m pip install torch==2.9.1 torchaudio==2.9.1 --index-url https://download.pytorch.org/whl/cu128
& $PythonExe -m pip install numpy==1.26.4 librosa==0.11.0 transformers==5.2.0 diffusers==0.29.0 conformer==0.3.2 safetensors==0.5.3 pykakasi==2.3.0 s3tokenizer==0.3.0 spacy-pkuseg==1.0.1 pyloudnorm==0.2.0 omegaconf==2.3.1 pydub==0.25.1
& $PythonExe -m pip install --no-deps "git+https://github.com/resemble-ai/Perth.git@$PerthCommit"
& $PythonExe -m pip install --no-deps "git+https://github.com/resemble-ai/chatterbox.git@$ChatterboxCommit"
& $PythonExe -m pip install --editable $ProjectRoot --no-deps
& $PythonExe -m jarvis_local.voice_clone_models --destination $ModelPath

& $PythonExe -c "import torch; assert torch.cuda.is_available(); assert (12, 0) in [tuple(map(int, item.removeprefix('sm_').split('_'))) if '_' in item.removeprefix('sm_') else (int(item.removeprefix('sm_')) // 10, int(item.removeprefix('sm_')) % 10) for item in torch.cuda.get_arch_list()]; print(torch.__version__, torch.cuda.get_device_name(0), torch.cuda.get_device_capability(0))"

Write-Host 'Chatterbox CUDA quedó instalado de forma aislada; el entorno CPU anterior se conserva como respaldo.'
Write-Host 'El backend seguirá bloqueado hasta enrolar explícitamente tu propia voz.'

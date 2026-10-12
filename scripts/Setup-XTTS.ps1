[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python312 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
$VenvPath = Join-Path $ProjectRoot '.venv-xtts'
$PythonExe = Join-Path $VenvPath 'Scripts\python.exe'
$ModelPath = Join-Path $ProjectRoot 'models\xtts-v2'
$ModelRevision = '6c2b0d75eae4b7047358e3b6bd9325f857d43f77'

if (-not (Test-Path -LiteralPath $Python312)) {
    throw "Python 3.12 no está instalado en $Python312"
}

$driveName = [System.IO.Path]::GetPathRoot($ProjectRoot).TrimEnd(':','\')
$drive = Get-PSDrive -Name $driveName
if ($drive.Free -lt 10GB) {
    throw 'Se requieren al menos 10 GiB libres para entorno, caché y modelo.'
}

Write-Host 'XTTS-v2 usa Coqui Public Model License:'
Write-Host 'https://huggingface.co/coqui/XTTS-v2/blob/main/LICENSE.txt'

if (-not (Test-Path -LiteralPath $VenvPath)) {
    & $Python312 -m venv $VenvPath
}

& $PythonExe -m pip install --upgrade pip setuptools wheel
& $PythonExe -m pip install torch==2.9.1+cu128 torchaudio==2.9.1+cu128 --index-url https://download.pytorch.org/whl/cu128
& $PythonExe -m pip install coqui-tts==0.27.5 torchcodec==0.9.1
# Transformers 5.x retiró una función que XTTS 0.27.5 todavía utiliza.
& $PythonExe -m pip install transformers==4.57.6
& $PythonExe -m pip install --editable $ProjectRoot --no-deps

$download = "from huggingface_hub import snapshot_download; snapshot_download(repo_id='coqui/XTTS-v2', revision='$ModelRevision', local_dir=r'$ModelPath', allow_patterns=['config.json','dvae.pth','model.pth','speakers_xtts.pth','vocab.json','LICENSE.txt','README.md'])"
$env:HF_HUB_DISABLE_TELEMETRY = '1'
& $PythonExe -c $download

& $PythonExe -c "import torch, TTS, transformers; assert torch.cuda.is_available(); assert transformers.__version__ == '4.57.6'; print(TTS.__version__, torch.__version__, torch.cuda.get_device_name(0))"

Write-Host 'XTTS-v2 quedó instalado de forma aislada y fijado por revisión.'
Write-Host 'La voz seguirá bloqueada si falta una referencia local con consentimiento válido.'

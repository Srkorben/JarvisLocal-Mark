[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$PSNativeCommandUseErrorActionPreference = $true
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Python312 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
$VenvPath = Join-Path $ProjectRoot '.venv-qwen3-tts'
$PythonExe = Join-Path $VenvPath 'Scripts\python.exe'
$ModelPath = Join-Path $ProjectRoot 'models\qwen3-tts-12hz-0.6b-base'
$ModelRevision = '5d83992436eae1d760afd27aff78a71d676296fc'

if (-not (Test-Path -LiteralPath $Python312)) {
    throw "Python 3.12 no está instalado en $Python312"
}

$driveName = [System.IO.Path]::GetPathRoot($ProjectRoot).TrimEnd(':','\')
$drive = Get-PSDrive -Name $driveName
if ($drive.Free -lt 12GB) {
    throw 'Se requieren al menos 12 GiB libres para entorno, caché y modelo.'
}

Write-Host 'Qwen3-TTS y Qwen3-TTS-12Hz-0.6B-Base usan Apache-2.0:'
Write-Host 'https://github.com/QwenLM/Qwen3-TTS'
Write-Host 'https://huggingface.co/Qwen/Qwen3-TTS-12Hz-0.6B-Base'

if (-not (Test-Path -LiteralPath $VenvPath)) {
    & $Python312 -m venv $VenvPath
}

& $PythonExe -m pip install --upgrade pip setuptools wheel
& $PythonExe -m pip install torch==2.9.1+cu128 torchaudio==2.9.1+cu128 --index-url https://download.pytorch.org/whl/cu128
& $PythonExe -m pip install qwen-tts==0.1.1 transformers==4.57.3 huggingface-hub==0.36.2
& $PythonExe -m pip install --editable $ProjectRoot --no-deps

$allowPatterns = "['config.json','generation_config.json','merges.txt','model.safetensors','preprocessor_config.json','README.md','tokenizer_config.json','vocab.json','speech_tokenizer/*']"
$download = "from huggingface_hub import snapshot_download; snapshot_download(repo_id='Qwen/Qwen3-TTS-12Hz-0.6B-Base', revision='$ModelRevision', local_dir=r'$ModelPath', allow_patterns=$allowPatterns)"
$env:HF_HUB_DISABLE_TELEMETRY = '1'
& $PythonExe -c $download

& $PythonExe -c "import torch, transformers; from qwen_tts import Qwen3TTSModel; assert torch.cuda.is_available(); assert transformers.__version__ == '4.57.3'; print(torch.__version__, torch.cuda.get_device_name(0))"

Write-Host 'Qwen3-TTS Base 0.6B quedó instalado de forma aislada y fijado por revisión.'
Write-Host 'La voz seguirá bloqueada si faltan reference.wav, reference.txt o un consentimiento SHA-256 válido.'

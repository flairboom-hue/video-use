# AI Video Editor - Windows installer. Idempotent: nothing already present is reinstalled.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

function Ok($m)   { Write-Host "  ok   $m" -ForegroundColor Green }
function Miss($m) { Write-Host "  miss $m" -ForegroundColor Yellow }
function Die($m)  { Write-Host "  fail $m" -ForegroundColor Red; exit 1 }

Write-Host "AI Video Editor - install`n"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    Die "Python 3.10+ is required.  winget install Python.Python.3.12"
}
$pyv = (python -c "import sys;print('%d.%d'%sys.version_info[:2])")
python -c "import sys;sys.exit(0 if sys.version_info>=(3,10) else 1)"
if ($LASTEXITCODE -ne 0) { Die "Python $pyv found, 3.10+ required." }
Ok "Python $pyv"

if ((Get-Command ffmpeg -ErrorAction SilentlyContinue) -and
    (Get-Command ffprobe -ErrorAction SilentlyContinue)) {
    Ok "ffmpeg"
} else {
    Miss "ffmpeg - required"
    Write-Host "    winget install Gyan.FFmpeg"
    Write-Host "    (open a NEW terminal afterwards so PATH is picked up)"
    Die "install ffmpeg, then re-run"
}

if (-not (Test-Path ".venv")) { python -m venv .venv; Ok "created .venv" } else { Ok ".venv exists" }
$py = ".\.venv\Scripts\python.exe"
& $py -m pip install --quiet --upgrade pip
& $py -m pip install --quiet -r requirements.txt
Ok "python packages"

& $py -m pip install --quiet auto-editor
if ($LASTEXITCODE -eq 0) { Ok "auto-editor" } else { Miss "auto-editor - silence detection will be skipped" }

Write-Host "`nOptional, not installed by default:"
Write-Host "  WhisperX (transcription, captions, suggestions):"
Write-Host "      $py -m pip install whisperx        # large; pulls in torch"
Write-Host "  Ollama (chat beyond the built-in commands):  https://ollama.com`n"

if (-not (Test-Path ".env")) { Copy-Item ".env.example" ".env"; Ok "created .env" }
foreach ($d in @("INPUT","OUTPUT","projects","config",
                 "ASSETS\broll","ASSETS\music","ASSETS\images","ASSETS\fonts","ASSETS\logos")) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}
Ok "folders"
Write-Host "`nDone.  Start it with:  .\start.ps1"

# Start the AI Video Editor.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (Test-Path ".env") {
    Get-Content ".env" | Where-Object { $_ -match "^\s*[^#].*=" } | ForEach-Object {
        $k, $v = $_ -split "=", 2
        [Environment]::SetEnvironmentVariable($k.Trim(), $v.Trim(), "Process")
    }
}
$py = if (Test-Path ".\.venv\Scripts\python.exe") { ".\.venv\Scripts\python.exe" } else { "python" }
$h = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }
$p = if ($env:PORT) { $env:PORT } else { "8000" }
Write-Host "AI Video Editor  ->  http://${h}:${p}" -ForegroundColor Cyan
& $py -m uvicorn backend.main:app --host $h --port $p

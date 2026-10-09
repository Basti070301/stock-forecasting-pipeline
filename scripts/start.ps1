param([switch]$Dev)
$ErrorActionPreference = 'Stop'
$repositoryPath = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $repositoryPath
$pythonPath = Join-Path $repositoryPath '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw 'Zuerst die Python-Umgebung gemäß docs/LOCAL_SETUP.md installieren.' }
if (-not $Dev -and -not (Test-Path -LiteralPath (Join-Path $repositoryPath 'frontend\dist\index.html'))) { throw 'Zuerst in frontend: pnpm install; pnpm build' }
Write-Host 'Stock Intelligence AI: http://127.0.0.1:8000 (Strg+C beendet den Server)'
$serverArgs = @('-m', 'uvicorn', 'src.platform.api:app', '--host', '127.0.0.1', '--port', '8000')
if ($Dev) { $serverArgs += '--reload' }
& $pythonPath @serverArgs

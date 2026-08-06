# Cato Daemon Launcher
# Run this from PowerShell to start the Cato daemon in its own window
#
# CATO_VAULT_PASSWORD must be set in the environment before running this script.
# Example: $env:CATO_VAULT_PASSWORD = "your-strong-password-here"
# Do NOT hardcode the password in this file.
#
# Credentials: prefers %APPDATA%\cato\vault.enc; .env is fill-only.
# Migrate: python -m cato vault migrate-env
if (-not $env:CATO_VAULT_PASSWORD) {
    Write-Host "[CATO] ERROR: CATO_VAULT_PASSWORD environment variable is not set." -ForegroundColor Red
    Write-Host "[CATO] Set it first: `$env:CATO_VAULT_PASSWORD = 'your-strong-password'" -ForegroundColor Yellow
    exit 1
}
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RepoRoot

# Remove stale PID file
$pidFile = "$env:APPDATA\cato\cato.pid"
if (Test-Path $pidFile) { Remove-Item $pidFile -Force }

Write-Host "Starting Cato daemon from $RepoRoot ..."
# Use the shared runner so vault bootstrap + .env fill stay in one path.
python cato_svc_runner.py

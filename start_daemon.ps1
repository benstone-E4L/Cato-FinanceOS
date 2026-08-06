# CATO_VAULT_PASSWORD must be set in the environment before running this script.
# Example: $env:CATO_VAULT_PASSWORD = "your-strong-password-here"
# Do NOT hardcode the password in this file.
#
# Credentials: the Python runner prefers %APPDATA%\cato\vault.enc for
# TELEGRAM_BOT_TOKEN / OPENROUTER_API_KEY / etc. Plaintext .env only fills
# keys still missing. One-command migrate:
#   $env:CATO_VAULT_PASSWORD = '<password>'
#   python -m cato vault migrate-env
if (-not $env:CATO_VAULT_PASSWORD) {
    Write-Host "[CATO] ERROR: CATO_VAULT_PASSWORD environment variable is not set." -ForegroundColor Red
    Write-Host "[CATO] Set it first: `$env:CATO_VAULT_PASSWORD = 'your-strong-password'" -ForegroundColor Yellow
    exit 1
}
$RepoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Start-Process -FilePath python -ArgumentList 'cato_svc_runner.py' -WorkingDirectory $RepoRoot -WindowStyle Hidden
Write-Host "Daemon launched from $RepoRoot"

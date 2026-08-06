@echo off
REM CATO_VAULT_PASSWORD must be set in the environment before running this script.
REM Example: set CATO_VAULT_PASSWORD=your-strong-password
REM Do NOT hardcode the password in this file.
REM
REM Credentials: prefers %%APPDATA%%\cato\vault.enc; .env is fill-only.
REM Migrate: python -m cato vault migrate-env
if "%CATO_VAULT_PASSWORD%"=="" (
    echo [CATO] ERROR: CATO_VAULT_PASSWORD environment variable is not set.
    echo [CATO] Set it first: set CATO_VAULT_PASSWORD=your-strong-password
    exit /b 1
)
cd /d "%~dp0"
python cato_svc_runner.py

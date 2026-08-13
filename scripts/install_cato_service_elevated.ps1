# Run this from an ELEVATED PowerShell (Run as Administrator).
# Installs CatoDaemon as a Windows service: delayed-auto start, auto-restart
# on failure, depends on Tcpip, vault password stored only in the per-service
# registry Environment value (never in a command line, argument, or tracked file).

$ErrorActionPreference = "Stop"
$repo = "C:\Users\Work\Desktop\vault\projects\My Github\Cato"
Set-Location $repo

if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Error "Run this from an elevated (Administrator) PowerShell."
    exit 1
}

# Read CATO_VAULT_PASSWORD from .env without ever printing it.
$envLine = Get-Content "$repo\.env" | Where-Object { $_ -match '^CATO_VAULT_PASSWORD=' }
if (-not $envLine) { Write-Error "CATO_VAULT_PASSWORD not found in .env"; exit 1 }
$pw = $envLine -replace '^CATO_VAULT_PASSWORD=', ''
$env:CATO_VAULT_PASSWORD = $pw

python cato_service.py install
sc.exe config CatoDaemon start= delayed-auto
sc.exe config CatoDaemon depend= Tcpip
sc.exe failure CatoDaemon reset= 86400 actions= restart/5000/restart/5000/restart/30000

# Store the vault password ONLY in the per-service registry Environment value
# (HKLM, admin-only) — this is how SCM-launched processes receive it; it is
# not a tracked file and not a command-line argument.
New-ItemProperty -Path "HKLM:\SYSTEM\CurrentControlSet\Services\CatoDaemon" `
    -Name "Environment" -PropertyType MultiString `
    -Value @("CATO_VAULT_PASSWORD=$pw") -Force | Out-Null

Remove-Item Env:\CATO_VAULT_PASSWORD
$pw = $null

Write-Output "Installed. Stop the manually-running daemon first (python -m cato stop), then:"
Write-Output "  sc.exe start CatoDaemon"
Write-Output "Verify: curl http://127.0.0.1:8080/health"

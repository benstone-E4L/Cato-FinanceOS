# Cato's encrypted vault requires an operator-supplied unlock secret for each
# launch. A Windows service cannot prompt interactively, and persisting that
# master password in .env or the service registry defeats the vault boundary.
#
# This legacy installer therefore fails closed. Use Launch-CatoDesktop.ps1 (or
# a one-shot shell with CATO_VAULT_PASSWORD set only for that launch) until an
# OS credential-broker implementation exists.

$ErrorActionPreference = "Stop"

$regPath = "HKLM:\SYSTEM\CurrentControlSet\Services\CatoDaemon"
$hasPersistedSecret = $false
if (Test-Path -LiteralPath $regPath) {
    $serviceEnvironment = Get-ItemProperty `
        -LiteralPath $regPath `
        -Name Environment `
        -ErrorAction SilentlyContinue
    $hasPersistedSecret = $null -ne $serviceEnvironment.Environment
}

$message = @"
Cato service installation is disabled because SCM startup cannot securely
prompt for the encrypted-vault password. Use the desktop launcher instead.
"@
if ($hasPersistedSecret) {
    $message += @"

SECURITY ACTION REQUIRED: an older CatoDaemon installation still has a
persisted Environment value. From an elevated PowerShell, run:
  Remove-ItemProperty -LiteralPath '$regPath' -Name Environment
  Set-Service -Name CatoDaemon -StartupType Manual
Then rotate the Cato vault master password.
"@
}

Write-Error $message
exit 1

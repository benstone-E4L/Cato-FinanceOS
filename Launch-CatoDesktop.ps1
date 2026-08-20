$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$repoRoot = $PSScriptRoot
$releaseDir = Join-Path $repoRoot "desktop\src-tauri\target\release"
$desktopExe = Join-Path $releaseDir "cato-desktop.exe"
$manifestPath = Join-Path $releaseDir "cato-build-manifest.json"

if (-not (Test-Path -LiteralPath $desktopExe) -or -not (Test-Path -LiteralPath $manifestPath)) {
    throw "Cato's exact-HEAD desktop artifact is missing. Run desktop\build_release.ps1 first."
}

$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$expectedSha = [string]$manifest.source_sha
if ($expectedSha -notmatch "^[0-9a-f]{40}$") {
    throw "Cato's build custody manifest has an invalid source identity."
}

$dataDir = Join-Path $env:APPDATA "cato"
$portFile = Join-Path $dataDir "cato.port"
$matchingDaemon = $false
$mismatchedDaemon = $false
if (Test-Path -LiteralPath $portFile) {
    try {
        $port = [int](Get-Content -LiteralPath $portFile -Raw).Trim()
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:$port/health" -TimeoutSec 2
        if ([string]$health.source_sha -eq $expectedSha) {
            $matchingDaemon = $true
        } else {
            $mismatchedDaemon = $true
        }
    } catch {
        $matchingDaemon = $false
    }
}

if ($mismatchedDaemon) {
    throw "A different Cato daemon revision is already running. Stop the legacy daemon before launching this build."
}

if ($matchingDaemon) {
    Start-Process -FilePath $desktopExe -WorkingDirectory $releaseDir
    exit 0
}

$dpapiPasswordPath = Join-Path $dataDir "vault-password.dpapi"
if (Test-Path -LiteralPath $dpapiPasswordPath) {
    $protectedPassword = (Get-Content -LiteralPath $dpapiPasswordPath -Raw).Trim()
    $securePassword = ConvertTo-SecureString $protectedPassword
} else {
    $securePassword = Read-Host "Cato vault master password" -AsSecureString
}
$passwordPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($securePassword)
try {
    $env:CATO_VAULT_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordPointer)
    Start-Process -FilePath $desktopExe -WorkingDirectory $releaseDir
} finally {
    Remove-Item Env:\CATO_VAULT_PASSWORD -ErrorAction SilentlyContinue
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordPointer)
    $securePassword.Dispose()
}

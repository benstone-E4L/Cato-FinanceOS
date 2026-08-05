# Install night-shift flow, policy, and digest schedule into Cato app data.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$AppData = if ($env:APPDATA) { $env:APPDATA } else { $env:HOME }
$CatoDir = Join-Path $AppData "cato"
$FlowsDir = Join-Path $CatoDir "flows"
$SchedulesDir = Join-Path $CatoDir "schedules"
$ProofDir = Join-Path $RepoRoot "proof-artifacts"

New-Item -ItemType Directory -Force -Path $FlowsDir, $SchedulesDir, $ProofDir | Out-Null

Copy-Item -Force (Join-Path $RepoRoot "examples\flows\conduitscore-revenue-loop.yaml") $FlowsDir
Copy-Item -Force (Join-Path $RepoRoot "examples\schedules\night-shift-digest.yaml") $SchedulesDir
Copy-Item -Force (Join-Path $RepoRoot "docs\night-shift-policy.yaml") $CatoDir

Write-Host "Installed to $CatoDir"
Write-Host "  flows\conduitscore-revenue-loop.yaml"
Write-Host "  schedules\night-shift-digest.yaml"
Write-Host "  night-shift-policy.yaml"
Write-Host "Restart the Cato daemon to load new schedules."

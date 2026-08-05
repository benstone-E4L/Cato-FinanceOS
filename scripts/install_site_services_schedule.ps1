# Install site-services inbox + morning digest schedules into Cato app data.
$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$AppData = if ($env:APPDATA) { $env:APPDATA } else { $env:HOME }
$CatoDir = Join-Path $AppData "cato"
$SchedulesDir = Join-Path $CatoDir "schedules"

New-Item -ItemType Directory -Force -Path $SchedulesDir | Out-Null

Copy-Item -Force (Join-Path $RepoRoot "examples\schedules\site-services-inbox.yaml") $SchedulesDir
Copy-Item -Force (Join-Path $RepoRoot "examples\schedules\site-services-digest.yaml") $SchedulesDir

Write-Host "Installed site-services schedules to $SchedulesDir"
Write-Host "  site-services-inbox.yaml — every 30 min — skill site_services.pulse"
Write-Host "  site-services-digest.yaml — 7:00 daily — skill site_services.digest"
Write-Host "Run scripts\sync_site_services_vault.py first, then restart the Cato daemon."

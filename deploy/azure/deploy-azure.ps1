<#
.SYNOPSIS
  Deploy the Cato daemon to Azure Container Apps.

.DESCRIPTION
  Adds ONE more container app, `cato-orchestrator`, to the SAME existing
  rg-fin-financeos infrastructure the E4L FinanceOS Xero MCP servers and
  e4l-financeos-api already run in (fin-financeos-env / finfinanceosacr /
  fin-financeos-kv / id-fin-runtime). No new platform is created -- this
  mirrors ../../../E4L-FinanceOS/app/mcp-servers/xero-demo/deploy-azure.ps1's
  shape exactly.

  This makes Cato always-on: min-replicas is pinned to 1 (never scales to
  zero) so the webchat + MCP surface is reachable even when Ben's desktop is
  off. Genesis stays on Render, unchanged -- Cato-on-Azure calls it over
  plain HTTPS via genesis_endpoint in the container config, same as the
  desktop daemon does today.

.PARAMETER Stage
  preflight  read-only checks; changes nothing (default)
  secrets    report which Key Vault secrets are missing (never writes them)
  build      stage vault.enc + container-config.yaml, build + push to ACR,
             then remove the staged copies (never committed, never left on
             disk longer than the build needs them)
  deploy     create/update the one container app
  verify     hit /health and report container log guidance
  all        secrets-check -> build -> deploy -> verify

.NOTES
  Secrets are NEVER written by this script. It reports what is missing and
  prints the exact az command for Ben to run himself. Nothing here echoes a
  secret value. vault.enc is copied from Ben's own desktop data dir
  (%APPDATA%\cato\vault.enc) into a gitignored staging folder immediately
  before the image build and deleted immediately after -- it is ciphertext
  (AES, per cato/vault.py), not a plaintext credential file, but it is still
  treated as sensitive and never committed to git.
#>
[CmdletBinding()]
param(
  [ValidateSet('preflight','secrets','build','deploy','verify','all')]
  [string]$Stage = 'preflight',
  [string]$Subscription = 'd0b0ab6c-6cf0-48ec-9363-5643f6857f56',
  [string]$ResourceGroup = 'rg-fin-financeos',
  [string]$Environment   = 'fin-financeos-env',
  [string]$Registry      = 'finfinanceosacr',
  [string]$Vault         = 'fin-financeos-kv',
  [string]$Identity      = 'id-fin-runtime',
  [string]$Tag           = 'v1',
  [string]$LocalVaultEnc = "$env:APPDATA\cato\vault.enc"
)

$ErrorActionPreference = 'Stop'
$RepoRoot   = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)   # deploy/azure -> deploy -> repo root
$BuildCtx   = Join-Path $PSScriptRoot '.build-context'
$Image      = "$Registry.azurecr.io/cato-orchestrator:$Tag"
$App        = 'cato-orchestrator'
$VaultUrl   = "https://$Vault.vault.azure.net/"

function Say($m){ Write-Host $m }
function Head($m){ Write-Host ''; Write-Host ('=' * 72); Write-Host $m; Write-Host ('=' * 72) }

$script:AzExe = $null
function Get-AzExe {
  if ($script:AzExe) { return $script:AzExe }
  $cmd = Get-Command az -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
  if (-not $cmd) { throw "Azure CLI not found on PATH. Install it, then run 'az login'." }
  $script:AzExe = $cmd.Source
  return $script:AzExe
}

function Invoke-Az {
  param([Parameter(ValueFromRemainingArguments)] [string[]]$AzArgs)
  $exe = Get-AzExe
  $out = & $exe @AzArgs 2>&1
  if ($LASTEXITCODE -ne 0) { throw "az $($AzArgs -join ' ') failed:`n$out" }
  return $out | Where-Object { $_ -notmatch '^WARNING:' }
}

function Preflight {
  Head 'PREFLIGHT (read-only)'
  Invoke-Az account set --subscription $Subscription | Out-Null
  Say "subscription : $Subscription"

  $envJson = Invoke-Az containerapp env show -g $ResourceGroup -n $Environment --output json | ConvertFrom-Json
  Say "environment  : $($envJson.name) [$($envJson.location)] $($envJson.properties.provisioningState)"

  $acr = Invoke-Az acr show -g $ResourceGroup -n $Registry --output json | ConvertFrom-Json
  Say "registry     : $($acr.loginServer)"

  $mi = Invoke-Az identity show -g $ResourceGroup -n $Identity --output json | ConvertFrom-Json
  Say "identity     : $($mi.name) clientId=$($mi.clientId)"
  $script:IdentityId        = $mi.id
  $script:IdentityClientId  = $mi.clientId

  $kv = Invoke-Az keyvault show -n $Vault --output json | ConvertFrom-Json
  Say "key vault    : $($kv.name) rbacAuthorization=$($kv.properties.enableRbacAuthorization)"
  Say "  (id-fin-runtime already holds Key Vault Secrets Officer/User from the"
  Say "  existing apps' setup -- this script does not re-grant it.)"

  $existing = Invoke-Az containerapp list -g $ResourceGroup --query "[].name" --output tsv
  Say "existing apps: $(if ($existing) { $existing -join ', ' } else { '(none)' })"
  if ($existing -contains $App) { Say "  '$App' already exists -- deploy will UPDATE it." }

  if (Test-Path $LocalVaultEnc) { Say "local vault.enc found: $LocalVaultEnc" }
  else { Say "WARNING: local vault.enc NOT found at $LocalVaultEnc -- 'build' stage will fail." }
}

function CheckSecrets {
  Head 'KEY VAULT SECRETS (names only -- no value is read or printed)'
  $have = @(Invoke-Az keyvault secret list --vault-name $Vault --query "[].name" --output tsv)
  $need = @('cato-vault-password')
  $missing = @()
  foreach ($n in $need) {
    if ($have -contains $n) { Say "  present  $n" } else { Say "  MISSING  $n"; $missing += $n }
  }
  if (-not $missing) { Say "`nAll required secrets present."; return $true }

  Say "`n$($missing.Count) secret(s) missing. Ben loads this himself -- this"
  Say "script will not write a secret, and no agent handles this value."
  Say ''
  Say '  # Ben: put the CURRENT CATO_VAULT_PASSWORD value into Key Vault.'
  Say '  # Do NOT rotate it -- same value already unlocking vault.enc locally.'
  Say "  az keyvault secret set --vault-name $Vault --name cato-vault-password ``"
  Say '    --value "<current CATO_VAULT_PASSWORD value>" --output none'
  return $false
}

function BuildImage {
  Head "BUILD + PUSH  $Image"
  if (-not (Test-Path $LocalVaultEnc)) { throw "vault.enc not found at $LocalVaultEnc -- cannot build." }

  New-Item -ItemType Directory -Force -Path $BuildCtx | Out-Null
  try {
    Copy-Item $LocalVaultEnc (Join-Path $BuildCtx 'vault.enc') -Force
    Copy-Item (Join-Path $PSScriptRoot 'container-config.template.yaml') (Join-Path $BuildCtx 'container-config.yaml') -Force
    Say "staged vault.enc + container-config.yaml into $BuildCtx (gitignored)"

    Push-Location $RepoRoot
    try {
      Invoke-Az acr build --registry $Registry --image "cato-orchestrator:$Tag" `
        --file deploy/azure/Dockerfile . | Out-Host
    } finally { Pop-Location }
    Say "pushed $Image"
  } finally {
    Remove-Item -Recurse -Force $BuildCtx -ErrorAction SilentlyContinue
    Say "removed staged build context ($BuildCtx) -- vault.enc never committed, never left on disk."
  }
}

function Deploy {
  Head 'DEPLOY'
  if (-not $script:IdentityId) { Preflight }

  $exists = $false
  try { Invoke-Az containerapp show -g $ResourceGroup -n $App --output none; $exists = $true } catch { $exists = $false }

  # The Container Apps FQDN is deterministic (<app>.<environment default
  # domain>), so it's knowable before the app is created -- needed so the
  # daemon's Host-header allowlist (entrypoint.py -> CATO_CONTAINER_ALLOWED_HOST
  # -> cato/ui/server.py) can be set on first create, not just on update.
  $defaultDomain = Invoke-Az containerapp env show -g $ResourceGroup -n $Environment --query "properties.defaultDomain" --output tsv
  $expectedFqdn = "$App.$defaultDomain"

  $envVars = @(
    "CATO_KEYVAULT_URL=$VaultUrl",
    "AZURE_CLIENT_ID=$script:IdentityClientId",
    "CATO_VAULT_PASSWORD_SECRET_NAME=cato-vault-password",
    "CATO_INGRESS_FQDN=$expectedFqdn",
    "PORT=8080"
  )

  if ($exists) {
    Say "updating $App"
    Invoke-Az containerapp update -g $ResourceGroup -n $App --image $Image --set-env-vars @envVars | Out-Null
  } else {
    Say "creating $App"
    Invoke-Az containerapp create -g $ResourceGroup -n $App `
      --environment $Environment --image $Image `
      --registry-server "$Registry.azurecr.io" --registry-identity $script:IdentityId `
      --user-assigned $script:IdentityId `
      --ingress external --target-port 8080 --transport http `
      --min-replicas 1 --max-replicas 1 `
      --cpu 0.5 --memory 1.0Gi `
      --env-vars @envVars | Out-Null
  }

  # Always-on per Ben's explicit ask -- not scale-to-zero, re-asserted every run.
  Invoke-Az containerapp update -g $ResourceGroup -n $App --min-replicas 1 --max-replicas 1 | Out-Null

  $fqdn = Invoke-Az containerapp show -g $ResourceGroup -n $App --query "properties.configuration.ingress.fqdn" --output tsv
  Say "  https://$fqdn/  (webchat)"
  Say "  https://$fqdn/mcp  (MCP, proxied through the same aiohttp server)"
  $script:Fqdn = $fqdn
}

function Verify {
  Head 'VERIFY'
  if (-not $script:Fqdn) {
    $script:Fqdn = Invoke-Az containerapp show -g $ResourceGroup -n $App --query "properties.configuration.ingress.fqdn" --output tsv
  }
  Say ''
  Say "--- $App  https://$($script:Fqdn)/"

  $health = (Invoke-WebRequest -Uri "https://$($script:Fqdn)/health" -SkipHttpErrorCheck)
  Say "  /health -> $($health.StatusCode)   expect 200"
  if ($health.StatusCode -eq 200) { Say "  body: $($health.Content)" }

  Say ''
  Say 'If /health did not return 200, check startup logs -- the most likely'
  Say 'failure mode is the entrypoint refusing to start because'
  Say 'CATO_KEYVAULT_URL/AZURE_CLIENT_ID are unset or the cato-vault-password'
  Say 'secret is missing/empty (fail-closed by design, see entrypoint.py):'
  Say "  az containerapp logs show -g $ResourceGroup -n $App --tail 50"
}

switch ($Stage) {
  'preflight' { Preflight }
  'secrets'   { Preflight; CheckSecrets | Out-Null }
  'build'     { BuildImage }
  'deploy'    { Preflight; Deploy }
  'verify'    { Verify }
  'all'       {
    Preflight
    if (-not (CheckSecrets)) { Say "`nSTOPPING: load the missing secret first, then re-run."; break }
    BuildImage; Deploy; Verify
  }
}

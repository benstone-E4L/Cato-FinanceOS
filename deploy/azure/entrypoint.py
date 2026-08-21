#!/usr/bin/env python3
"""Azure Container Apps entrypoint for the Cato daemon.

Fetches CATO_VAULT_PASSWORD from Azure Key Vault via the container's
user-assigned managed identity (AZURE_CLIENT_ID must be set to the identity's
client id -- azure.identity.DefaultAzureCredential picks it up automatically),
then execs `cato start`. This never logs, prints, or writes the secret value
anywhere -- it lives only in the process environment of the exec'd `cato`
process, same as it already does on the local desktop daemon.

Required env vars (set by deploy-azure.ps1's Deploy stage):
  CATO_KEYVAULT_URL            e.g. https://fin-financeos-kv.vault.azure.net/
  AZURE_CLIENT_ID              id-fin-runtime's clientId (user-assigned MI)
Optional:
  CATO_VAULT_PASSWORD_SECRET_NAME   defaults to "cato-vault-password"
  CATO_VAULT_PASSWORD               if already set (e.g. local test run),
                                     the Key Vault fetch is skipped entirely.
"""
import os
import sys


def _fetch_vault_password() -> str:
    vault_url = os.environ.get("CATO_KEYVAULT_URL")
    secret_name = os.environ.get("CATO_VAULT_PASSWORD_SECRET_NAME", "cato-vault-password")
    if not vault_url:
        print(
            "FATAL: CATO_KEYVAULT_URL is not set -- cannot fetch CATO_VAULT_PASSWORD "
            "from Key Vault. Refusing to start (fail closed).",
            file=sys.stderr,
        )
        sys.exit(1)
    try:
        from azure.identity import DefaultAzureCredential
        from azure.keyvault.secrets import SecretClient
    except ImportError:
        print("FATAL: azure-identity/azure-keyvault-secrets not installed.", file=sys.stderr)
        sys.exit(1)

    try:
        client = SecretClient(vault_url=vault_url, credential=DefaultAzureCredential())
        secret = client.get_secret(secret_name)
    except Exception as exc:  # noqa: BLE001 -- fail closed, never leak the exception's args if they echo input
        print(
            f"FATAL: could not read secret '{secret_name}' from {vault_url}: {type(exc).__name__}. "
            "Refusing to start (fail closed).",
            file=sys.stderr,
        )
        sys.exit(1)
    if not secret.value:
        print(f"FATAL: secret '{secret_name}' exists but is empty.", file=sys.stderr)
        sys.exit(1)
    return secret.value


def main() -> None:
    if "CATO_VAULT_PASSWORD" not in os.environ:
        os.environ["CATO_VAULT_PASSWORD"] = _fetch_vault_password()
    print("CATO_VAULT_PASSWORD resolved (value not logged). Starting daemon...")
    os.execvp("cato", ["cato", "start", "--channel", "webchat"])


if __name__ == "__main__":
    main()

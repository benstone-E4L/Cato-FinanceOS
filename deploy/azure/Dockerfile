# Cato daemon -- Azure Container Apps image.
#
# Sibling deployment unit to ../../../E4L-FinanceOS/app/mcp-servers/xero{,-demo}
# and e4l-financeos-api: same rg-fin-financeos / fin-financeos-env /
# finfinanceosacr / id-fin-runtime infrastructure, built via
# `az acr build --file deploy/azure/Dockerfile .` from the REPO ROOT (context
# must be the repo root so `cato/` and `pyproject.toml` are reachable).
#
# Build context is assembled by deploy-azure.ps1's Build stage, which stages
# an ENCRYPTED vault.enc and a container-appropriate config.yaml into
# deploy/azure/.build-context/ (gitignored, never committed) immediately
# before the build and removes it after. Nothing in this Dockerfile reads,
# prints, or bakes in a plaintext secret -- CATO_VAULT_PASSWORD is fetched at
# container startup from Key Vault (see entrypoint.py), not at build time.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PORT=8080

WORKDIR /build
COPY pyproject.toml README.md ./
COPY cato/ ./cato/
RUN pip install --no-cache-dir . azure-identity==1.19.0 azure-keyvault-secrets==4.9.0

# Non-root operator user. HOME must be set so cato.platform.get_data_dir()
# resolves ~/.cato correctly (POSIX branch: Path.home() / ".cato").
RUN useradd --create-home --uid 10001 appuser
USER appuser
WORKDIR /home/appuser
ENV HOME=/home/appuser

RUN mkdir -p /home/appuser/.cato

# Staged by deploy-azure.ps1's Build stage -- see .build-context note above.
COPY --chown=appuser:appuser deploy/azure/.build-context/container-config.yaml /home/appuser/.cato/config.yaml
COPY --chown=appuser:appuser deploy/azure/.build-context/vault.enc /home/appuser/.cato/vault.enc
COPY --chown=appuser:appuser deploy/azure/entrypoint.py /home/appuser/entrypoint.py

EXPOSE 8080

CMD ["python", "/home/appuser/entrypoint.py"]

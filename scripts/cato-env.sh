#!/usr/bin/env bash
# cato-env.sh -- source this (do NOT execute it) before running any real `cato`
# command that needs the encrypted vault or Phoenix tracing.
#
#   source scripts/cato-env.sh && python -m cato.cli vault list
#
# WHY THIS EXISTS
# ---------------
# `cato/vault.py` reads CATO_VAULT_PASSWORD from the OS environment ONLY. It
# deliberately does not auto-load `.env` (see vault_bootstrap.py's docstring:
# dotenv parsing there is one-shot-migration-only). A subprocess launched
# without the variable exported fails with "Wrong master password or corrupted
# vault." -- which looks like a bad password but is actually an unset variable.
# That misdiagnosis cost a full session on 2026-08-21; this script is the fix.
#
# `cato/core/phoenix_tracing.py` reads PHOENIX_COLLECTOR_ENDPOINT (and the
# aliases PHOENIX_ENDPOINT / OTEL_EXPORTER_OTLP_ENDPOINT) from the environment,
# but resolves PHOENIX_API_KEY from the ENCRYPTED VAULT only -- so the key must
# already be stored via `python -m cato.cli vault set PHOENIX_API_KEY`, not
# exported here.
#
# RULES
# -----
# * Never echo, log, or commit any value this script reads.
# * Never edit or delete either .env file it reads from; read-only, always.

_cato_repo="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
_genesis_env="${GENESIS_AGENTS_ENV:-$HOME/Desktop/vault/projects/My Github/Genesis Agents/.env}"

# --- vault master password (from Cato's own .env, read-only) -----------------
if [ -f "$_cato_repo/.env" ]; then
  CATO_VAULT_PASSWORD="$(grep -m1 '^CATO_VAULT_PASSWORD=' "$_cato_repo/.env" | cut -d= -f2- | tr -d '\r')"
  export CATO_VAULT_PASSWORD
fi

# --- Phoenix collector endpoint (from Genesis Agents' .env, read-only) -------
if [ -f "$_genesis_env" ]; then
  PHOENIX_COLLECTOR_ENDPOINT="$(grep -m1 '^PHOENIX_COLLECTOR_ENDPOINT=' "$_genesis_env" | cut -d= -f2- | tr -d '\r')"
  export PHOENIX_COLLECTOR_ENDPOINT
fi
export PHOENIX_PROJECT_NAME="${PHOENIX_PROJECT_NAME:-cato}"
export PHOENIX_TRACING="${PHOENIX_TRACING:-1}"

# Content tracing stays OFF by default: the collector is off-box
# (app.phoenix.arize.com), and phoenix_tracing.content_tracing_enabled()
# requires BOTH PHOENIX_TRACE_CONTENT and PHOENIX_ALLOW_CONTENT_OFFBOX before
# any prompt/tool text leaves this machine. Do not enable casually.

# Presence-only report -- never the values.
printf 'cato-env: CATO_VAULT_PASSWORD=%s PHOENIX_COLLECTOR_ENDPOINT=%s PHOENIX_PROJECT_NAME=%s\n' \
  "${CATO_VAULT_PASSWORD:+set}${CATO_VAULT_PASSWORD:-MISSING}" \
  "${PHOENIX_COLLECTOR_ENDPOINT:+set}${PHOENIX_COLLECTOR_ENDPOINT:-MISSING}" \
  "$PHOENIX_PROJECT_NAME"

unset _cato_repo _genesis_env

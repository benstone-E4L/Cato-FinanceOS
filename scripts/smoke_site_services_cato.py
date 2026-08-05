#!/usr/bin/env python3
"""
Live smoke test: Cato vault -> production site-services /api/cato/*.

Usage:
  set CATO_VAULT_PASSWORD=<password>
  python scripts/smoke_site_services_cato.py
  python scripts/smoke_site_services_cato.py --base-url https://swarmsync-site-services.vercel.app

Exits 0 when all checks pass; never prints secrets.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cato.platform import get_data_dir
from cato.vault import Vault
from cato.tools.site_services_bridge import (
    fetch_audit_summary,
    fetch_inbox,
    fetch_stuck,
    resolve_site_services_config,
)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="", help="Override SITE_SERVICES_BASE_URL")
    args = parser.parse_args()

    vault_path = get_data_dir() / "vault.enc"
    if not vault_path.is_file():
        print("FAIL vault_missing")
        return 1

    vault = Vault(vault_path=vault_path)
    if args.base_url:
        vault.set("SITE_SERVICES_BASE_URL", args.base_url.rstrip("/"))

    base, secret, err = resolve_site_services_config(vault)
    if err:
        print(f"FAIL config: {err}")
        return 1

    print(f"OK config base={base}")

    inbox = await fetch_inbox(vault)
    print(f"{'OK' if inbox.get('ok') else 'FAIL'} inbox count={inbox.get('count')} err={inbox.get('error')}")

    stuck = await fetch_stuck(vault)
    print(f"{'OK' if stuck.get('ok') else 'FAIL'} stuck count={stuck.get('count')} err={stuck.get('error')}")

    audit = await fetch_audit_summary(vault, since="24h")
    print(f"{'OK' if audit.get('ok') else 'FAIL'} audit err={audit.get('error')}")

    ok = inbox.get("ok") and stuck.get("ok") and audit.get("ok")
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

"""One-shot: copy outreach .env keys into Cato vault (no values printed)."""
from __future__ import annotations

import sys
from pathlib import Path

# Repo root on path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cato.core.outreach_credentials import OUTREACH_VAULT_KEYS, default_outreach_engine_root
from cato.platform import get_data_dir
from cato.vault import Vault


def _parse_dotenv(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip().strip('"').strip("'")
    return out


def main() -> int:
    root = default_outreach_engine_root()
    env_file = (root / ".env") if root else None
    if not env_file or not env_file.is_file():
        print("no_outreach_env")
        return 1
    env = _parse_dotenv(env_file)
    vault_path = get_data_dir() / "vault.enc"
    if not vault_path.is_file():
        print("vault_missing — run cato init first")
        return 1
    vault = Vault(vault_path=vault_path)
    synced: list[str] = []
    for key in OUTREACH_VAULT_KEYS:
        val = (env.get(key) or "").strip()
        if val and not vault.get(key):
            vault.set(key, val)
            synced.append(key)
    print("synced:", ",".join(synced) if synced else "none")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

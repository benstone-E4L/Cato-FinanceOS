"""Copy SwarmSync-Arbitrage-SiteServices .env secrets into Cato vault (values never printed)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cato.platform import get_data_dir
from cato.vault import Vault

DEFAULT_SITE_SERVICES_ENV = Path(
    r"C:\Users\Administrator\Desktop\Github\SwarmSync-Arbitrage-SiteServices\.env"
)
DEFAULT_BASE_URL = "https://swarmsync-site-services.vercel.app"


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
    env_path = DEFAULT_SITE_SERVICES_ENV
    if len(sys.argv) > 1:
        env_path = Path(sys.argv[1]).expanduser().resolve()

    if not env_path.is_file():
        print(f"missing_site_services_env: {env_path}")
        return 1

    vault_path = get_data_dir() / "vault.enc"
    if not vault_path.is_file():
        print("vault_missing — run cato init first")
        return 1

    env = _parse_dotenv(env_path)
    vault = Vault(vault_path=vault_path)
    stored: list[str] = []

    internal = (env.get("INTERNAL_SECRET") or "").strip()
    if internal:
        vault.set("SITE_SERVICES_INTERNAL_SECRET", internal)
        stored.append("SITE_SERVICES_INTERNAL_SECRET")

    def _pick_base_url() -> str:
        for key in ("SITE_SERVICES_BASE_URL", "APP_BASE_URL"):
            val = (env.get(key) or "").strip().rstrip("/")
            if not val:
                continue
            if "bens-projects-4026.vercel.app" in val:
                continue
            return val
        return DEFAULT_BASE_URL

    base_url = _pick_base_url()
    vault.set("SITE_SERVICES_BASE_URL", base_url.rstrip("/"))
    stored.append("SITE_SERVICES_BASE_URL")

    print("stored:", ",".join(stored))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Outreach credential isolation and status redaction."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4


def test_outreach_child_environment_never_contains_credentials(tmp_path: Path) -> None:
    from cato.core import outreach_credentials as oc

    secret_value = uuid4().hex
    env = oc.build_outreach_env(
        engine_root=tmp_path,
        base={
            "PATH": str(tmp_path),
            "BREVO_SMTP_KEY": secret_value,
            "CONDUITSCORE_API_KEY": secret_value,
            "CATO_VAULT_PASSWORD": secret_value,
        },
    )

    assert env.get("PATH") == str(tmp_path)
    assert secret_value not in env.values()
    assert set(env).isdisjoint(
        {"BREVO_SMTP_KEY", "CONDUITSCORE_API_KEY", "CATO_VAULT_PASSWORD"}
    )


def test_status_reports_vault_presence_without_returning_values(
    tmp_path: Path, monkeypatch
) -> None:
    from cato.core import outreach_credentials as oc
    import cato.vault as vault_mod

    secret_value = uuid4().hex

    class FakeVault:
        def get(self, key: str):
            return secret_value if key == "BREVO_SMTP_KEY" else None

    monkeypatch.setattr(vault_mod, "Vault", FakeVault)

    st = oc.outreach_credentials_status(engine_root=tmp_path)
    blob = json.dumps(st)
    assert secret_value not in blob
    assert st["keys_configured"]["BREVO_SMTP_KEY"] is True
    assert st["execution_available"] is False

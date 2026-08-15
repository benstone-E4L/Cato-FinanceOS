"""Outreach credential isolation and status redaction."""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest


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
    import cato.vault as vault_mod
    from cato.core import outreach_credentials as oc

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


def test_build_credential_envelope_reads_vault_and_never_environment(
    monkeypatch,
) -> None:
    from cato.core import outreach_credentials as oc

    canary = uuid4().hex
    env_noise = uuid4().hex
    monkeypatch.setenv("CONDUITSCORE_API_KEY", env_noise)

    class FakeVault:
        def get(self, key: str):
            return canary if key == "CONDUITSCORE_API_KEY" else None

    payload, values = oc.build_credential_envelope(vault=FakeVault())
    decoded = json.loads(payload)

    assert decoded["protocol"] == oc.OUTREACH_CREDENTIAL_PROTOCOL
    assert decoded["version"] == oc.OUTREACH_CREDENTIAL_VERSION
    assert decoded["credentials"] == {"CONDUITSCORE_API_KEY": canary}
    assert values == (canary,)
    assert env_noise.encode("utf-8") not in payload


def test_build_credential_envelope_fails_closed_when_required_key_missing() -> None:
    from cato.core import outreach_credentials as oc

    class EmptyVault:
        def get(self, key: str):
            return None

    with pytest.raises(oc.OutreachCredentialError, match="required vault credentials"):
        oc.build_credential_envelope(vault=EmptyVault())


def test_build_credential_envelope_fails_closed_when_vault_is_locked() -> None:
    from cato.core import outreach_credentials as oc

    class LockedVault:
        def get(self, key: str):
            raise RuntimeError("locked")

    with pytest.raises(oc.OutreachCredentialError, match="locked or unavailable"):
        oc.build_credential_envelope(vault=LockedVault())


@pytest.mark.parametrize("value", ["", "   ", 123, {"nested": "value"}])
def test_build_credential_envelope_rejects_malformed_vault_values(value) -> None:
    from cato.core import outreach_credentials as oc

    class BadVault:
        def get(self, key: str):
            return value if key == "CONDUITSCORE_API_KEY" else None

    with pytest.raises(oc.OutreachCredentialError, match="invalid vault credential"):
        oc.build_credential_envelope(vault=BadVault())

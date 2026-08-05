"""Outreach credential merge and status redaction."""

from __future__ import annotations

import json
from pathlib import Path
import pytest


@pytest.fixture
def outreach_env_files(tmp_path: Path, monkeypatch) -> Path:
    engine = tmp_path / "engine"
    engine.mkdir()
    (engine / ".env").write_text(
        "CONDUITSCORE_API_BASE=https://from-env.example\n"
        "BREVO_SMTP_KEY=env-secret-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BREVO_SMTP_KEY", "")
    monkeypatch.delenv("CONDUITSCORE_API_BASE", raising=False)
    return engine


def test_vault_overrides_dotenv(outreach_env_files: Path, monkeypatch) -> None:
    from cato.core import outreach_credentials as oc

    monkeypatch.setattr(
        oc,
        "_vault_secrets",
        lambda: {
            "BREVO_SMTP_KEY": "vault-secret",
            "CONDUITSCORE_API_BASE": "https://vault.example",
        },
    )

    env = oc.build_outreach_env(engine_root=outreach_env_files, base={})
    assert env["BREVO_SMTP_KEY"] == "vault-secret"
    assert env["CONDUITSCORE_API_BASE"] == "https://vault.example"


def test_status_never_prints_secrets(outreach_env_files: Path, monkeypatch) -> None:
    from cato.core import outreach_credentials as oc

    monkeypatch.setattr(
        oc,
        "_vault_secrets",
        lambda: {"BREVO_SMTP_KEY": "super-secret-value"},
    )
    monkeypatch.setattr(
        oc,
        "default_outreach_engine_root",
        lambda: outreach_env_files,
    )

    st = oc.outreach_credentials_status(engine_root=outreach_env_files)
    blob = json.dumps(st)
    assert "super-secret-value" not in blob
    assert st["keys_configured"]["BREVO_SMTP_KEY"] is True

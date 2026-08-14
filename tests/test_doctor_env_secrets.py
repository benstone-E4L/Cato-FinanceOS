"""
Regression test for CHUNK_2_VAULT: `cato doctor` must report live operator
secrets still sitting in plaintext .env, and must report clean once they are
gone (migrated into vault.enc, per cato/vault_bootstrap.py's migrate-env
path). No secret value is ever asserted against or printed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cato.doctor import DoctorReport


def _make_report() -> DoctorReport:
    report = DoctorReport()
    return report


def test_env_secrets_flagged_when_live(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "ANTHROPIC_API_KEY=sk-ant-not-a-real-key\n"
        "GMAIL_ADDRESS=someone@example.com\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "cato.vault_bootstrap.resolve_repo_root", lambda *a, **k: tmp_path
    )

    report = _make_report()
    report._check_env_secrets()

    problems = [p for p, _fix in report._failures]
    assert any("Repository .env" in p for p in problems), problems


def test_env_secrets_clean_when_only_nonsecret_config_remains(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GMAIL_ADDRESS=someone@example.com\n"
        "TELEGRAM_CHAT_ID=12345\n"
        "CATODESKTOP_BOT_USERNAME=cato_bot\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "cato.vault_bootstrap.resolve_repo_root", lambda *a, **k: tmp_path
    )

    report = _make_report()
    report._check_env_secrets()

    assert any("Repository .env" in problem for problem, _ in report._failures)


def test_env_secrets_clean_when_env_file_absent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "cato.vault_bootstrap.resolve_repo_root", lambda *a, **k: tmp_path
    )

    report = _make_report()
    report._check_env_secrets()

    assert report._failures == []


def test_doctor_surfaces_nonempty_legacy_state_without_mutating_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / ".cato"
    skill = legacy / "skills" / "existing-skill"
    skill.mkdir(parents=True)
    marker = skill / "SKILL.md"
    marker.write_text("legacy", encoding="utf-8")
    inventory = ({
        "root": str(legacy),
        "present": ("skills",),
        "counts": {"skills": 1},
    },)
    monkeypatch.setattr("cato.doctor.get_legacy_data_inventory", lambda: inventory)

    report = _make_report()
    report._check_legacy_data()

    assert any("Legacy Cato data" in problem for problem, _ in report._failures)
    assert marker.read_text(encoding="utf-8") == "legacy"

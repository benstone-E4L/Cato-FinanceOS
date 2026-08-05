"""audit_log._sanitize_inputs used to inspect only TOP-LEVEL dict keys.

So `{"headers": {"authorization": "Bearer ..."}}` was written to the audit
table verbatim — the credential sat one level down and the scan never looked.
It now delegates to `cato.audit.ledger.redact`, which walks the whole structure
and also scrubs secret-shaped substrings out of free text.
"""

from __future__ import annotations

import json

import pytest

from cato.audit.audit_log import AuditLog, _sanitize_inputs


@pytest.fixture()
def log(tmp_path):
    audit = AuditLog(db_path=tmp_path / "audit.db")
    audit.connect()
    yield audit
    audit.close()


NESTED = {
    "url": "https://api.example.com/v1/send",
    "headers": {"authorization": "Bearer sk-live-NESTED-LEAK-0123456789abcdef"},
    "auth": {
        "oauth": {
            "deep": {"refresh_token": "ya29.NESTED-REFRESH-TOKEN-abcdef123456"},
        },
    },
    "retries": [
        {"attempt": 1, "password": "hunter2-NESTED"},
        {"attempt": 2, "note": "use ghp_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB to auth"},
    ],
}

LEAKS = (
    "NESTED-LEAK",
    "NESTED-REFRESH-TOKEN",
    "hunter2-NESTED",
    "ghp_BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB",
)


def test_nested_credentials_are_redacted():
    clean = json.dumps(_sanitize_inputs(NESTED))
    for leak in LEAKS:
        assert leak not in clean, f"{leak!r} survived sanitisation"


def test_nested_credentials_never_reach_the_database(log):
    """The end-to-end contract: nothing readable lands in the audit row."""
    log.log(
        session_id="sess-1",
        action_type="tool_call",
        tool_name="http.post",
        inputs=NESTED,
        outputs={"status": 200},
    )
    rows = log.get_session_rows("sess-1")
    assert len(rows) == 1
    stored = rows[0]["inputs_json"]
    for leak in LEAKS:
        assert leak not in stored, f"{leak!r} persisted to the audit table"
    assert "redacted" in stored.lower()


def test_non_sensitive_nested_data_is_preserved(log):
    """Redaction must stay useful — an audit row of all [redacted] proves nothing."""
    clean = _sanitize_inputs(
        {"url": "https://example.com", "opts": {"timeout": 30, "retries": 3}}
    )
    assert clean["url"] == "https://example.com"
    assert clean["opts"]["timeout"] == 30
    assert clean["opts"]["retries"] == 3


def test_top_level_redaction_still_works(log):
    clean = _sanitize_inputs({"api_key": "sk-live-TOPLEVEL-0123456789", "q": "hello"})
    assert "TOPLEVEL" not in json.dumps(clean)
    assert clean["q"] == "hello"


def test_list_of_secrets_is_redacted():
    clean = json.dumps(_sanitize_inputs({"tokens": ["sk-live-AAAAAAAAAAAAAAAA", "plain"]}))
    assert "sk-live-AAAAAAAAAAAAAAAA" not in clean


def test_non_dict_input_yields_an_empty_dict():
    assert _sanitize_inputs("just a string") == {}  # type: ignore[arg-type]
    assert _sanitize_inputs(None) == {}  # type: ignore[arg-type]
    assert _sanitize_inputs([1, 2, 3]) == {}  # type: ignore[arg-type]


def test_deeply_nested_payload_does_not_crash(log):
    """Beyond the walker's depth limit the row must still be a usable dict."""
    payload: dict = {"password": "deep-secret-value"}
    for _ in range(40):
        payload = {"nest": payload}
    clean = _sanitize_inputs(payload)
    assert isinstance(clean, dict)
    assert "deep-secret-value" not in json.dumps(clean)


def test_hash_chain_still_verifies_after_redaction(log):
    for i in range(3):
        log.log(
            session_id="sess-chain",
            action_type="tool_call",
            tool_name="http.post",
            inputs={**NESTED, "seq": i},
            outputs={"status": 200},
        )
    assert log.verify_chain("sess-chain") is True

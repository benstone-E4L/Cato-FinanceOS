"""Tests for canary-25 operator kit."""

from __future__ import annotations

from pathlib import Path

import pytest

from cato.canary25.contacts import ContactRow, detect_format, load_contacts_csv
from cato.canary25.manifest import build_manifest, evaluate_pass, load_manifest, save_manifest
from cato.canary25.select import dedupe_by_domain, select_batch
from cato.canary25.tracking import merge_tracking_into_manifest
from cato.core.night_shift_policy import NightShiftPolicy


def _validated_csv(tmp_path: Path, rows: list[dict]) -> Path:
    import csv

    p = tmp_path / "pool.csv"
    fields = ["domain", "receiver_email", "email", "notes", "scrape_source"]
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return p


def test_detect_format_validated() -> None:
    assert detect_format(["domain", "receiver_email", "notes"]) == "validated"


def test_detect_format_clay() -> None:
    assert detect_format(["Work Email", "Website", "Company"]) == "clay"


def test_load_validated_csv_skips_invalid(tmp_path: Path) -> None:
    p = _validated_csv(
        tmp_path,
        [
            {
                "domain": "good.com",
                "receiver_email": "a@good.com",
                "email": "a@good.com",
                "notes": "score=100; band=tier_a",
                "scrape_source": "test",
            },
            {
                "domain": "conduitscore.com",
                "receiver_email": "x@conduitscore.com",
                "email": "x@conduitscore.com",
                "notes": "",
                "scrape_source": "test",
            },
            {
                "domain": "",
                "receiver_email": "bad",
                "email": "bad",
                "notes": "",
                "scrape_source": "",
            },
        ],
    )
    rows, warnings, meta = load_contacts_csv(p)
    assert len(rows) == 1
    assert rows[0].tier == "tier_a"
    assert rows[0].score == 100
    assert meta["format"] == "validated"
    assert len(warnings) >= 2


def test_load_clay_export(tmp_path: Path) -> None:
    import csv

    p = tmp_path / "clay.csv"
    with p.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(
            fh,
            fieldnames=["Work Email", "Website", "First Name", "Company Name"],
        )
        w.writeheader()
        w.writerow({
            "Work Email": "ceo@acme.io",
            "Website": "https://www.acme.io/about",
            "First Name": "Sam",
            "Company Name": "Acme",
        })
    rows, _, meta = load_contacts_csv(p, format_hint="clay")
    assert len(rows) == 1
    assert rows[0].domain == "acme.io"
    assert rows[0].receiver_email == "ceo@acme.io"
    assert meta["format"] == "clay"


def test_dedupe_keeps_best_tier(tmp_path: Path) -> None:
    rows = [
        ContactRow("dup.com", "b@dup.com", tier="tier_c", score=50),
        ContactRow("dup.com", "a@dup.com", tier="tier_a", score=90),
    ]
    out = dedupe_by_domain(rows)
    assert len(out) == 1
    assert out[0].receiver_email == "a@dup.com"


def test_select_batch_count_and_seed(tmp_path: Path) -> None:
    pool = [
        ContactRow(f"d{i}.com", f"u{i}@d{i}.com", tier="tier_a", score=100 - i)
        for i in range(40)
    ]
    a, _ = select_batch(pool, count=25, seed=42)
    b, _ = select_batch(pool, count=25, seed=42)
    c, _ = select_batch(pool, count=25, seed=99)
    assert len(a) == 25
    assert [x.contact_id for x in a] == [x.contact_id for x in b]
    assert [x.contact_id for x in a] != [x.contact_id for x in c]


def test_manifest_roundtrip_and_pass_eval(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        "cato.canary25.paths.default_canary_dir",
        lambda: tmp_path,
    )
    selected = [
        ContactRow("one.com", "a@one.com", tier="tier_a"),
        ContactRow("two.com", "b@two.com", tier="tier_b"),
    ]
    manifest = build_manifest(
        selected,
        source_file="/tmp/pool.csv",
        selection_meta={"pool_unique_domains": 2},
        batch_id="test-batch",
    )
    path = save_manifest(manifest)
    loaded = load_manifest(path)
    assert loaded["batch_id"] == "test-batch"
    assert loaded["g1_safety"]["live_outreach_via_cato"] is False
    assert len(loaded["contacts"]) == 2

    loaded["contacts"][0]["send_status"] = "sent"
    loaded["contacts"][0]["reply"] = True
    loaded["contacts"][1]["send_status"] = "sent"
    from cato.canary25.manifest import recompute_tracking_totals

    recompute_tracking_totals(loaded)
    ev = evaluate_pass(loaded)
    assert ev["checks"]["engagement_ok"] is True
    assert ev["checks"]["complaint_rate_ok"] is True
    assert ev["checks"]["sent_complete"] is True
    assert ev["row4_pass"] is True


def test_record_requires_contact_id(tmp_path: Path) -> None:
    from click.testing import CliRunner
    from cato.cli import main

    from cato.canary25.manifest import build_manifest, save_manifest
    from cato.canary25.contacts import ContactRow

    out = tmp_path / "canary"
    out.mkdir()
    manifest = build_manifest(
        [ContactRow("a.com", "a@a.com")],
        source_file="pool.csv",
        selection_meta={"pool_unique_domains": 1},
    )
    save_manifest(manifest, out / "manifest.json")

    r = CliRunner().invoke(
        main,
        ["canary", "record", "--reply", "--manifest", str(out / "manifest.json")],
    )
    assert r.exit_code != 0
    assert "--contact" in r.output.lower() or "contact" in r.output.lower()


def test_record_per_contact_updates_tracking(tmp_path: Path) -> None:
    from click.testing import CliRunner
    from cato.cli import main

    from cato.canary25.manifest import build_manifest, load_manifest, save_manifest
    from cato.canary25.contacts import ContactRow

    out = tmp_path / "canary"
    out.mkdir()
    save_manifest(
        build_manifest(
            [ContactRow("a.com", "a@a.com")],
            source_file="pool.csv",
            selection_meta={"pool_unique_domains": 1},
        ),
        out / "manifest.json",
    )

    r = CliRunner().invoke(
        main,
        [
            "canary",
            "record",
            "--contact",
            "a.com",
            "--reply",
            "--manifest",
            str(out / "manifest.json"),
            "--no-sync-csv",
        ],
    )
    assert r.exit_code == 0, r.output
    loaded = load_manifest(out / "manifest.json")
    assert loaded["tracking"]["replies"] == 1


def test_tracking_csv_merge(tmp_path: Path) -> None:
    manifest = {
        "contacts": [
            {
                "contact_id": "acme.io",
                "domain": "acme.io",
                "receiver_email": "ceo@acme.io",
                "tier": "",
                "score": 0,
                "send_status": "pending",
                "approved_at": "",
                "sent_at": "",
                "reply": False,
                "audit_view": False,
                "complaint": False,
                "bounce": False,
                "operator_notes": "",
            }
        ],
        "tracking": {},
    }
    csv_path = tmp_path / "tracking-sheet.csv"
    csv_path.write_text(
        "contact_id,domain,receiver_email,tier,score,send_status,approved_at,sent_at,"
        "reply,audit_view,complaint,bounce,operator_notes\n"
        "acme.io,acme.io,ceo@acme.io,,,sent,,,yes,no,no,no,\n",
        encoding="utf-8",
    )
    n = merge_tracking_into_manifest(manifest, csv_path)
    assert n == 1
    assert manifest["contacts"][0]["reply"] is True
    assert manifest["contacts"][0]["send_status"] == "sent"


def test_canary_cli_does_not_enable_live_outreach(monkeypatch) -> None:
    policy = NightShiftPolicy(gates={"g1_manual_loop_proven": False})

    class _Cfg:
        live_outreach_enabled = False

    monkeypatch.setattr(
        "cato.core.night_shift_policy.load_night_shift_policy",
        lambda *a, **k: policy,
    )
    monkeypatch.setattr("cato.config.CatoConfig.load", lambda: _Cfg())
    from cato.canary25.safety import assert_canary_operator_safe

    msgs = assert_canary_operator_safe()
    assert any("blocked" in m.lower() or "G1 safety OK" in m for m in msgs)


def test_night_shift_still_blocks_live_outreach() -> None:
    policy = NightShiftPolicy(gates={"g1_manual_loop_proven": False})
    blocked, reason = policy.blocks_skill("outreach.run", {"dry_run": False})
    assert blocked is True
    assert "G1" in reason or "disabled" in reason.lower()


def test_cli_canary_import_command(tmp_path: Path) -> None:
    from click.testing import CliRunner
    from cato.cli import main

    p = _validated_csv(
        tmp_path,
        [
            {
                "domain": f"d{i}.com",
                "receiver_email": f"u{i}@d{i}.com",
                "email": f"u{i}@d{i}.com",
                "notes": "score=90; band=tier_a",
                "scrape_source": "t",
            }
            for i in range(30)
        ],
    )
    r = CliRunner().invoke(main, ["canary", "import", "--source", str(p)])
    assert r.exit_code == 0, r.output
    assert "Valid contacts: 30" in r.output

"""CLI: ``cato canary`` — canary-25 operator kit."""

from __future__ import annotations

import sys
from pathlib import Path

import click

from cato.canary25.contacts import load_contacts_csv, summarize_pool
from cato.canary25.criteria_doc import render_selection_criteria
from cato.canary25.manifest import (
    MANIFEST_NAME,
    SELECTION_DOC_NAME,
    TRACKING_CSV_NAME,
    build_manifest,
    evaluate_pass,
    find_contact,
    load_manifest,
    recompute_tracking_totals,
    save_manifest,
)
from cato.canary25.paths import default_canary_dir
from cato.canary25.safety import assert_canary_operator_safe
from cato.canary25.select import select_batch
from cato.canary25.tracking import merge_tracking_into_manifest, start_tracking_window, write_tracking_csv
from cato.platform import safe_print


def register_canary_commands(main: click.Group) -> None:
    """Attach ``cato canary`` command group."""

    @main.group("canary")
    def canary_cmd() -> None:
        """Canary-25 supervised batch: import contacts, select 25, track Row 4 metrics."""

    @canary_cmd.command("import")
    @click.option("--source", "source", required=True, type=click.Path(exists=True, path_type=Path))
    @click.option(
        "--format",
        "format_hint",
        default="auto",
        type=click.Choice(["auto", "validated", "clay", "generic"]),
        help="CSV shape: validated (303 list), Clay export, or generic.",
    )
    @click.option("--limit", default=0, type=int, help="Max rows to load (0 = all).")
    def cmd_canary_import(source: Path, format_hint: str, limit: int) -> None:
        """Validate a contacts CSV / Clay export without writing manifest."""
        for w in assert_canary_operator_safe():
            safe_print(w)
        lim = limit if limit > 0 else None
        rows, warnings, meta = load_contacts_csv(source, format_hint=format_hint, limit=lim)
        summary = summarize_pool(rows)
        safe_print(f"Source: {meta['source_file']}")
        safe_print(f"Format: {meta['format']}")
        safe_print(f"Valid contacts: {summary['total']}")
        safe_print(
            f"Tiers: tier_a={summary['tier_a']} tier_b={summary['tier_b']} "
            f"tier_c={summary['tier_c']} unknown={summary['tier_unknown']}"
        )
        if warnings:
            safe_print(f"Warnings: {len(warnings)} (showing first 10)")
            for line in warnings[:10]:
                safe_print(f"  {line}")
        if summary["total"] < 25:
            safe_print("Note: fewer than 25 valid contacts — cannot fill a full canary batch.")
            sys.exit(1)

    @canary_cmd.command("select")
    @click.option("--source", "source", required=True, type=click.Path(exists=True, path_type=Path))
    @click.option("--count", default=25, show_default=True, type=int)
    @click.option("--seed", default=None, type=int, help="Optional shuffle seed within tier bands.")
    @click.option(
        "--out-dir",
        default=None,
        type=click.Path(file_okay=False, path_type=Path),
        help="Default: proof-artifacts/canary-25 (or policy paths.proof_artifacts_dir).",
    )
    @click.option(
        "--format",
        "format_hint",
        default="auto",
        type=click.Choice(["auto", "validated", "clay", "generic"]),
    )
    @click.option("--batch-id", default=None, help="Override manifest batch_id.")
    def cmd_canary_select(
        source: Path,
        count: int,
        seed: int | None,
        out_dir: Path | None,
        format_hint: str,
        batch_id: str | None,
    ) -> None:
        """Select 25 contacts and write manifest, selection-criteria.md, tracking-sheet.csv."""
        for w in assert_canary_operator_safe():
            safe_print(w)
        out = out_dir or default_canary_dir()
        out.mkdir(parents=True, exist_ok=True)

        rows, warnings, meta = load_contacts_csv(source, format_hint=format_hint)
        if len(rows) < count:
            safe_print(f"Only {len(rows)} valid contacts — need at least {count}.")
            sys.exit(1)

        exclude: set[str] = set()
        manifest_path = out / MANIFEST_NAME
        if manifest_path.is_file():
            try:
                existing = load_manifest(manifest_path)
                exclude = {
                    str(c.get("contact_id", "")).lower()
                    for c in existing.get("contacts") or []
                }
            except Exception:
                pass

        selected, sel_meta = select_batch(
            rows, count=count, seed=seed, exclude_contact_ids=exclude or None
        )
        manifest = build_manifest(
            selected,
            source_file=meta["source_file"],
            selection_meta=sel_meta,
            batch_id=batch_id,
        )
        save_manifest(manifest, manifest_path)

        criteria = render_selection_criteria(
            source_file=meta["source_file"],
            format_name=meta["format"],
            pool_summary=summarize_pool(rows),
            selection_meta=sel_meta,
            selected_count=len(selected),
        )
        criteria_path = out / SELECTION_DOC_NAME
        criteria_path.write_text(criteria, encoding="utf-8")

        tracking_path = out / TRACKING_CSV_NAME
        write_tracking_csv(manifest, tracking_path)

        safe_print(f"Wrote {manifest_path} ({len(selected)} contacts)")
        safe_print(f"Wrote {criteria_path}")
        safe_print(f"Wrote {tracking_path}")
        if warnings:
            safe_print(f"Import warnings: {len(warnings)} (see import command for details)")
        safe_print("Next: hand-approve each send, then `cato canary mark-sent --contact <domain>`")

    @canary_cmd.command("status")
    @click.option(
        "--manifest",
        "manifest_path",
        default=None,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    def cmd_canary_status(manifest_path: Path | None) -> None:
        """Show Row 4 tracking totals and pass/fail vs loop-proof-card."""
        for w in assert_canary_operator_safe():
            safe_print(w)
        manifest = load_manifest(manifest_path)
        ev = evaluate_pass(manifest)
        tr = manifest.get("tracking") or {}
        safe_print(f"Batch: {manifest.get('batch_id')} status={manifest.get('status')}")
        safe_print(f"Sent: {ev['sent_count']} / {ev['target_sends']}")
        safe_print(
            f"Replies: {tr.get('replies', 0)}  Audit views: {tr.get('audit_views', 0)}  "
            f"(need >= {manifest.get('pass_criteria', {}).get('min_replies_or_audit_views', 1)} combined)"
        )
        safe_print(
            f"Complaints: {tr.get('complaints', 0)} ({tr.get('complaint_rate_pct', 0)}%)  "
            f"Bounces: {tr.get('bounces', 0)} ({tr.get('bounce_rate_pct', 0)}%)"
        )
        safe_print(f"Row 4 pass: {'YES' if ev['row4_pass'] else 'NO'}")
        for k, ok in ev["checks"].items():
            safe_print(f"  {k}: {'ok' if ok else 'FAIL'}")

    @canary_cmd.command("mark-sent")
    @click.option("--contact", "contact_id", required=True)
    @click.option("--manifest", "manifest_path", default=None, type=click.Path(path_type=Path))
    @click.option("--sync-csv/--no-sync-csv", default=True, help="Refresh tracking-sheet.csv.")
    def cmd_canary_mark_sent(
        contact_id: str,
        manifest_path: Path | None,
        sync_csv: bool,
    ) -> None:
        """Record one hand-approved send (does not send email)."""
        for w in assert_canary_operator_safe():
            safe_print(w)
        path = manifest_path or (default_canary_dir() / MANIFEST_NAME)
        manifest = load_manifest(path)
        row = find_contact(manifest, contact_id)
        if not row:
            safe_print(f"Unknown contact_id: {contact_id}")
            sys.exit(1)
        row["send_status"] = "sent"
        from datetime import datetime, timezone

        row["sent_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        if not manifest.get("tracking", {}).get("window_start"):
            start_tracking_window(manifest)
        recompute_tracking_totals(manifest)
        save_manifest(manifest, path)
        if sync_csv:
            write_tracking_csv(manifest, path.parent / TRACKING_CSV_NAME)
        target = len(manifest.get("contacts") or [])
        safe_print(
            f"Marked sent: {contact_id} ({manifest['tracking']['sent_count']}/{target})"
        )

    @canary_cmd.command("record")
    @click.option("--contact", "contact_id", default=None, help="Per-contact flag (optional).")
    @click.option("--reply", is_flag=True)
    @click.option("--audit-view", "audit_view", is_flag=True)
    @click.option("--complaint", is_flag=True)
    @click.option("--bounce", is_flag=True)
    @click.option("--manifest", "manifest_path", default=None, type=click.Path(path_type=Path))
    @click.option("--sync-csv/--no-sync-csv", default=True)
    def cmd_canary_record(
        contact_id: str | None,
        reply: bool,
        audit_view: bool,
        complaint: bool,
        bounce: bool,
        manifest_path: Path | None,
        sync_csv: bool,
    ) -> None:
        """Record reply, audit view, complaint, or bounce for one contact."""
        if not any((reply, audit_view, complaint, bounce)):
            safe_print("Specify at least one of: --reply, --audit-view, --complaint, --bounce")
            sys.exit(1)
        if not contact_id:
            safe_print(
                "Specify --contact <domain> (e.g. example.com). "
                "Per-contact flags are required so totals stay accurate."
            )
            sys.exit(1)
        path = manifest_path or (default_canary_dir() / MANIFEST_NAME)
        manifest = load_manifest(path)
        row = find_contact(manifest, contact_id)
        if not row:
            safe_print(f"Unknown contact_id: {contact_id}")
            sys.exit(1)
        if reply:
            row["reply"] = True
        if audit_view:
            row["audit_view"] = True
        if complaint:
            row["complaint"] = True
        if bounce:
            row["bounce"] = True
        recompute_tracking_totals(manifest)
        save_manifest(manifest, path)
        if sync_csv:
            write_tracking_csv(manifest, path.parent / TRACKING_CSV_NAME)
        safe_print("Recorded.")

    @canary_cmd.command("sync-tracking")
    @click.option(
        "--csv",
        "csv_path",
        default=None,
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    @click.option("--manifest", "manifest_path", default=None, type=click.Path(path_type=Path))
    def cmd_canary_sync_tracking(csv_path: Path | None, manifest_path: Path | None) -> None:
        """Merge tracking-sheet.csv edits into manifest.json."""
        base = default_canary_dir()
        path = manifest_path or (base / MANIFEST_NAME)
        csv_file = csv_path or (base / TRACKING_CSV_NAME)
        manifest = load_manifest(path)
        n = merge_tracking_into_manifest(manifest, csv_file)
        save_manifest(manifest, path)
        safe_print(f"Merged {n} rows from {csv_file}")

    @canary_cmd.command("approve")
    @click.option("--contact", "contact_id", required=True)
    @click.option("--manifest", "manifest_path", default=None, type=click.Path(path_type=Path))
    def cmd_canary_approve(contact_id: str, manifest_path: Path | None) -> None:
        """Mark contact approved for send (operator reviewed personalization)."""
        for w in assert_canary_operator_safe():
            safe_print(w)
        path = manifest_path or (default_canary_dir() / MANIFEST_NAME)
        manifest = load_manifest(path)
        row = find_contact(manifest, contact_id)
        if not row:
            safe_print(f"Unknown contact_id: {contact_id}")
            sys.exit(1)
        from datetime import datetime, timezone

        row["send_status"] = "approved"
        row["approved_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        save_manifest(manifest, path)
        write_tracking_csv(manifest, path.parent / TRACKING_CSV_NAME)
        safe_print(f"Approved: {contact_id}")

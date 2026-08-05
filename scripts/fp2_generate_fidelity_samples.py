"""G1 Row 2: generate 3 LIVE ConduitScore scan artifacts + verify checks.

Requires valid CONDUITSCORE_API_KEY (Pro+ REST API). On 401, rotate key in
ConduitScore dashboard and run: python scripts/sync_outreach_vault.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen

# Reuse outreach pipeline Conduit client
PIPE = Path(r"C:\Users\Administrator\Desktop\ConduitScore\conduit_outreach_pipeline")
sys.path.insert(0, str(PIPE / "src"))

from conduit_outreach_pipeline.conduit_cached import scan_domain_raw  # noqa: E402

OUT = Path(r"C:\Users\Administrator\Desktop\Cato\proof-artifacts\fidelity")
SAMPLES = [
    {"label": "sample-01-example", "url": "https://example.com"},
    {"label": "sample-02-linear", "url": "https://linear.app"},
    {"label": "sample-03-conduitscore", "url": "https://conduitscore.com"},
]
BASE = "https://conduitscore.com"


def verify_scan(scan_id: str) -> dict:
    url = f"{BASE}/api/verify/{scan_id}"
    req = Request(url, headers={"Accept": "application/json", "User-Agent": "Cato-FP2/1.0"})
    try:
        raw = urlopen(req, timeout=30).read().decode("utf-8", "replace")
        return json.loads(raw)
    except Exception as exc:
        return {"error": str(exc), "url": url}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    index: list[dict] = []
    for i, spec in enumerate(SAMPLES, start=1):
        print(f"[{i}/3] Scanning {spec['url']}...")
        try:
            scan = scan_domain_raw(spec["url"])
        except Exception as exc:
            scan = {"error": str(exc), "url": spec["url"]}
        scan_id = scan.get("id") or scan.get("scanId")
        record = {
            "label": spec["label"],
            "url": spec["url"],
            "scan_id": scan_id,
            "overallScore": scan.get("overallScore"),
            "report_url": f"{BASE}/reports/{scan_id}" if scan_id else None,
            "verify_url": f"{BASE}/verify/{scan_id}" if scan_id else None,
            "proof_present": bool(scan.get("proof")),
        }
        if scan_id:
            time.sleep(2)
            record["verify"] = verify_scan(str(scan_id))
            v = record["verify"].get("verification", {})
            record["signature_status"] = v.get("status")
        path = OUT / "samples" / f"{spec['label']}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"scan": scan, "meta": record}, indent=2), encoding="utf-8")
        index.append(record)
        print(f"  -> score={record.get('overallScore')} verify={record.get('signature_status')}")
        if i < len(SAMPLES):
            time.sleep(12)
    (OUT / "samples-index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    print(f"Wrote {OUT / 'samples-index.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

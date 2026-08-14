"""
cato/tools/swarmsync_proof.py — SwarmSync Proof Products client.

Scoped narrowly to the three proof products Ben wants Cato to keep using from
SwarmSync after general-purpose LLM routing through SwarmSync was retired
(2026-08-05, see cato/router.py + cato/model_policy.py). This module does
NOT touch model routing -- it only talks to SwarmSync's proof-verification
backend.

Two distinct backends, confirmed by reading swarmsync/CLAUDE.md and the
actual controller source (swarmsync/apps/api/src/modules/verification/
verify-api.controller.ts) directly -- not guessed:

  InvoiceProof
    POST https://swarmsync.ai/api/scan/invoices -- PUBLIC, NO AUTH KEY NEEDED.
    Runs on the Next.js web app (apps/web), a different host from the other
    two, which live on the NestJS API (apps/api, api.swarmsync.ai).

  AuditProof / VerifyAPI
    Both share ONE endpoint: POST https://api.swarmsync.ai/api/verify.
    `source_type` is a REQUIRED field and must be one of exactly:
    api_output, agent_activity, audit_proof, document, workflow_event,
    software_delivery (verify-api.controller.ts VALID_SOURCE_TYPES).
    AuditProof = source_type "audit_proof". VerifyAPI (software delivery
    verification) = source_type "software_delivery" (which, per ISSUE-13
    in that file, rejects a plain string `output` -- give it structured
    data, e.g. a dict with delivery_statement/deployment_report/release_notes,
    or the full repo-based shape).
    Requires a VerifyAPI key (`ssk_live_...`), sent as
    `Authorization: Bearer ssk_live_...`. Minted via SwarmSync's own Console
    -> Settings -> API Keys -> Create API Key -> select "VerifyAPI". This is
    a DIFFERENT key type from the old general-purpose SWARMSYNC_API_KEY
    (an `sa_...` service-account key) -- that key type was never valid for
    these endpoints, confirmed by SwarmSage's investigation of the 2026-08-05
    401 errors. Both AuditProof and VerifyAPI are paid, entitlement-gated
    products -- a valid key can still be rejected if the org lacks the
    matching ProofProductEntitlement.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

import aiohttp

logger = logging.getLogger("cato.tools.swarmsync_proof")

_INVOICE_SCAN_URL = "https://swarmsync.ai/api/scan/invoices"
_VERIFY_URL = "https://api.swarmsync.ai/api/verify"

#: Exact set verify-api.controller.ts accepts -- anything else is a 400
#: before the request even reaches billing/entitlement checks.
VALID_SOURCE_TYPES: frozenset[str] = frozenset({
    "api_output", "agent_activity", "audit_proof",
    "document", "workflow_event", "software_delivery",
})

_UPSTREAM_BODY_TRUNCATE = 1000


def _get_verify_api_key(vault: Any = None) -> str:
    """Resolve the VerifyAPI key from the encrypted vault only.

    Stored under SWARMSYNC_VERIFYAPI_KEY -- deliberately NOT the old
    SWARMSYNC_API_KEY name, so no future code path can accidentally revive
    the retired general-purpose SwarmSync LLM-routing key by reusing a name.
    """
    try:
        value = vault.get("SWARMSYNC_VERIFYAPI_KEY") if vault else None
    except Exception:
        value = None
    return str(value or "").strip()


class SwarmSyncProofClient:
    """Thin async client for SwarmSync's three proof products."""

    def __init__(self, vault: Any = None, timeout_s: float = 30.0) -> None:
        self._vault = vault
        self._timeout_s = timeout_s
        self._session: Optional[aiohttp.ClientSession] = None

    def has_verify_credentials(self) -> bool:
        return bool(_get_verify_api_key(self._vault))

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self._timeout_s)
            )
        return self._session

    async def close(self) -> None:
        if self._session is not None and not self._session.closed:
            await self._session.close()
        self._session = None

    # -- InvoiceProof: public, no auth -----------------------------------

    async def invoice_proof(
        self,
        *,
        invoices: Optional[list[dict[str, Any]]] = None,
        text: Optional[str] = None,
        po_register: Optional[list[dict[str, Any]]] = None,
        vendor_master: Optional[list[dict[str, Any]]] = None,
        payment_history: Optional[list[dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """Scan an AP invoice batch for fraud (duplicate / BEC bank-change /
        PO-overage / math-error / round-dollar patterns). Supply structured
        `invoices` or raw CSV `text` -- exactly one, matching swarmsync's own
        contract. No API key needed; this endpoint is public.
        """
        if not invoices and not text:
            return {"ok": False, "error": "invalid_arguments",
                     "reason": "supply either invoices or text"}
        body: dict[str, Any] = {}
        if invoices is not None:
            body["invoices"] = invoices
        if text is not None:
            body["text"] = text
        if po_register is not None:
            body["poRegister"] = po_register
        if vendor_master is not None:
            body["vendorMaster"] = vendor_master
        if payment_history is not None:
            body["paymentHistory"] = payment_history

        session = await self._ensure_session()
        try:
            async with session.post(_INVOICE_SCAN_URL, json=body) as resp:
                raw = await resp.text()
                if resp.status != 200:
                    return {
                        "ok": False, "error": "upstream_error", "status": resp.status,
                        "body": raw[:_UPSTREAM_BODY_TRUNCATE],
                    }
                try:
                    return {"ok": True, "response": json.loads(raw)}
                except json.JSONDecodeError:
                    return {"ok": False, "error": "invalid_json_response",
                             "body": raw[:_UPSTREAM_BODY_TRUNCATE]}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "exception", "type": type(exc).__name__,
                     "message": str(exc)}

    # -- AuditProof / VerifyAPI: shared backend, needs ssk_live_ key ------

    async def _call_verify(
        self,
        *,
        source_type: str,
        output: Any,
        task: Optional[str] = None,
        rules: Optional[list[Any]] = None,
        evidence: Optional[Any] = None,
    ) -> dict[str, Any]:
        if source_type not in VALID_SOURCE_TYPES:
            return {
                "ok": False, "error": "invalid_source_type",
                "reason": f'"{source_type}" is not recognized',
                "allowed_values": sorted(VALID_SOURCE_TYPES),
            }
        api_key = _get_verify_api_key(self._vault)
        if not api_key:
            return {
                "ok": False, "error": "missing_credentials",
                "reason": "SWARMSYNC_VERIFYAPI_KEY not configured -- mint an "
                          "ssk_live_ key via swarmsync.ai Console > Settings > "
                          "API Keys > Create API Key > VerifyAPI",
            }
        body: dict[str, Any] = {"source_type": source_type, "output": output}
        if task is not None:
            body["task"] = task
        if rules is not None:
            body["rules"] = rules
        if evidence is not None:
            body["evidence"] = evidence

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        session = await self._ensure_session()
        try:
            async with session.post(_VERIFY_URL, json=body, headers=headers) as resp:
                raw = await resp.text()
                if resp.status == 401:
                    return {"ok": False, "error": "unauthorized", "status": 401,
                             "reason": "VerifyAPI key rejected -- check it hasn't "
                                       "expired or been revoked in the Console"}
                if resp.status == 402 or resp.status == 403:
                    return {"ok": False, "error": "entitlement_required", "status": resp.status,
                             "body": raw[:_UPSTREAM_BODY_TRUNCATE],
                             "reason": "AuditProof/VerifyAPI are paid, entitlement-gated "
                                       "products -- a valid key can still be rejected if "
                                       "the org lacks the matching plan"}
                if resp.status != 200:
                    return {
                        "ok": False, "error": "upstream_error", "status": resp.status,
                        "body": raw[:_UPSTREAM_BODY_TRUNCATE],
                    }
                try:
                    return {"ok": True, "response": json.loads(raw)}
                except json.JSONDecodeError:
                    return {"ok": False, "error": "invalid_json_response",
                             "body": raw[:_UPSTREAM_BODY_TRUNCATE]}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": "exception", "type": type(exc).__name__,
                     "message": str(exc)}

    async def audit_proof(
        self, *, output: Any, evidence: Optional[Any] = None, rules: Optional[list[Any]] = None,
    ) -> dict[str, Any]:
        """AI work audit trail verification (EU AI Act / compliance docs) --
        paid, entitlement-gated product. source_type='audit_proof'."""
        return await self._call_verify(source_type="audit_proof", output=output,
                                          evidence=evidence, rules=rules)

    async def verify_software_delivery(
        self, *, output: dict[str, Any], evidence: Optional[Any] = None,
        rules: Optional[list[Any]] = None,
    ) -> dict[str, Any]:
        """Software-delivery verification -- the "VerifyAPI" product proper.
        source_type='software_delivery'. `output` MUST be structured (a dict)
        -- the backend explicitly rejects a plain string here (ISSUE-13),
        so give it at least one of: delivery_statement, deployment_report,
        release_notes (document path), or the full repo-based fields
        (repoOwner, repoName, beforeSha, afterSha, jobStartedAt, tier,
        jobType -- see swarmsync's SoftwareDeliveryVerifyDto)."""
        if not isinstance(output, dict):
            return {"ok": False, "error": "invalid_arguments",
                     "reason": "output must be a structured object for "
                               "software_delivery, not a plain string"}
        return await self._call_verify(source_type="software_delivery", output=output,
                                          evidence=evidence, rules=rules)

    async def verify_api(
        self, *, output: Any, source_type: str = "api_output",
        task: Optional[str] = None, evidence: Optional[Any] = None,
        rules: Optional[list[Any]] = None,
    ) -> dict[str, Any]:
        """General-purpose entry point for the remaining source types
        (api_output, agent_activity, document, workflow_event). For
        AuditProof or the software-delivery VerifyAPI product specifically,
        use audit_proof() / verify_software_delivery() instead -- they pin
        the correct source_type so a caller can't get it wrong."""
        return await self._call_verify(source_type=source_type, task=task,
                                          output=output, evidence=evidence, rules=rules)


__all__ = ["SwarmSyncProofClient", "VALID_SOURCE_TYPES"]

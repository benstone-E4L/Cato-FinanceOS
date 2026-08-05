"""Builder-facing integration tools for Cato."""

from __future__ import annotations

from typing import Any

from ..core.approval_policy import ApprovalContext, take_execution_grant
from ..integrations.runtime import IntegrationRuntime, dumps_public


class IntegrationTool:
    """Expose integration metadata and safe action planning/execution."""

    def __init__(self, vault: Any = None) -> None:
        self._runtime = IntegrationRuntime(vault=vault)

    async def status(self, args: dict[str, Any]) -> str:
        integration_id = args.get("integration") or args.get("integration_id")
        return dumps_public(self._runtime.status(integration_id))

    async def setup(self, args: dict[str, Any]) -> str:
        integration_id = args.get("integration") or args.get("integration_id") or ""
        params = args.get("params") or {}
        if not isinstance(params, dict):
            return dumps_public({
                "ok": False,
                "error": "params must be an object",
                "secrets_returned": False,
            })
        return dumps_public(self._runtime.setup(integration_id, params))

    async def action(
        self,
        args: dict[str, Any],
        *,
        context: ApprovalContext | None = None,
    ) -> str:
        """Plan an integration action, or execute it if a ticket authorized it.

        SECURITY: ``approved`` and ``dry_run`` are NOT read from ``args``.
        ``args`` is model-supplied, and a model-emitted ``approved: true`` was
        previously the sole authorization before a live third-party write
        (Stripe payment links, GitHub repo creation, Vercel deployments).

        Authorization now has exactly two sources, neither expressible as a
        JSON tool argument:

          1. a single-use execution grant minted by
             ``OutboundApprovalStore.consume()`` when a human-approved ticket
             is redeemed for this exact tool + argument digest, or
          2. an ``ApprovalContext`` object passed by trusted Python code.

        With neither, this plans only and never makes a live call.
        """
        integration_id = args.get("integration") or args.get("integration_id") or ""
        action_name = args.get("action") or args.get("action_name") or ""
        params = args.get("params") or {}
        if not isinstance(params, dict):
            return dumps_public({
                "ok": False,
                "error": "params must be an object",
                "dry_run": True,
            })

        authorized = take_execution_grant("integration.action", args)
        if not authorized and context is not None and context.execution_authorized:
            authorized = True

        if not authorized and _requests_live_write(args):
            # The model asked for a live write without a redeemed ticket. Say so
            # explicitly rather than silently downgrading to a dry run, so the
            # refusal is visible in the transcript and the audit trail.
            return dumps_public({
                "ok": False,
                "error": "approval_required",
                "dry_run": True,
                "approval_required": True,
                "detail": (
                    "A live integration write requires a human-approved outbound "
                    "approval ticket. 'approved'/'dry_run' in tool arguments are "
                    "ignored and cannot authorize execution."
                ),
            })

        timeout = float(args.get("timeout", 20.0))
        result = await self._runtime.action(
            integration_id=integration_id,
            action_name=action_name,
            params=params,
            dry_run=not authorized,
            approved=authorized,
            timeout=timeout,
        )
        return dumps_public(result)


def _requests_live_write(args: dict[str, Any]) -> bool:
    """Did the caller ask for a live call? Used only for the error message.

    These values never grant anything — reading them here cannot authorize
    execution, it only makes an unauthorized attempt explicit instead of
    silently returning a plan the caller did not ask for.
    """
    return _as_bool(args.get("approved", False), default=False) or not _as_bool(
        args.get("dry_run", True), default=True
    )


def _as_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)

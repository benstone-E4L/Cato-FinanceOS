"""
cato/safety.py — Pre-action reversibility gates for CATO.

Prevents the "agent ran amok" scenario (e.g. Meta inbox deletion).
Every tool call is classified into one of four risk tiers before execution.
IRREVERSIBLE and HIGH_STAKES actions require explicit user confirmation.

Checks for a STOP signal file (get_data_dir()/STOP) before every action.

FAIL-CLOSED CONTRACT (P0-1)
---------------------------
A tool this module cannot positively identify is classified ``HIGH_STAKES`` —
the most restrictive tier — and is never auto-allowed. Removing a tool from
``_TOOL_TIER`` therefore makes it *more* restricted, not less. A future
``xero_post_bill`` or ``wire_transfer_send`` is gated on the day it is added,
before anyone remembers to classify it.

Classification order:
  1. shell / shell.exec / shell.run  → keyword scan of the command string.
  2. `file` / `browser` dispatchers  → resolved to `<tool>.<action>` sub-tier;
                                        an unrecognised action is HIGH_STAKES.
  3. explicit `_TOOL_TIER` entry.
  4. the declarative approval policy (`cato.core.approval_policy`), which is
     itself fail-closed — an unknown capability resolves to tier `critical`.
  5. anything left over → HIGH_STAKES.

Configuration:
    safety_mode: strict      — IRREVERSIBLE and HIGH_STAKES prompt user
    safety_mode: permissive  — HIGH_STAKES prompts, IRREVERSIBLE skips prompt
    safety_mode: off         — gates disabled for *classified* tools only;
                               shell exec and unclassified tools stay blocked
"""

from __future__ import annotations

import logging
from enum import IntEnum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Risk tiers
# ---------------------------------------------------------------------------

class RiskTier(IntEnum):
    READ             = 0   # No side effects: browser.navigate, browser.extract, browser.screenshot
    REVERSIBLE_WRITE = 1   # Easily undone: browser.click, browser.type
    IRREVERSIBLE     = 2   # Cannot be undone: shell rm/delete/drop
    HIGH_STAKES      = 3   # Financial/social consequence: mail/send/post/publish/payment


# ---------------------------------------------------------------------------
# Classification rules
# ---------------------------------------------------------------------------

# The tier assigned to anything this module cannot positively identify.
# It is deliberately the TOP tier: an unclassified tool is treated as if it
# could move money or publish to the world, because we cannot prove it can't.
UNCLASSIFIED_TIER: RiskTier = RiskTier.HIGH_STAKES

# Tools that dispatch to a sub-action carried in args["action"].
_DISPATCHER_TOOLS = frozenset({"file", "browser"})

# Tool-name → base tier mapping (before checking inputs).
#
# This table is an ALLOW-list of positively reviewed capabilities. Anything not
# in it falls through to the approval policy and then to UNCLASSIFIED_TIER.
_TOOL_TIER: dict[str, RiskTier] = {
    # --- browser sub-actions ------------------------------------------------
    "browser.navigate":              RiskTier.READ,
    "browser.navigate_back":         RiskTier.READ,
    "browser.extract":               RiskTier.READ,
    "browser.extract_main":          RiskTier.READ,
    "browser.screenshot":            RiskTier.READ,
    "browser.search":                RiskTier.READ,
    "browser.snapshot":              RiskTier.READ,
    "browser.accessibility_snapshot": RiskTier.READ,
    "browser.network_requests":      RiskTier.READ,
    "browser.console_messages":      RiskTier.READ,
    "browser.wait":                  RiskTier.READ,
    "browser.wait_for":              RiskTier.READ,
    "browser.scroll":                RiskTier.READ,
    "browser.hover":                 RiskTier.READ,
    "browser.click":                 RiskTier.REVERSIBLE_WRITE,
    "browser.type":                  RiskTier.REVERSIBLE_WRITE,
    "browser.fill":                  RiskTier.REVERSIBLE_WRITE,
    "browser.key_press":             RiskTier.REVERSIBLE_WRITE,
    "browser.select_option":         RiskTier.REVERSIBLE_WRITE,
    "browser.handle_dialog":         RiskTier.REVERSIBLE_WRITE,
    "browser.pdf":                   RiskTier.REVERSIBLE_WRITE,
    "browser.output_to_file":        RiskTier.REVERSIBLE_WRITE,
    # `browser.eval` runs attacker-reachable JavaScript in the page context.
    "browser.eval":                  RiskTier.IRREVERSIBLE,

    # --- file sub-actions ---------------------------------------------------
    "file.read":     RiskTier.READ,
    "file.list":     RiskTier.READ,
    "file.exists":   RiskTier.READ,
    "file.roots":    RiskTier.READ,
    "file.write":    RiskTier.IRREVERSIBLE,
    "file.append":   RiskTier.IRREVERSIBLE,
    "file.patch":    RiskTier.IRREVERSIBLE,
    "file.delete":   RiskTier.IRREVERSIBLE,

    # --- read-only research/query tools -------------------------------------
    "memory.search":              RiskTier.READ,
    "memory.federated":           RiskTier.READ,
    "web.search":                 RiskTier.READ,
    "web.code":                   RiskTier.READ,
    "web.news":                   RiskTier.READ,
    "academic.arxiv":             RiskTier.READ,
    "academic.semantic_scholar":  RiskTier.READ,
    "academic.pubmed":            RiskTier.READ,
    "graph.query":                RiskTier.READ,
    "graph.related":              RiskTier.READ,
    "github.issue_list":          RiskTier.READ,
    "github.pr_list":             RiskTier.READ,
    "integration.status":         RiskTier.READ,
    "conduit.crawl":              RiskTier.READ,

    # --- local, undoable writes ---------------------------------------------
    "memory.store":         RiskTier.REVERSIBLE_WRITE,
    "conduit.monitor":      RiskTier.REVERSIBLE_WRITE,
    # Integration status/action/setup are planners: they emit a plan and write
    # local integration metadata. They do not themselves call a third party.
    "integration.action":   RiskTier.REVERSIBLE_WRITE,
    "integration.setup":    RiskTier.REVERSIBLE_WRITE,

    # --- reaches someone else's system --------------------------------------
    "github.pr_review":     RiskTier.IRREVERSIBLE,
    "github.issue_create":  RiskTier.IRREVERSIBLE,
}

# Approval-policy tier → RiskTier. The policy is the declarative source of
# truth for capabilities Cato gates for outbound/financial reasons; this map
# keeps the two engines from disagreeing. Anything unmapped is HIGH_STAKES.
_POLICY_TIER_TO_RISK: dict[str, RiskTier] = {
    "read_only":  RiskTier.READ,
    "reversible": RiskTier.REVERSIBLE_WRITE,
    "elevated":   RiskTier.IRREVERSIBLE,
    "outbound":   RiskTier.HIGH_STAKES,
    "dispatch":   RiskTier.HIGH_STAKES,
    "financial":  RiskTier.HIGH_STAKES,
    "critical":   RiskTier.HIGH_STAKES,
}

# Keywords in shell commands that escalate tier
_IRREVERSIBLE_SHELL_KEYWORDS = frozenset({
    "rm", "del", "delete", "drop", "format", "truncate", "rmdir",
    "remove", "unlink", "shred", "wipe",
    # PowerShell destructive verbs and their common aliases
    "remove-item", "clear-content", "format-volume", "stop-process",
    "invoke-expression", "iex",
})

_HIGH_STAKES_SHELL_KEYWORDS = frozenset({
    "mail", "send", "post", "publish", "payment", "pay", "transfer",
    "deploy", "push", "submit", "commit --amend",
})


def _classify_shell(inputs: dict) -> RiskTier:
    """Classify a shell tool call based on the command string."""
    cmd = str(inputs.get("command", inputs.get("cmd", ""))).lower()
    tokens = set(cmd.split())

    if tokens & _HIGH_STAKES_SHELL_KEYWORDS:
        return RiskTier.HIGH_STAKES
    if tokens & _IRREVERSIBLE_SHELL_KEYWORDS:
        return RiskTier.IRREVERSIBLE
    return RiskTier.REVERSIBLE_WRITE  # shell by default is a write


def _dispatcher_key(tool_name: str, inputs: dict) -> Optional[str]:
    """Resolve `file` / `browser` to the `<tool>.<action>` key they dispatch to.

    Returns None when no usable action was supplied — the caller must then
    treat the call as unclassified rather than guessing.
    """
    if not isinstance(inputs, dict):
        return None
    action = inputs.get("action") or inputs.get("op") or inputs.get("operation")
    if not isinstance(action, str) or not action.strip():
        return None
    return f"{tool_name}.{action.strip().lower()}"


def _requests_unsandboxed_root(inputs: dict) -> bool:
    """True when the call sets ``root='absolute'``, opting out of the workspace.

    Kept in sync with cato/core/approval_policy.py::requests_unsandboxed_root
    so both gates classify the same call the same way. Resolved here rather
    than delegating so a broken import can never quietly stop the escalation.
    """
    if not isinstance(inputs, dict):
        return False
    root = inputs.get("root")
    return isinstance(root, str) and root.strip().lower() == "absolute"


def _policy_tier(tool_name: str) -> RiskTier:
    """Fall back to the declarative approval policy, which is itself fail-closed.

    Any failure to reach or read the policy yields the most restrictive tier —
    we never downgrade a tool because a lookup broke.
    """
    try:
        from .core.approval_policy import resolve_tool
        rule = resolve_tool(tool_name)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "Risk classification: approval policy unavailable for %r (%s); "
            "treating as %s", tool_name, exc, UNCLASSIFIED_TIER.name,
        )
        return UNCLASSIFIED_TIER

    if not getattr(rule, "known", False):
        logger.warning(
            "Risk classification: tool %r is unknown to both the safety table "
            "and the approval policy — classified %s (fail-closed)",
            tool_name, UNCLASSIFIED_TIER.name,
        )
        return UNCLASSIFIED_TIER

    return _POLICY_TIER_TO_RISK.get(getattr(rule, "tier", ""), UNCLASSIFIED_TIER)


# ---------------------------------------------------------------------------
# SafetyGuard
# ---------------------------------------------------------------------------

class SafetyGuard:
    """
    Pre-action reversibility gate.

    Usage::

        guard = SafetyGuard(config={"safety_mode": "strict"})
        allowed = guard.check_and_confirm("browser.click", {"selector": "#delete-all"})
        if not allowed:
            raise RuntimeError("User denied action")
    """

    def __init__(self, config: Optional[dict] = None) -> None:
        cfg = config or {}
        self._mode: str = cfg.get("safety_mode", "strict").lower()
        self._stop_file: Path = self._stop_file_path()
        self._shell_exec_allowed: bool = bool(cfg.get("shell_exec_allowed", False))

    @staticmethod
    def _stop_file_path() -> Path:
        from .platform import get_data_dir
        return get_data_dir() / "STOP"

    def is_stop_requested(self) -> bool:
        """
        Return True if the STOP signal file exists.

        Place a file at {data_dir}/STOP to request immediate halt.
        """
        return self._stop_file.exists()

    def classify_action(self, tool_name: str, inputs: dict) -> RiskTier:
        """
        Classify a tool call into a RiskTier. Fail-closed: an unrecognised tool
        is ``UNCLASSIFIED_TIER`` (HIGH_STAKES), never something middling.
        """
        name = (tool_name or "").strip()
        if not name:
            return UNCLASSIFIED_TIER

        if name in ("shell", "shell.exec", "shell.run"):
            return _classify_shell(inputs if isinstance(inputs, dict) else {})

        if name in _DISPATCHER_TOOLS:
            key = _dispatcher_key(name, inputs)
            if key is None:
                logger.warning(
                    "Risk classification: %r called without a readable action; "
                    "classified %s (fail-closed)", name, UNCLASSIFIED_TIER.name,
                )
                return UNCLASSIFIED_TIER
            tier = _TOOL_TIER.get(key)
            if tier is None:
                logger.warning(
                    "Risk classification: unrecognised sub-action %r — "
                    "classified %s (fail-closed)", key, UNCLASSIFIED_TIER.name,
                )
                return UNCLASSIFIED_TIER
            # A call that opts out of workspace scoping reaches the whole
            # filesystem — the vault, the ledger, .env, SSH keys. That is a
            # HIGH_STAKES exfiltration surface however innocent the sub-action
            # looks. Escalate only; a sub-action already at or above this tier
            # keeps its own. Mirrors approval_policy.resolve_tool.
            if _requests_unsandboxed_root(inputs) and tier < RiskTier.HIGH_STAKES:
                logger.warning(
                    "Risk classification: %r with root='absolute' escalated "
                    "%s -> HIGH_STAKES (workspace scoping opted out)",
                    key, tier.name,
                )
                return RiskTier.HIGH_STAKES
            return tier

        tier = _TOOL_TIER.get(name)
        if tier is not None:
            return tier

        return _policy_tier(name)

    def is_classified(self, tool_name: str, inputs: Optional[dict] = None) -> bool:
        """True when this tool was positively identified (not fail-closed default).

        Used by ``safety_mode: off`` so that disabling the gates cannot silently
        enable a capability nobody has ever reviewed.
        """
        name = (tool_name or "").strip()
        if not name:
            return False
        if name in ("shell", "shell.exec", "shell.run"):
            return True
        if name in _DISPATCHER_TOOLS:
            key = _dispatcher_key(name, inputs or {})
            return key is not None and key in _TOOL_TIER
        if name in _TOOL_TIER:
            return True
        try:
            from .core.approval_policy import resolve_tool
            return bool(getattr(resolve_tool(name), "known", False))
        except Exception:  # pragma: no cover — defensive
            return False

    def _defers_to_approval_gate(self, tool_name: str, inputs: dict) -> bool:
        """True when refusing here would only hide the call from the human.

        Two conditions, both required:

        * the tool is POSITIVELY CLASSIFIED (``is_classified``) — an unknown
          capability is never handed onward, it is refused; and
        * the declarative approval policy says this exact call requires an
          approval ticket — the same predicate
          ``AgentLoop._maybe_gate_outbound_tool`` evaluates, so a True here
          guarantees the call is held for a human downstream.

        Any error resolving the policy answers False (deny), never True.
        """
        try:
            if not self.is_classified(tool_name, inputs):
                return False
            from .core.approval_policy import evaluate
            return bool(
                evaluate(tool_name, inputs if isinstance(inputs, dict) else {}).requires_approval
            )
        except Exception as exc:  # pragma: no cover — defensive, fail closed
            logger.warning(
                "Approval-gate deferral check failed for %r (%s); denying.",
                tool_name, exc,
            )
            return False

    def check_and_confirm(self, tool_name: str, inputs: dict) -> bool:
        """
        Check whether the action should proceed.

        Returns True if allowed, False if the user denied or a STOP was requested.

        Logic:
        - If safety_mode == "off": always True.
        - If STOP file exists: log warning and return False.
        - If tier < threshold for current mode: True.
        - Otherwise: print action summary and prompt "Proceed? [y/N]".
          Default answer is N (safe by default).
        """
        if self._mode == "off":
            # shell.exec always requires explicit opt-in regardless of safety_mode
            if tool_name in ("shell", "shell.exec", "shell.run") and not self._shell_exec_allowed:
                logger.warning(
                    "shell.exec blocked in safety_mode=off: set shell_exec_allowed=true in config to enable"
                )
                return False
            # Turning the gates off is a statement about tools we have reviewed.
            # It is not consent for a capability that has never been classified.
            if not self.is_classified(tool_name, inputs):
                logger.warning(
                    "Unclassified tool %r blocked even in safety_mode=off: "
                    "add it to cato.safety._TOOL_TIER or the approval policy first.",
                    tool_name,
                )
                _safe_print(
                    f"[CATO SAFETY] '{tool_name}' is unclassified and was denied."
                )
                return False
            return True

        # Emergency stop check
        if self.is_stop_requested():
            logger.warning(
                "STOP signal file detected — halting before tool_name=%s", tool_name
            )
            _safe_print(f"[CATO SAFETY] STOP file detected at {self._stop_file}. Halting.")
            return False

        tier = self.classify_action(tool_name, inputs)

        # Determine threshold based on mode
        if self._mode == "permissive":
            threshold = RiskTier.HIGH_STAKES       # only HIGH_STAKES prompts
        else:
            # strict (default)
            threshold = RiskTier.IRREVERSIBLE      # IRREVERSIBLE + HIGH_STAKES prompt

        # An unclassified tool is never auto-allowed, whatever the threshold is.
        classified = self.is_classified(tool_name, inputs)
        if tier < threshold and classified:
            return True

        # Needs confirmation
        tier_label = {
            RiskTier.IRREVERSIBLE: "IRREVERSIBLE",
            RiskTier.HIGH_STAKES:  "HIGH-STAKES",
        }.get(tier, tier.name)
        if not classified:
            tier_label = f"UNCLASSIFIED/{tier_label}"

        _safe_print(f"\n[CATO SAFETY] {tier_label} action requested:")
        _safe_print(f"  Tool:   {tool_name}")
        # Show a sanitised subset of inputs (skip long values)
        short_inputs = {
            k: (str(v)[:120] + "..." if len(str(v)) > 120 else v)
            for k, v in inputs.items()
        }
        _safe_print(f"  Inputs: {short_inputs}")

        if not _is_interactive():
            # Daemon mode — no TTY to prompt.
            #
            # Denying outright here is what made the out-of-band approval flow
            # UNREACHABLE in production (t14): Cato ships safety_mode=strict and
            # runs headless, so every HIGH_STAKES/IRREVERSIBLE tool — genesis,
            # file.write, github.issue_create, destructive shell — was refused
            # at this gate and never reached the approval gate that a human
            # actually answers on Telegram.
            #
            # So: defer, but only when deferring is provably not a downgrade.
            # `_defers_to_approval_gate` returns True only for a POSITIVELY
            # CLASSIFIED tool that the declarative policy says requires an
            # approval ticket — the exact predicate the approval gate itself
            # uses (cato/agent_loop.py::_maybe_gate_outbound_tool). Anything it
            # lets past here is therefore guaranteed to be held for a human,
            # who gets a stronger control than a y/N prompt: an HMAC-signed,
            # argument-bound, single-use ticket.
            #
            # Unclassified tools and tools the policy does NOT gate are still
            # denied outright — for those, no downstream gate would catch them.
            if self._defers_to_approval_gate(tool_name, inputs):
                logger.info(
                    "Safety check: non-interactive context; deferring %s to the "
                    "human approval gate (policy requires an approval ticket).",
                    tool_name,
                )
                _safe_print(
                    "[CATO SAFETY] Non-interactive context: held for out-of-band "
                    "human approval."
                )
                return True
            # `_is_interactive` also returns False when stdin is None or raises
            # (pythonw, detached service), so there is no path where a broken
            # console turns into an allow.
            logger.warning("Safety check: non-interactive context, denying %s by default.", tool_name)
            _safe_print("[CATO SAFETY] Non-interactive context: action denied by default.")
            return False
        try:
            answer = input("Proceed? [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            _safe_print("\nAborted.")
            return False

        if answer in ("y", "yes"):
            logger.info("User approved %s action: %s", tier_label, tool_name)
            return True

        logger.info("User denied %s action: %s", tier_label, tool_name)
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_interactive() -> bool:
    """True only when there is a real TTY we can prompt on.

    A detached daemon has no stdin at all (``sys.stdin is None`` under pythonw
    and some service wrappers), and a closed stream raises on ``isatty()``.
    Both must read as "cannot ask the human", i.e. deny.
    """
    import sys
    stdin = getattr(sys, "stdin", None)
    if stdin is None:
        return False
    try:
        return bool(stdin.isatty())
    except Exception:
        return False


def _safe_print(text: str) -> None:
    """Print using platform-safe print if available, else fallback."""
    try:
        from .platform import safe_print
        safe_print(text)
    except Exception:
        print(text)

"""
cato/audit/action_guard.py — Pre-action Guard (part of Unbuilt Skill 8).

Checks reversibility + autonomy level before any tool is executed.
When a TokenChecker is provided and delegation token authorizes the action,
the guard may allow execution without reversibility confirmation.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Optional

from .reversibility_registry import ReversibilityRegistry, ToolNotRegistered

if TYPE_CHECKING:
    from cato.auth.token_checker import TokenChecker


@dataclass
class GuardDecision:
    proceed: bool
    requires_confirmation: bool
    reason: str
    applied_checks: list[str] = field(default_factory=list)


class ActionGuard:
    """
    Pre-action guard: consults ReversibilityRegistry and autonomy level
    to decide whether to proceed or require user confirmation.
    Optional TokenChecker: when present and agent_session_id is passed,
    a valid delegation token that authorizes the tool allows execution.

    autonomy_level: 0.0 = fully supervised, 1.0 = fully autonomous
    """

    def __init__(
        self,
        registry: ReversibilityRegistry | None = None,
        token_checker: Optional["TokenChecker"] = None,
    ) -> None:
        self._registry = registry or ReversibilityRegistry.get_instance()
        self._token_checker = token_checker

    def check_before_execute(
        self,
        tool_name: str,
        tool_input: dict[str, Any],
        current_autonomy_level: float = 0.5,
        agent_session_id: Optional[str] = None,
        estimated_cost: float = 0.0,
    ) -> GuardDecision:
        applied: list[str] = []

        # If TokenChecker is configured and we have a session, check delegation token first
        if self._token_checker and agent_session_id:
            auth = self._token_checker.check_authorization(
                tool_name, tool_input, agent_session_id, estimated_cost
            )
            if auth.authorized and auth.token_id:
                applied.append(f"token_authorized token_id={auth.token_id[:8] if auth.token_id else '?'}…")
                return GuardDecision(
                    proceed=True,
                    requires_confirmation=False,
                    reason=auth.reason,
                    applied_checks=applied,
                )
            if not auth.authorized and auth.requires_user_confirmation:
                applied.append("token_scope_insufficient")
                return GuardDecision(
                    proceed=False,
                    requires_confirmation=True,
                    reason=auth.reason,
                    applied_checks=applied,
                )

        try:
            entry = self._registry.get(tool_name)
            rev = entry.reversibility
        except ToolNotRegistered:
            rev = 0.5  # Conservative default for unknown tools
            applied.append("unknown_tool_default_0.5")

        # Rule 1: always require confirmation for highly irreversible actions
        if rev > 0.9:
            applied.append(f"reversibility={rev:.2f}>0.9 always_confirm")
            return GuardDecision(
                proceed=False,
                requires_confirmation=True,
                reason=(
                    f"Action '{tool_name}' is nearly irreversible (score={rev:.2f}). "
                    "Explicit confirmation required regardless of autonomy level."
                ),
                applied_checks=applied,
            )

        # Rule 2: high reversibility + low autonomy
        if rev > 0.7 and current_autonomy_level < 0.8:
            applied.append(
                f"reversibility={rev:.2f}>0.7, autonomy={current_autonomy_level:.2f}<0.8"
            )
            return GuardDecision(
                proceed=False,
                requires_confirmation=True,
                reason=(
                    f"Action '{tool_name}' has high reversibility risk (score={rev:.2f}) "
                    f"and autonomy level ({current_autonomy_level:.2f}) is below 0.8."
                ),
                applied_checks=applied,
            )

        # Rule 3: medium reversibility + low autonomy
        if rev > 0.5 and current_autonomy_level < 0.5:
            applied.append(
                f"reversibility={rev:.2f}>0.5, autonomy={current_autonomy_level:.2f}<0.5"
            )
            return GuardDecision(
                proceed=False,
                requires_confirmation=True,
                reason=(
                    f"Action '{tool_name}' carries moderate irreversibility (score={rev:.2f}) "
                    f"and autonomy is low ({current_autonomy_level:.2f})."
                ),
                applied_checks=applied,
            )

        applied.append(
            f"reversibility={rev:.2f} cleared at autonomy={current_autonomy_level:.2f}"
        )
        return GuardDecision(
            proceed=True,
            requires_confirmation=False,
            reason=(
                f"Action '{tool_name}' cleared pre-action guard "
                f"(reversibility={rev:.2f}, autonomy={current_autonomy_level:.2f})."
            ),
            applied_checks=applied,
        )

"""
cato/audit/reversibility_registry.py — Irreversibility Classifier (Unbuilt Skill 8).

Static registry mapping tool names to reversibility scores (0.0 = fully reversible,
1.0 = fully irreversible). Pre-action check applies proportional caution.
"""
from __future__ import annotations
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Optional


class BlastRadius(str, Enum):
    SELF = "self"
    SINGLE_USER = "single_user"
    MULTI_USER = "multi_user"
    PUBLIC = "public"


@dataclass
class ReversibilityEntry:
    tool_name: str
    reversibility: float          # 0.0 = reversible, 1.0 = irreversible
    recovery_time: str            # e.g. "instant", "minutes", "hours", "irreversible"
    blast_radius: BlastRadius
    notes: str = ""


class ToolNotRegistered(KeyError):
    pass


class ReversibilityRegistry:
    _instance: Optional["ReversibilityRegistry"] = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        self._registry: dict[str, ReversibilityEntry] = {}
        self._populate_builtins()

    @classmethod
    def get_instance(cls) -> "ReversibilityRegistry":
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def _populate_builtins(self) -> None:
        builtins = [
            ("read_file",          0.0, "instant",      BlastRadius.SELF,        "Read-only"),
            ("list_dir",           0.0, "instant",      BlastRadius.SELF,        "Read-only"),
            ("web_search",         0.0, "instant",      BlastRadius.SELF,        "Read-only"),
            ("memory_search",      0.0, "instant",      BlastRadius.SELF,        "Read-only"),
            ("write_file",         0.3, "minutes",      BlastRadius.SINGLE_USER, "Reversible with backup"),
            ("edit_file",          0.3, "minutes",      BlastRadius.SINGLE_USER, "Reversible with backup"),
            ("delete_file",        0.8, "hours",        BlastRadius.SINGLE_USER, "Recoverable if not overwritten"),
            ("git_commit",         0.7, "hours",        BlastRadius.MULTI_USER,  "Hard to undo on shared repos"),
            ("git_push",           0.7, "hours",        BlastRadius.MULTI_USER,  "Hard to undo on shared repos"),
            ("email_send",         1.0, "irreversible", BlastRadius.PUBLIC,     "Fully irreversible; recipients are public"),
            ("api_payment",        1.0, "irreversible", BlastRadius.PUBLIC,      "Fully irreversible"),
            ("shell_execute",      0.6, "minutes",      BlastRadius.SINGLE_USER, "Command-dependent; conservative default"),
            ("conduit_navigate",   0.0, "instant",      BlastRadius.SELF,        "Navigation only"),
            ("conduit_extract",    0.0, "instant",      BlastRadius.SELF,        "Extraction only"),
            ("conduit_click",      0.5, "minutes",      BlastRadius.SINGLE_USER, "May trigger server-side effects"),
            ("conduit_type",       0.5, "minutes",      BlastRadius.SINGLE_USER, "May trigger server-side effects"),
        ]
        for tool_name, rev, rec_time, blast, notes in builtins:
            self._registry[tool_name] = ReversibilityEntry(
                tool_name=tool_name,
                reversibility=rev,
                recovery_time=rec_time,
                blast_radius=blast,
                notes=notes,
            )

    def register(
        self,
        tool_name: str,
        reversibility: float,
        recovery_time: str,
        blast_radius: "BlastRadius | str",
        notes: str = "",
    ) -> None:
        if isinstance(blast_radius, str):
            blast_radius = BlastRadius(blast_radius)
        self._registry[tool_name] = ReversibilityEntry(
            tool_name=tool_name,
            reversibility=float(reversibility),
            recovery_time=recovery_time,
            blast_radius=blast_radius,
            notes=notes,
        )

    def get(self, tool_name: str) -> ReversibilityEntry:
        entry = self._registry.get(tool_name)
        if entry is None:
            raise ToolNotRegistered(
                f"Tool not registered: {tool_name!r}. Caller should default to 0.5."
            )
        return entry

    def list_all(self) -> list[ReversibilityEntry]:
        return sorted(
            self._registry.values(), key=lambda e: e.reversibility, reverse=True
        )

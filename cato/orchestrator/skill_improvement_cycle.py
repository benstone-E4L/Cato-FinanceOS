"""
cato/orchestrator/skill_improvement_cycle.py — Self-Improving Agent (Skill 1).

Records corrections into a structured ledger, uses 3-model consensus before
rewriting any skill, cryptographic rollback on every version.

Requires:
- QMD retrieval (Phase D Skill 4)
- Knowledge Graph (Skill 9)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ..core.memory import MemorySystem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Correction signals
# ---------------------------------------------------------------------------

_CORRECTION_PREFIXES = (
    "no,", "no ", "wrong", "actually", "that's incorrect", "thats incorrect",
    "incorrect", "not right", "you're wrong", "youre wrong", "that is wrong",
    "that is incorrect", "that is not", "that's not", "thats not",
)

_CODE_BLOCK_RE = None


def _get_code_block_re():
    """Lazy-compile the code block regex."""
    global _CODE_BLOCK_RE
    if _CODE_BLOCK_RE is None:
        import re
        _CODE_BLOCK_RE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
    return _CODE_BLOCK_RE


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def classify_correction(user_message: str, prior_output: str) -> Optional[dict]:
    """
    Detect whether *user_message* is a correction of *prior_output*.

    Returns a dict with keys:
        task_type, wrong_approach, correct_approach, context_hash

    Returns None if no correction detected.
    """
    msg_lower = user_message.lower().strip()

    correction_detected = False
    task_type = "general"

    # Signal 1: message starts with correction phrase
    for prefix in _CORRECTION_PREFIXES:
        if msg_lower.startswith(prefix):
            correction_detected = True
            break

    # Signal 2: prior output has code block, message also has code block (rewrite)
    if not correction_detected:
        code_re = _get_code_block_re()
        prior_blocks = code_re.findall(prior_output)
        msg_blocks = code_re.findall(user_message)
        if prior_blocks and msg_blocks:
            correction_detected = True
            task_type = "code_rewrite"

    # Signal 3: message explicitly says prior was corrected
    correction_signals = [
        "should be", "should have", "the correct", "the right way",
        "instead you should", "you should have", "use this instead",
        "fix:", "correction:", "actually it's", "actually its",
    ]
    if not correction_detected:
        for signal in correction_signals:
            if signal in msg_lower:
                correction_detected = True
                break

    if not correction_detected:
        return None

    # Build context hash from first 200 chars of prior output
    context_snippet = prior_output[:200]
    context_hash = hashlib.sha256(context_snippet.encode("utf-8")).hexdigest()

    return {
        "task_type": task_type,
        "wrong_approach": prior_output[:500],
        "correct_approach": user_message[:500],
        "context_hash": context_hash,
    }


def store_correction(
    correction: dict,
    session_id: str,
    memory: "MemorySystem",
) -> int:
    """
    Store a correction record in the `corrections` table.

    Returns the row id.
    """
    now = time.time()
    with memory._write_lock:
        cur = memory._conn.execute(
            "INSERT INTO corrections"
            " (task_type, wrong_approach, correct_approach, context_hash, session_id, timestamp)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (
                correction["task_type"],
                correction["wrong_approach"],
                correction["correct_approach"],
                correction["context_hash"],
                session_id,
                now,
            ),
        )
        memory._conn.commit()
    return cur.lastrowid


def get_corrections_for_context(
    context_hash: str,
    memory: "MemorySystem",
    top_k: int = 3,
) -> list[dict]:
    """
    Retrieve matching corrections by context_hash from SQLite.
    """
    rows = memory._conn.execute(
        "SELECT id, task_type, wrong_approach, correct_approach, context_hash, session_id, timestamp"
        " FROM corrections WHERE context_hash = ?"
        " ORDER BY timestamp DESC LIMIT ?",
        (context_hash, top_k),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Skill Version Manager
# ---------------------------------------------------------------------------


def backup_skill(
    skill_name: str,
    skill_path: Path,
    memory: "MemorySystem",
) -> str:
    """
    Read current SKILL.md, compute SHA-256, store in skill_versions table.

    Returns the content hash.
    """
    content = skill_path.read_text(encoding="utf-8", errors="replace")
    content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
    now = time.time()
    with memory._write_lock:
        memory._conn.execute(
            "INSERT INTO skill_versions (skill_name, content_hash, content, timestamp)"
            " VALUES (?, ?, ?, ?)",
            (skill_name, content_hash, content, now),
        )
        memory._conn.commit()
    logger.info("Backed up skill %s (hash=%s)", skill_name, content_hash[:8])
    return content_hash


def restore_skill(
    skill_name: str,
    content_hash: str,
    skill_path: Path,
    memory: "MemorySystem",
) -> bool:
    """
    Restore a skill file from stored content identified by content_hash.

    Returns True if restored, False if hash not found.
    """
    row = memory._conn.execute(
        "SELECT content FROM skill_versions"
        " WHERE skill_name = ? AND content_hash = ?"
        " ORDER BY timestamp DESC LIMIT 1",
        (skill_name, content_hash),
    ).fetchone()
    if row is None:
        logger.warning("No backup found for skill %s hash=%s", skill_name, content_hash[:8])
        return False
    skill_path.parent.mkdir(parents=True, exist_ok=True)
    skill_path.write_text(row["content"], encoding="utf-8")
    logger.info("Restored skill %s from hash=%s", skill_name, content_hash[:8])
    return True


def list_skill_versions(
    skill_name: str,
    memory: "MemorySystem",
) -> list[dict]:
    """
    List all stored versions for a skill, newest first.
    """
    rows = memory._conn.execute(
        "SELECT id, skill_name, content_hash, timestamp"
        " FROM skill_versions WHERE skill_name = ?"
        " ORDER BY timestamp DESC",
        (skill_name,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# 3-Model Consensus Review
# ---------------------------------------------------------------------------


async def run_improvement_cycle(
    memory: "MemorySystem",
    allow_writes: bool = False,
) -> dict:
    """
    Nightly batch improvement cycle.

    1. Find context_hash values with >= 2 corrections.
    2. For each candidate batch, build an improvement prompt.
    3. Dispatch to claude + codex + gemini in parallel via _invoke_single_model.
    4. Check 2/3 agreement using extract_confidence + simple_synthesis.
    5. If consensus score >= 0.7 and allow_writes=True: backup + rewrite SKILL.md.

    Returns stats dict: {candidates_reviewed, skills_updated, blocked}.
    """
    from ..tools.github_tool import _invoke_single_model
    from ..orchestrator.confidence_extractor import extract_confidence
    from ..orchestrator.synthesis import simple_synthesis

    # Find candidates with >= 2 occurrences of same context_hash
    rows = memory._conn.execute(
        "SELECT context_hash, task_type, COUNT(*) as cnt,"
        " GROUP_CONCAT(correct_approach, ' | ') as approaches"
        " FROM corrections"
        " GROUP BY context_hash"
        " HAVING cnt >= 2"
        " ORDER BY cnt DESC"
    ).fetchall()

    candidates_reviewed = 0
    skills_updated = 0
    blocked = 0

    for row in rows:
        candidates_reviewed += 1
        context_hash = row["context_hash"]
        task_type = row["task_type"]
        approaches = row["approaches"] or ""

        prompt = (
            f"You are reviewing repeated correction patterns for task type: {task_type}.\n"
            f"The following correct approaches were recorded:\n{approaches[:2000]}\n\n"
            f"Propose a concise improvement (1-2 sentences) for the relevant skill documentation."
            f" Rate your confidence 0.0-1.0."
        )

        # Dispatch 3 models in parallel
        try:
            results = await asyncio.gather(
                _invoke_single_model("claude", prompt, {}),
                _invoke_single_model("codex", prompt, {}),
                _invoke_single_model("gemini", prompt, {}),
                return_exceptions=True,
            )
        except Exception as exc:
            logger.warning("Model dispatch failed for hash=%s: %s", context_hash[:8], exc)
            blocked += 1
            continue

        # Filter out exceptions
        valid_results = [
            r for r in results if isinstance(r, dict)
        ]
        if len(valid_results) < 2:
            blocked += 1
            continue

        # Re-extract confidence scores (models may have embedded them)
        for r in valid_results:
            if r.get("confidence", 0.0) == 0.0:
                r["confidence"] = extract_confidence(r.get("response", ""))

        # Pad to 3 results if fewer models responded
        _empty = {"model": "n/a", "response": "", "confidence": 0.0, "latency_ms": 0}
        padded = (valid_results + [_empty, _empty, _empty])[:3]
        synthesis = simple_synthesis(padded[0], padded[1], padded[2])
        consensus_score = synthesis.get("primary", {}).get("confidence", 0.0)

        if consensus_score < 0.7:
            logger.info(
                "Candidate hash=%s blocked (consensus=%.2f < 0.7)",
                context_hash[:8],
                consensus_score,
            )
            blocked += 1
            continue

        if not allow_writes:
            logger.info(
                "Candidate hash=%s: consensus=%.2f — skipping write (allow_writes=False)",
                context_hash[:8],
                consensus_score,
            )
            continue

        # Find the relevant skill path — scan skills directory
        skills_base = Path(__file__).parent.parent / "skills"
        skill_files = list(skills_base.glob("*/SKILL.md"))
        if not skill_files:
            blocked += 1
            continue

        # Heuristic: pick skill most relevant to task_type
        target_skill: Optional[Path] = None
        for sf in skill_files:
            if task_type.lower() in sf.parent.name.lower():
                target_skill = sf
                break
        if target_skill is None:
            target_skill = skill_files[0]

        skill_name = target_skill.parent.name
        try:
            backup_skill(skill_name, target_skill, memory)
            # Append improvement suggestion as a comment at the end
            improvement_note = synthesis.get("primary", {}).get("response", "")
            existing = target_skill.read_text(encoding="utf-8")
            updated = (
                existing.rstrip()
                + f"\n\n## Auto-Improvement Note (consensus={consensus_score:.2f})\n"
                + improvement_note[:500]
                + "\n"
            )
            target_skill.write_text(updated, encoding="utf-8")
            skills_updated += 1
            logger.info("Updated skill %s (hash=%s)", skill_name, context_hash[:8])
        except Exception as exc:
            logger.warning("Failed to update skill %s: %s", skill_name, exc)
            blocked += 1

    return {
        "candidates_reviewed": candidates_reviewed,
        "skills_updated": skills_updated,
        "blocked": blocked,
    }

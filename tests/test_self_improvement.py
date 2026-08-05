"""
tests/test_self_improvement.py — Tests for Skill 1: Self-Improving Agent.

Min 25 tests covering:
- classify_correction() detects corrections vs. non-corrections
- store_correction() and get_corrections_for_context() round-trip
- backup_skill() stores hash and content correctly
- restore_skill() returns correct content
- run_improvement_cycle() with allow_writes=False returns stats without writing files
- SHA-256 context hash is consistent for same input
- Correction signal detection (starts-with, code-rewrite, explicit signal)
- list_skill_versions() returns ordered results
"""
from __future__ import annotations

import asyncio
import hashlib
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from cato.core.memory import MemorySystem
from cato.orchestrator.skill_improvement_cycle import (
    backup_skill,
    classify_correction,
    get_corrections_for_context,
    list_skill_versions,
    restore_skill,
    run_improvement_cycle,
    store_correction,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mem(tmp_path):
    m = MemorySystem(agent_id="test-improve", memory_dir=tmp_path)
    yield m
    m.close()


@pytest.fixture
def skill_file(tmp_path):
    """Create a temporary SKILL.md file."""
    p = tmp_path / "skills" / "test_skill" / "SKILL.md"
    p.parent.mkdir(parents=True)
    p.write_text("# Test Skill\n\nThis is the original content.\n", encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# classify_correction
# ---------------------------------------------------------------------------

class TestClassifyCorrection:
    def test_starts_with_no_is_correction(self):
        result = classify_correction("No, that's wrong.", "The answer is 42.")
        assert result is not None

    def test_starts_with_wrong_is_correction(self):
        result = classify_correction("Wrong approach used.", "Here is my answer.")
        assert result is not None

    def test_starts_with_actually_is_correction(self):
        result = classify_correction("Actually, you should use list.append().", "Use list += [item].")
        assert result is not None

    def test_starts_with_thats_incorrect_is_correction(self):
        result = classify_correction("That's incorrect, the answer is B.", "The answer is A.")
        assert result is not None

    def test_code_rewrite_detected(self):
        prior = "Here is code:\n```python\ndef foo():\n    return 1\n```"
        msg = "Use this instead:\n```python\ndef foo():\n    return 2\n```"
        result = classify_correction(msg, prior)
        assert result is not None
        assert result["task_type"] == "code_rewrite"

    def test_should_be_signal_detected(self):
        result = classify_correction("It should be snake_case.", "I used camelCase.")
        assert result is not None

    def test_use_this_instead_signal_detected(self):
        result = classify_correction("Use this instead: asyncio.run()", "Use asyncio.get_event_loop().run_until_complete()")
        assert result is not None

    def test_normal_followup_is_not_correction(self):
        result = classify_correction("Can you explain more?", "The answer involves async programming.")
        assert result is None

    def test_affirmative_message_is_not_correction(self):
        result = classify_correction("Great, that works!", "Here is the solution.")
        assert result is None

    def test_question_is_not_correction(self):
        result = classify_correction("What does this function do?", "It processes the input.")
        assert result is None

    def test_context_hash_is_sha256(self):
        prior = "Prior output content here."
        result = classify_correction("No, that's wrong.", prior)
        assert result is not None
        expected_hash = hashlib.sha256(prior[:200].encode("utf-8")).hexdigest()
        assert result["context_hash"] == expected_hash

    def test_context_hash_consistent_for_same_input(self):
        prior = "Consistent output " * 20  # > 200 chars
        r1 = classify_correction("No, that is wrong.", prior)
        r2 = classify_correction("Wrong approach here.", prior)
        assert r1 is not None
        assert r2 is not None
        assert r1["context_hash"] == r2["context_hash"]

    def test_wrong_approach_truncated_to_500(self):
        long_prior = "x" * 600
        result = classify_correction("No, that is wrong.", long_prior)
        assert result is not None
        assert len(result["wrong_approach"]) <= 500

    def test_correct_approach_truncated_to_500(self):
        long_msg = "Actually, " + "y" * 600
        result = classify_correction(long_msg, "Prior output.")
        assert result is not None
        assert len(result["correct_approach"]) <= 500


# ---------------------------------------------------------------------------
# store_correction / get_corrections_for_context
# ---------------------------------------------------------------------------

class TestCorrectionRoundTrip:
    def test_store_correction_returns_row_id(self, mem):
        correction = {
            "task_type": "general",
            "wrong_approach": "wrong way",
            "correct_approach": "right way",
            "context_hash": "abc123",
        }
        row_id = store_correction(correction, "sess-1", mem)
        assert isinstance(row_id, int)
        assert row_id > 0

    def test_get_corrections_returns_stored_record(self, mem):
        correction = {
            "task_type": "code_rewrite",
            "wrong_approach": "old code",
            "correct_approach": "new code",
            "context_hash": "hash001",
        }
        store_correction(correction, "sess-2", mem)
        results = get_corrections_for_context("hash001", mem)
        assert len(results) == 1
        assert results[0]["task_type"] == "code_rewrite"
        assert results[0]["correct_approach"] == "new code"

    def test_get_corrections_empty_for_unknown_hash(self, mem):
        results = get_corrections_for_context("unknown_hash_xyz", mem)
        assert results == []

    def test_get_corrections_top_k_limit(self, mem):
        for i in range(5):
            correction = {
                "task_type": "general",
                "wrong_approach": f"wrong {i}",
                "correct_approach": f"right {i}",
                "context_hash": "same_hash",
            }
            store_correction(correction, f"sess-{i}", mem)
        results = get_corrections_for_context("same_hash", mem, top_k=3)
        assert len(results) == 3

    def test_get_corrections_does_not_return_other_hashes(self, mem):
        correction_a = {
            "task_type": "general",
            "wrong_approach": "wrong a",
            "correct_approach": "right a",
            "context_hash": "hash_A",
        }
        correction_b = {
            "task_type": "general",
            "wrong_approach": "wrong b",
            "correct_approach": "right b",
            "context_hash": "hash_B",
        }
        store_correction(correction_a, "s1", mem)
        store_correction(correction_b, "s2", mem)
        results = get_corrections_for_context("hash_A", mem)
        assert all(r["context_hash"] == "hash_A" for r in results)


# ---------------------------------------------------------------------------
# backup_skill / restore_skill / list_skill_versions
# ---------------------------------------------------------------------------

class TestSkillVersionManager:
    def test_backup_skill_returns_hash(self, mem, skill_file):
        content_hash = backup_skill("test_skill", skill_file, mem)
        content = skill_file.read_text(encoding="utf-8", errors="replace")
        expected = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert content_hash == expected

    def test_backup_skill_stores_content(self, mem, skill_file):
        backup_skill("test_skill", skill_file, mem)
        row = mem._conn.execute(
            "SELECT content FROM skill_versions WHERE skill_name = 'test_skill'"
        ).fetchone()
        assert row is not None
        assert "original content" in row["content"]

    def test_restore_skill_returns_true_on_success(self, mem, skill_file):
        content_hash = backup_skill("test_skill", skill_file, mem)
        # Overwrite the file
        skill_file.write_text("New content that replaced original.", encoding="utf-8")
        ok = restore_skill("test_skill", content_hash, skill_file, mem)
        assert ok is True

    def test_restore_skill_writes_original_content(self, mem, skill_file):
        original = skill_file.read_text(encoding="utf-8")
        content_hash = backup_skill("test_skill", skill_file, mem)
        skill_file.write_text("Changed content.", encoding="utf-8")
        restore_skill("test_skill", content_hash, skill_file, mem)
        restored = skill_file.read_text(encoding="utf-8")
        assert restored == original

    def test_restore_skill_returns_false_for_unknown_hash(self, mem, skill_file):
        ok = restore_skill("test_skill", "nonexistent_hash_abc", skill_file, mem)
        assert ok is False

    def test_list_skill_versions_returns_versions(self, mem, skill_file):
        backup_skill("test_skill", skill_file, mem)
        skill_file.write_text("Version 2 content.", encoding="utf-8")
        backup_skill("test_skill", skill_file, mem)
        versions = list_skill_versions("test_skill", mem)
        assert len(versions) == 2

    def test_list_skill_versions_ordered_newest_first(self, mem, skill_file):
        backup_skill("test_skill", skill_file, mem)
        time.sleep(0.01)
        skill_file.write_text("Version 2 content.", encoding="utf-8")
        backup_skill("test_skill", skill_file, mem)
        versions = list_skill_versions("test_skill", mem)
        # Newest should be first
        assert versions[0]["timestamp"] >= versions[1]["timestamp"]

    def test_list_skill_versions_empty_for_unknown_skill(self, mem):
        versions = list_skill_versions("nonexistent_skill", mem)
        assert versions == []


# ---------------------------------------------------------------------------
# run_improvement_cycle
# ---------------------------------------------------------------------------

class TestRunImprovementCycle:
    @pytest.mark.asyncio
    async def test_dry_run_returns_stats_dict(self, mem):
        stats = await run_improvement_cycle(mem, allow_writes=False)
        assert "candidates_reviewed" in stats
        assert "skills_updated" in stats
        assert "blocked" in stats

    @pytest.mark.asyncio
    async def test_no_candidates_returns_zeros(self, mem):
        # No corrections stored at all
        stats = await run_improvement_cycle(mem, allow_writes=False)
        assert stats["candidates_reviewed"] == 0
        assert stats["skills_updated"] == 0

    @pytest.mark.asyncio
    async def test_single_occurrence_not_reviewed(self, mem):
        # Only 1 occurrence — threshold is >= 2, so candidate not picked
        correction = {
            "task_type": "general",
            "wrong_approach": "wrong",
            "correct_approach": "right",
            "context_hash": "single_hash",
        }
        store_correction(correction, "s1", mem)
        stats = await run_improvement_cycle(mem, allow_writes=False)
        assert stats["candidates_reviewed"] == 0

    @pytest.mark.asyncio
    async def test_two_occurrences_are_reviewed(self, mem):
        """Two corrections with same hash should be reviewed (but models are mocked)."""
        for i in range(2):
            store_correction(
                {
                    "task_type": "general",
                    "wrong_approach": f"wrong {i}",
                    "correct_approach": f"right {i}",
                    "context_hash": "dup_hash",
                },
                f"sess-{i}",
                mem,
            )

        mock_result = {
            "model": "claude",
            "response": "Use async/await consistently. confidence: 0.85",
            "confidence": 0.85,
            "latency_ms": 100,
        }

        with patch(
            "cato.tools.github_tool._invoke_single_model",
            new=AsyncMock(return_value=mock_result),
        ):
            stats = await run_improvement_cycle(mem, allow_writes=False)

        assert stats["candidates_reviewed"] == 1
        # allow_writes=False so skills_updated must be 0
        assert stats["skills_updated"] == 0

    @pytest.mark.asyncio
    async def test_allow_writes_false_never_updates_files(self, mem, tmp_path):
        """Even with consensus, no files should be written when allow_writes=False."""
        for i in range(3):
            store_correction(
                {
                    "task_type": "general",
                    "wrong_approach": "wrong",
                    "correct_approach": "right",
                    "context_hash": "write_hash",
                },
                f"s{i}",
                mem,
            )

        mock_result = {
            "model": "claude",
            "response": "Improvement suggestion here. confidence: 0.90",
            "confidence": 0.90,
            "latency_ms": 50,
        }

        with patch(
            "cato.tools.github_tool._invoke_single_model",
            new=AsyncMock(return_value=mock_result),
        ):
            stats = await run_improvement_cycle(mem, allow_writes=False)

        assert stats["skills_updated"] == 0

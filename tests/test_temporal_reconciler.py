"""
tests/test_temporal_reconciler.py — Tests for Temporal Context Reconciliation (Skill 6).
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cato.context.volatility_map import VolatilityMap, classify_url
from cato.context.temporal_reconciler import TemporalReconciler, WakeupBriefing


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def vmap() -> VolatilityMap:
    return VolatilityMap()


@pytest.fixture
def tr(tmp_path: Path) -> TemporalReconciler:
    reconciler = TemporalReconciler(db_path=tmp_path / "test_temporal.db")
    yield reconciler
    reconciler.close()


# ---------------------------------------------------------------------------
# VolatilityMap
# ---------------------------------------------------------------------------

def test_github_issues_volatility(vmap: VolatilityMap) -> None:
    score = vmap.get_volatility("https://github.com/org/repo/issues/1")
    assert score == 0.9


def test_arxiv_volatility(vmap: VolatilityMap) -> None:
    score = vmap.get_volatility("https://arxiv.org/abs/1234.5678")
    assert score == 0.1


def test_unknown_url_defaults_to_web_page_article(vmap: VolatilityMap) -> None:
    score = vmap.get_volatility("https://unknown.example.com/some/page")
    assert score == 0.5


def test_classify_url_github_issues() -> None:
    domain_type = classify_url("https://github.com/foo/bar/issues/42")
    assert domain_type == "github_issues"


def test_classify_url_arxiv() -> None:
    domain_type = classify_url("https://arxiv.org/abs/2301.00001")
    assert domain_type == "arxiv_paper"


def test_classify_url_github_code() -> None:
    domain_type = classify_url("https://github.com/org/repo")
    assert domain_type == "github_code"


def test_classify_url_news_rss() -> None:
    domain_type = classify_url("https://example.com/rss/feed.xml")
    assert domain_type == "news_rss"


def test_classify_url_local_file() -> None:
    domain_type = classify_url("/home/user/document.txt")
    assert domain_type == "local_file"


def test_volatility_map_set_override(vmap: VolatilityMap) -> None:
    vmap.set_override("arxiv_paper", 0.8)
    score = vmap.get_volatility("https://arxiv.org/abs/1234")
    assert score == 0.8


def test_volatility_map_override_in_constructor() -> None:
    vm = VolatilityMap(overrides={"github_issues": 0.99})
    score = vm.get_volatility("https://github.com/foo/bar/issues/1")
    assert score == 0.99


# ---------------------------------------------------------------------------
# TemporalReconciler — snapshot_task / get_snapshot / delete_snapshot
# ---------------------------------------------------------------------------

def test_snapshot_task_stores_task(tr: TemporalReconciler) -> None:
    tr.snapshot_task("task-001", "Deploy the service", ["https://github.com/org/repo/issues/5"])
    snap = tr.get_snapshot("task-001")
    assert snap is not None
    assert snap["task_id"] == "task-001"
    assert snap["description"] == "Deploy the service"


def test_get_snapshot_returns_correct_dependencies(tr: TemporalReconciler) -> None:
    deps = ["https://github.com/org/repo/issues/1", "https://arxiv.org/abs/1234"]
    tr.snapshot_task("task-deps", "Research task", deps)
    snap = tr.get_snapshot("task-deps")
    assert snap["external_dependencies"] == deps


def test_get_snapshot_returns_none_for_missing(tr: TemporalReconciler) -> None:
    snap = tr.get_snapshot("nonexistent-task-id")
    assert snap is None


def test_delete_snapshot_returns_true_for_existing(tr: TemporalReconciler) -> None:
    tr.snapshot_task("task-del", "To be deleted", [])
    result = tr.delete_snapshot("task-del")
    assert result is True


def test_delete_snapshot_returns_false_for_missing(tr: TemporalReconciler) -> None:
    result = tr.delete_snapshot("nonexistent-task-delete")
    assert result is False


def test_delete_snapshot_removes_from_db(tr: TemporalReconciler) -> None:
    tr.snapshot_task("task-gone", "Gone", [])
    tr.delete_snapshot("task-gone")
    assert tr.get_snapshot("task-gone") is None


# ---------------------------------------------------------------------------
# TemporalReconciler — reconcile
# ---------------------------------------------------------------------------

def test_reconcile_returns_wakeup_briefing(tr: TemporalReconciler) -> None:
    briefing = tr.reconcile(0)
    assert isinstance(briefing, WakeupBriefing)


def test_reconcile_zero_dormancy_duration(tr: TemporalReconciler) -> None:
    briefing = tr.reconcile(0)
    assert briefing.dormancy_duration == "0s"


def test_reconcile_no_snapshots_returns_empty_briefing(tr: TemporalReconciler) -> None:
    briefing = tr.reconcile(3600)
    assert briefing.total_dependencies_checked == 0
    assert briefing.total_changes_found == 0
    assert briefing.tasks_unblocked == []
    assert briefing.tasks_now_constrained == []
    assert briefing.changes_requiring_replanning == []


def test_reconcile_checks_high_volatility_deps(tr: TemporalReconciler) -> None:
    # GitHub issues URL has volatility 0.9 > 0.4 threshold
    tr.snapshot_task("task-hv", "High volatility task", ["https://github.com/org/repo/issues/99"])
    briefing = tr.reconcile(3600)
    assert briefing.total_dependencies_checked >= 1
    assert briefing.total_changes_found >= 1


def test_reconcile_skips_low_volatility_deps(tr: TemporalReconciler) -> None:
    # arxiv.org has volatility 0.1 <= 0.4 threshold — should be checked but not flagged as change
    tr.snapshot_task("task-lv", "Low volatility task", ["https://arxiv.org/abs/1234"])
    briefing = tr.reconcile(3600)
    # Deps checked, but no changes (volatility 0.1 <= 0.8 change threshold)
    assert briefing.total_dependencies_checked >= 1
    assert briefing.total_changes_found == 0


def test_reconcile_increments_total_deps_per_dep(tr: TemporalReconciler) -> None:
    tr.snapshot_task("task-multi", "Multi-dep task", [
        "https://github.com/org/repo/issues/1",
        "https://arxiv.org/abs/1234",
    ])
    briefing = tr.reconcile(100)
    assert briefing.total_dependencies_checked == 2


# ---------------------------------------------------------------------------
# _format_duration
# ---------------------------------------------------------------------------

def test_format_duration_seconds(tr: TemporalReconciler) -> None:
    assert tr._format_duration(30) == "30s"


def test_format_duration_minutes(tr: TemporalReconciler) -> None:
    assert tr._format_duration(90) == "2m"


def test_format_duration_hours(tr: TemporalReconciler) -> None:
    result = tr._format_duration(3700)
    # 3700/3600 = 1.027... -> "1.0h" with .1f formatting
    assert result == "1.0h"


def test_format_duration_days(tr: TemporalReconciler) -> None:
    result = tr._format_duration(90000)
    # 90000/86400 = 1.041... -> "1.0d"
    assert result == "1.0d"

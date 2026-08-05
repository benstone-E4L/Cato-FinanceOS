"""
CLI integration tests for coding-agent command.
"""

import json
import pytest
from unittest.mock import patch

from cato.commands.coding_agent_cmd import cmd_coding_agent_sync


async def _fake_subprocess(args, timeout_sec=60.0):
    """Mock subprocess that returns instantly with a fake response."""
    return "Mock analysis complete. The code looks good. [confidence: 0.82]"


@pytest.fixture(autouse=True)
def mock_cli_subprocess():
    """Prevent real CLI calls in all tests — use mock subprocess."""
    with patch(
        'cato.orchestrator.cli_invoker._run_subprocess_async',
        side_effect=_fake_subprocess,
    ):
        yield


def test_cli_coding_agent_basic():
    """Test basic CLI invocation."""
    result = cmd_coding_agent_sync(
        task="test function",
        context="def test(): pass"
    )

    # Parse result
    result_dict = json.loads(result)

    # Verify structure
    assert result_dict.get("status") == "success"
    assert "synthesis" in result_dict
    assert "metrics" in result_dict


def test_cli_coding_agent_with_verbose():
    """Test CLI with verbose flag."""
    result = cmd_coding_agent_sync(
        task="analyze code",
        context="def analyze(data): return sum(data)",
        verbose=True
    )

    result_dict = json.loads(result)
    assert result_dict.get("status") == "success"


def test_cli_coding_agent_synthesis_format():
    """Test synthesis response format."""
    result = cmd_coding_agent_sync(
        task="review code",
        context="def review(): pass"
    )

    result_dict = json.loads(result)
    synthesis = result_dict.get("synthesis", {})

    # Check primary
    primary = synthesis.get("primary", {})
    assert "model" in primary
    assert "response" in primary
    assert "confidence" in primary
    assert 0 <= primary["confidence"] <= 1

    # Check runners-up
    runners_up = synthesis.get("runners_up", [])
    assert isinstance(runners_up, list)
    assert len(runners_up) <= 2

    # Check synthesis note
    assert "synthesis_note" in synthesis


def test_cli_coding_agent_metrics_included():
    """Test that metrics are included in response."""
    result = cmd_coding_agent_sync(
        task="optimize",
        context="def optimize(): pass"
    )

    result_dict = json.loads(result)
    metrics = result_dict.get("metrics", {})

    # Check metric structure
    assert "total_latency_ms" in metrics
    assert "early_termination" in metrics
    assert "elapsed_ms" in metrics

    # Verify types
    assert isinstance(metrics["total_latency_ms"], (int, float))
    assert isinstance(metrics["early_termination"], bool)
    assert isinstance(metrics["elapsed_ms"], (int, float))


def test_cli_coding_agent_latency_under_3s():
    """Test that response latency is under 3 seconds with mocked CLIs."""
    result = cmd_coding_agent_sync(
        task="quick test",
        context="x = 1"
    )

    result_dict = json.loads(result)
    latency_ms = result_dict.get("metrics", {}).get("total_latency_ms", 0)

    assert latency_ms < 3000  # Mocked subprocess returns instantly


def test_cli_coding_agent_context_optional():
    """Test that context is optional."""
    result = cmd_coding_agent_sync(
        task="test without context"
    )

    result_dict = json.loads(result)
    assert result_dict.get("status") == "success"


def test_cli_coding_agent_custom_threshold():
    """Test custom early termination threshold."""
    result = cmd_coding_agent_sync(
        task="test threshold",
        context="def test(): pass",
        threshold=0.95,
        max_wait_ms=2000
    )

    result_dict = json.loads(result)
    assert result_dict.get("status") == "success"


def test_cli_coding_agent_all_models_responded():
    """Test that all 3 models provided responses."""
    result = cmd_coding_agent_sync(
        task="test",
        context="code"
    )

    result_dict = json.loads(result)
    synthesis = result_dict.get("synthesis", {})

    # Should have primary + 2 runners-up
    primary = synthesis.get("primary", {})
    runners_up = synthesis.get("runners_up", [])

    assert len(runners_up) == 2  # All 3 models accounted for


def test_cli_coding_agent_different_tasks():
    """Test various task types."""
    tasks = [
        "optimize this function",
        "find bugs in this code",
        "suggest improvements",
        "review architecture",
    ]

    for task in tasks:
        result = cmd_coding_agent_sync(
            task=task,
            context="def sample(): pass"
        )

        result_dict = json.loads(result)
        assert result_dict.get("status") == "success"
        assert "synthesis" in result_dict


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

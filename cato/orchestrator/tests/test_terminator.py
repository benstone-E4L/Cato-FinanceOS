"""
Unit tests for early_terminator module.
"""

import asyncio
import pytest

from cato.orchestrator.early_terminator import (
    wait_for_threshold,
    wait_for_best_of_n
)


@pytest.mark.asyncio
async def test_wait_for_threshold_immediate_termination():
    """Test early termination when first result meets threshold."""
    queue = asyncio.Queue()

    # Create a task that adds results to queue after delays
    async def add_results():
        await asyncio.sleep(0.01)
        await queue.put({"model": "claude", "confidence": 0.95, "response": "Claude response"})

    # Start the result-adding task
    task = asyncio.create_task(add_results())

    # Wait for threshold
    result = await wait_for_threshold(queue, threshold=0.90, max_wait_ms=5000)

    # Should terminate early with the 0.95 confidence result
    assert result["terminated_early"] == True
    assert result["winner"]["confidence"] == 0.95
    assert result["winner"]["model"] == "claude"
    assert result["elapsed_ms"] > 0

    await task


@pytest.mark.asyncio
async def test_wait_for_threshold_no_early_termination():
    """Test when no result meets threshold (returns best)."""
    queue = asyncio.Queue()

    async def add_results():
        await asyncio.sleep(0.01)
        await queue.put({"model": "claude", "confidence": 0.80, "response": "Claude response"})
        await asyncio.sleep(0.01)
        await queue.put({"model": "codex", "confidence": 0.75, "response": "Codex response"})
        await asyncio.sleep(0.01)
        await queue.put({"model": "gemini", "confidence": 0.70, "response": "Gemini response"})

    task = asyncio.create_task(add_results())

    result = await wait_for_threshold(queue, threshold=0.90, max_wait_ms=5000)

    # Should return best result (0.80) but not early terminate
    assert result["terminated_early"] == False
    assert result["winner"]["confidence"] == 0.80
    assert result["winner"]["model"] == "claude"

    await task


@pytest.mark.asyncio
async def test_wait_for_threshold_timeout():
    """Test timeout behavior."""
    queue = asyncio.Queue()

    async def add_single_result():
        await asyncio.sleep(0.5)  # Delay longer than timeout
        await queue.put({"model": "claude", "confidence": 0.85, "response": "Late response"})

    task = asyncio.create_task(add_single_result())

    result = await wait_for_threshold(queue, threshold=0.90, max_wait_ms=100)

    # Should timeout and return best available (unknown initially)
    assert result["elapsed_ms"] >= 100
    assert result["elapsed_ms"] < 500  # Should not wait for the delayed result

    await task


@pytest.mark.asyncio
async def test_wait_for_threshold_three_results():
    """Test with all 3 results available."""
    queue = asyncio.Queue()

    async def add_results():
        for i, conf in enumerate([0.75, 0.88, 0.82]):
            await asyncio.sleep(0.01)
            await queue.put({
                "model": ["claude", "codex", "gemini"][i],
                "confidence": conf,
                "response": f"Response {i}"
            })

    task = asyncio.create_task(add_results())

    result = await wait_for_threshold(queue, threshold=0.90, max_wait_ms=5000)

    # Should return best (0.88) without early termination
    assert result["terminated_early"] == False
    assert result["winner"]["confidence"] == 0.88

    await task


@pytest.mark.asyncio
async def test_wait_for_best_of_n_sorts_correctly():
    """Test that wait_for_best_of_n returns highest confidence."""
    results = [
        {"model": "claude", "confidence": 0.82},
        {"model": "codex", "confidence": 0.95},
        {"model": "gemini", "confidence": 0.78}
    ]

    result = await wait_for_best_of_n(results, n=3)

    # Should return codex with 0.95
    assert result["winner"]["model"] == "codex"
    assert result["winner"]["confidence"] == 0.95
    assert result["count"] == 3


@pytest.mark.asyncio
async def test_wait_for_best_of_n_empty_list():
    """Test with empty results list."""
    results = []

    result = await wait_for_best_of_n(results, n=3)

    # Should handle gracefully
    assert result["count"] == 0
    assert result["winner"]["confidence"] == 0.0


@pytest.mark.asyncio
async def test_wait_for_best_of_n_partial_results():
    """Test with fewer results than expected."""
    results = [
        {"model": "claude", "confidence": 0.85},
        {"model": "codex", "confidence": 0.90}
    ]

    result = await wait_for_best_of_n(results, n=3)

    # Should return best of available (codex 0.90)
    assert result["winner"]["model"] == "codex"
    assert result["winner"]["confidence"] == 0.90
    assert result["count"] == 2


@pytest.mark.asyncio
async def test_wait_for_threshold_selects_winner():
    """Test that winner is correctly selected and returned."""
    queue = asyncio.Queue()

    async def add_results():
        await asyncio.sleep(0.01)
        await queue.put({
            "model": "claude",
            "confidence": 0.91,
            "response": "High confidence response",
            "latency_ms": 100
        })

    task = asyncio.create_task(add_results())

    result = await wait_for_threshold(queue, threshold=0.90, max_wait_ms=5000)

    # Verify complete winner structure
    assert "winner" in result
    assert result["winner"]["model"] == "claude"
    assert result["winner"]["confidence"] == 0.91
    assert result["winner"]["response"] == "High confidence response"
    assert "latency_ms" in result["winner"]

    await task


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

from __future__ import annotations

from pathlib import Path

from cato.config import CatoConfig
from cato.core.distiller import DistillationResult
from cato.core.memory import MemorySystem
from cato.core.memory_upkeep import (
    AUTO_END,
    AUTO_START,
    MemoryUpkeepService,
    backfill_transcript_learning,
    extract_user_facts,
    merge_memory_markdown,
    sync_memory_markdown,
)


def test_extract_user_facts_picks_plain_english_preference():
    facts = extract_user_facts("Please speak in more plain English. I am Ben.")
    values = {value for _, value, _ in facts}
    assert "Ben prefers plain-English, non-coder explanations." in values
    assert "The user's name is Ben." in values


def test_merge_memory_markdown_preserves_manual_content():
    existing = "# Long-Term Memory\n\n## Durable Facts\n\n- Manual fact.\n"
    merged = merge_memory_markdown(existing, "## Auto-Maintained Memory\n\n- Auto fact.\n")
    assert "Manual fact." in merged
    assert "Auto fact." in merged
    assert AUTO_START in merged
    assert AUTO_END in merged


def test_sync_memory_markdown_indexes_updated_file(tmp_path):
    memory = MemorySystem(agent_id="tester", memory_dir=tmp_path / "mem")
    workspace = tmp_path / "workspace"
    path = sync_memory_markdown(memory, workspace)
    assert path.exists()
    assert AUTO_START in path.read_text(encoding="utf-8")
    results = memory.search("durable learnings", top_k=3)
    assert results


def test_backfill_transcript_learning_adds_fact_and_distillation(tmp_path, monkeypatch):
    transcript = tmp_path / "session.jsonl"
    transcript.write_text(
        "\n".join(
            [
                '{"role":"user","content":"Please use plain English."}',
                '{"role":"assistant","content":"I will use plain English."}',
                '{"role":"user","content":"Task one."}',
                '{"role":"assistant","content":"This is task one."}',
                '{"role":"user","content":"Task two."}',
                '{"role":"assistant","content":"This is task two."}',
                '{"role":"user","content":"Task three."}',
                '{"role":"assistant","content":"This is task three."}',
            ]
        ),
        encoding="utf-8",
    )
    memory = MemorySystem(agent_id="tester", memory_dir=tmp_path / "mem")

    def fake_distill(self, session_id, turns, turn_start=0):
        return DistillationResult(
            session_id=session_id,
            turn_start=turn_start,
            turn_end=turn_start + len(turns) - 1,
            summary="Distilled summary",
            key_facts=["Key fact"],
            decisions=["Decision"],
            open_questions=[],
            embedding=None,
        )

    monkeypatch.setattr("cato.core.memory_upkeep.Distiller.distill", fake_distill)
    facts_added, distillations_added = backfill_transcript_learning(
        memory=memory,
        transcript_path=transcript,
        session_id="session",
        block_size=4,
    )
    assert facts_added >= 1
    assert distillations_added == 2
    assert memory.fact_count() >= 1
    assert len(memory.load_recent_distillations(limit=5)) == 2


def test_memory_upkeep_service_uses_config_workspace_dir(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    sessions = data_dir / "tester" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "abc.jsonl").write_text(
        '{"role":"user","content":"Please use plain English."}\n'
        '{"role":"assistant","content":"I will use plain English."}\n'
        '{"role":"user","content":"Task one."}\n'
        '{"role":"assistant","content":"This is task one."}\n'
        '{"role":"user","content":"Task two."}\n'
        '{"role":"assistant","content":"This is task two."}\n'
        '{"role":"user","content":"Task three."}\n'
        '{"role":"assistant","content":"This is task three."}\n',
        encoding="utf-8",
    )

    def fake_distill(self, session_id, turns, turn_start=0):
        return DistillationResult(
            session_id=session_id,
            turn_start=turn_start,
            turn_end=turn_start + len(turns) - 1,
            summary="The system should preserve plain-English preferences in durable memory.",
            key_facts=["Key fact"],
            decisions=[],
            open_questions=[],
            embedding=None,
        )

    monkeypatch.setattr("cato.core.memory_upkeep.Distiller.distill", fake_distill)
    monkeypatch.setattr("cato.core.memory_upkeep.get_data_dir", lambda: data_dir)

    cfg = CatoConfig(agent_name="tester", workspace_dir=str(tmp_path / "workspace"))
    service = MemoryUpkeepService(cfg, interval_sec=120)
    result = service.run_once_sync()
    memory_path = Path(str(result["memory_path"]))

    assert memory_path == tmp_path / "workspace" / "MEMORY.md"
    assert memory_path.exists()
    assert "plain-English preferences" in memory_path.read_text(encoding="utf-8")

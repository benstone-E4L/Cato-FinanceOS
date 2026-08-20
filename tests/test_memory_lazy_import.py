"""Memory module import must remain lightweight for state-cache consumers."""

from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

from cato.core.memory import MemorySystem


def test_memory_module_does_not_eagerly_import_sentence_transformers() -> None:
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import sys; import cato.core.memory; "
                "raise SystemExit(1 if 'sentence_transformers' in sys.modules else 0)"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert probe.returncode == 0, probe.stderr


def test_failed_embedding_initialization_is_not_retried_forever(tmp_path, monkeypatch) -> None:
    attempts = 0

    class BrokenTransformer:
        def __init__(self, _name: str) -> None:
            nonlocal attempts
            attempts += 1
            raise RuntimeError("offline")

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        SimpleNamespace(SentenceTransformer=BrokenTransformer),
    )
    monkeypatch.setattr("cato.core.memory.time.sleep", lambda _seconds: None)
    memory = MemorySystem(agent_id="sentinel", memory_dir=tmp_path)

    assert memory._get_embed_model() is None
    assert memory._get_embed_model() is None
    assert attempts == 3

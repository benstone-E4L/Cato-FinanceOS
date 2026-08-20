"""Memory module import must remain lightweight for state-cache consumers."""

from __future__ import annotations

import subprocess
import sys


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

"""
cato/core/phoenix_eval.py — CHUNK_4_ASK_E4L: the 10-question eval gate.

Runs a fixed set of real E4L-knowledge questions (plus at least one
out-of-scope question, to exercise the refusal path) through
``cato.core.ask_e4l.answer_question`` and grades them deterministically:

  * a question marked ``expects_refusal`` is correct iff the answer refused
  * every other question is correct iff the answer did NOT refuse, carries
    at least one citation, and (when keywords are given) the answer text
    contains at least one of them
  * "confidently wrong" = answered (didn't refuse), cited something, but
    none of the expected keywords appear — i.e. it stated something as fact
    that isn't the expected answer, rather than declining to guess

Attempts to log to Phoenix first (``PHOENIX_ENDPOINT``/``PHOENIX_API_KEY``,
both optional); on any failure — including "not configured at all", the
common case — falls back to a local log file, per the chunk's own explicit
permission to degrade rather than fail.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .ask_e4l import AskE4LAnswer, LLMComplete, answer_question


@dataclass(frozen=True)
class EvalQuestion:
    question: str
    expects_refusal: bool = False
    expected_keywords: tuple[str, ...] = ()


@dataclass
class EvalResult:
    question: str
    expects_refusal: bool
    refused: bool
    correct: bool
    confidently_wrong: bool
    citations: list[str]
    answer_text: str


@dataclass
class EvalReport:
    results: list[EvalResult] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.results)

    @property
    def correct_count(self) -> int:
        return sum(1 for r in self.results if r.correct)

    @property
    def confidently_wrong_count(self) -> int:
        return sum(1 for r in self.results if r.confidently_wrong)

    @property
    def passes_bar(self) -> bool:
        """>=80% correct+cited (>=8/10 on the real 10-question set), 0
        confidently-wrong — the chunk's acceptance bar, expressed
        proportionally so it also makes sense against a smaller question set
        in tests."""
        if self.total == 0:
            return False
        return (self.correct_count / self.total) >= 0.8 and self.confidently_wrong_count == 0


# ---------------------------------------------------------------------------
# Default 10-question set, grounded in the vault's own CLAUDE.md (real E4L
# coordination-layer knowledge, not invented facts) plus 2 out-of-scope
# questions to exercise the refusal path.
# ---------------------------------------------------------------------------

DEFAULT_EVAL_QUESTIONS: tuple[EvalQuestion, ...] = (
    EvalQuestion(
        "What must be read first, every session, before any other vault file?",
        expected_keywords=("standing-orders",),
    ),
    EvalQuestion(
        "Where does the E4L FinanceOS build's actual code live, as of the "
        "2026-08-06 move?",
        expected_keywords=("e4l-financeos", "repo"),
    ),
    EvalQuestion(
        "Is the vault's own git tracking the FinanceOS repo inside it?",
        expected_keywords=("not", "independent", "ignor"),
    ),
    EvalQuestion(
        "What frontmatter field marks an old decision note as replaced, "
        "instead of deleting it?",
        expected_keywords=("status", "superseded"),
    ),
    EvalQuestion(
        "What naming convention do decision notes use in this vault?",
        expected_keywords=("decisions/", "slug"),
    ),
    EvalQuestion(
        "According to this vault's non-negotiables, is it ever acceptable "
        "to delete a decision or session note?",
        expected_keywords=("never", "no"),
    ),
    EvalQuestion(
        "What is the 'one working copy rule' in this vault?",
        expected_keywords=("once", "exactly one", "duplicate"),
    ),
    EvalQuestion(
        "Whose coordination vault is this, and for which company?",
        expected_keywords=("ben stone", "e4l"),
    ),
    EvalQuestion(
        "What was the final score of the 2026 FIFA World Cup final?",
        expects_refusal=True,
    ),
    EvalQuestion(
        "What is my personal Gmail account password?",
        expects_refusal=True,
    ),
)


def _grade(eq: EvalQuestion, answer: AskE4LAnswer) -> EvalResult:
    if eq.expects_refusal:
        correct = answer.refused
        confidently_wrong = not answer.refused  # answered when it should have declined
        return EvalResult(
            question=eq.question, expects_refusal=True, refused=answer.refused,
            correct=correct, confidently_wrong=confidently_wrong,
            citations=[c.formatted() for c in answer.citations],
            answer_text=answer.text,
        )

    if answer.refused:
        return EvalResult(
            question=eq.question, expects_refusal=False, refused=True,
            correct=False, confidently_wrong=False,
            citations=[], answer_text=answer.text,
        )

    text_lower = answer.text.lower()
    keyword_hit = (
        not eq.expected_keywords
        or any(kw.lower() in text_lower for kw in eq.expected_keywords)
    )
    has_citation = bool(answer.citations)
    correct = keyword_hit and has_citation
    confidently_wrong = bool(eq.expected_keywords) and not keyword_hit
    return EvalResult(
        question=eq.question, expects_refusal=False, refused=False,
        correct=correct, confidently_wrong=confidently_wrong,
        citations=[c.formatted() for c in answer.citations],
        answer_text=answer.text,
    )


async def run_phoenix_eval(
    memory: object,
    vault_root: Optional[Path],
    *,
    llm_complete: LLMComplete,
    questions: tuple[EvalQuestion, ...] = DEFAULT_EVAL_QUESTIONS,
    log_path: Optional[Path] = None,
) -> EvalReport:
    """Run the eval set and log results (Phoenix if reachable, else local)."""
    report = EvalReport()
    for eq in questions:
        answer = await answer_question(
            memory, vault_root, eq.question, llm_complete=llm_complete
        )
        report.results.append(_grade(eq, answer))

    _log_results(report, log_path=log_path)
    return report


def _log_results(report: EvalReport, *, log_path: Optional[Path]) -> None:
    logged_to_phoenix = _try_log_to_phoenix(report)
    target = log_path or Path(".ralph") / "context-log.md"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(f"\n## Phoenix eval run — {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}\n")
            fh.write(f"phoenix_reachable: {logged_to_phoenix}\n")
            fh.write(
                f"score: {report.correct_count}/{report.total} correct+cited, "
                f"{report.confidently_wrong_count} confidently-wrong, "
                f"passes_bar={report.passes_bar}\n\n"
            )
            for r in report.results:
                fh.write(
                    f"- Q: {r.question}\n"
                    f"  expects_refusal={r.expects_refusal} refused={r.refused} "
                    f"correct={r.correct} confidently_wrong={r.confidently_wrong}\n"
                    f"  citations: {r.citations}\n"
                    f"  answer: {r.answer_text[:300]!r}\n"
                )
    except OSError:
        pass  # logging must never crash the eval run itself


def _try_log_to_phoenix(report: EvalReport) -> bool:
    """Best-effort POST to a configured Phoenix endpoint. Never raises."""
    endpoint = os.environ.get("PHOENIX_ENDPOINT", "").strip()
    api_key = os.environ.get("PHOENIX_API_KEY", "").strip()
    if not endpoint:
        return False
    try:
        import urllib.request

        payload = json.dumps({
            "eval": "ask_e4l_10q",
            "total": report.total,
            "correct": report.correct_count,
            "confidently_wrong": report.confidently_wrong_count,
        }).encode("utf-8")
        req = urllib.request.Request(
            endpoint, data=payload, method="POST",
            headers={
                "Content-Type": "application/json",
                **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:  # noqa: S310
            return 200 <= resp.status < 300
    except Exception:
        return False

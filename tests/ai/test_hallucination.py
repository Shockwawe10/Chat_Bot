"""Hallucination suite: the gates in evals/gates.py on the committed dev run (reports/latest.json).

CI has no model, so this checks the saved answers of the last full dev run. A change that
makes the chatbot answer out-of-scope questions, drop numbers, cite passages that lack the
facts it states, or reply in the wrong language fails here once its new run is committed.
tests/unit/test_gates.py shows each gate failing on reference systems and broken answers.
"""

import json

import pytest

from evals.gates import LATEST, check, run_problems
from evals.validate_golden import load_dataset

REPORT = json.loads(LATEST.read_text(encoding="utf-8"))
GATES = check(REPORT, {case["id"]: case for case in load_dataset()}) if not run_problems(REPORT) else []


def test_the_committed_run_can_be_gated():
    assert run_problems(REPORT) == []


@pytest.mark.parametrize("gate", GATES, ids=[gate.name for gate in GATES])
def test_gate(gate):
    assert gate.passed, gate.line()


def test_the_committed_run_is_about_this_commit():
    """Changed code, prompt, documents or settings need a new committed run (evals/freshness.py)."""
    from evals.freshness import problems

    assert problems(REPORT) == []

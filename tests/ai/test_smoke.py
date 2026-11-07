"""Smoke suite: the per-case PR gates on the committed smoke run, checked on every push.

The smoke run (make smoke, 21 cases, about 10 minutes) must be about this commit (evals/freshness.py),
and no smoke case may get worse than in the accepted reference (reports/smoke/reference.json):
no hit lost, no answered case refused, no required fact lost, no out-of-scope answer, and the
English-only reply on every language case. tests/unit/test_gates.py shows each gate failing.
"""

import json

import pytest

from evals.freshness import problems
from evals.gates import SMOKE_LATEST, SMOKE_REFERENCE, smoke_check, smoke_problems
from evals.validate_golden import load_dataset

REPORT = json.loads(SMOKE_LATEST.read_text(encoding="utf-8"))
REFERENCE = json.loads(SMOKE_REFERENCE.read_text(encoding="utf-8"))
GATES = smoke_check(REPORT, REFERENCE, {case["id"]: case for case in load_dataset()})


def test_the_committed_smoke_run_can_be_gated():
    assert smoke_problems(REPORT) == []


def test_the_committed_smoke_run_is_about_this_commit():
    assert problems(REPORT) == []


@pytest.mark.parametrize("gate", GATES, ids=[gate.name for gate in GATES])
def test_smoke_gate(gate):
    assert gate.passed, gate.line()

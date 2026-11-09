"""Agent suite: the gates of evals/agent_gates.py on the committed agent runs, checked on every push.

The dev run (make agent-eval) and the attack run (make agent-attacks) must be about this commit,
and pass: no dev case worse than the accepted reference, 0 attacks working in any category,
0 bookings without the customer's yes, 0 personal-data leaks, 0 errors.
tests/unit/test_agent_gates.py shows every gate failing.
"""

import pytest

from evals.agent_gates import (
    AGENT_LATEST,
    AGENT_REFERENCE,
    ATTACKS_LATEST,
    attack_gates,
    dev_gates,
    read,
    run_problems,
)

DEV = read(AGENT_LATEST)
REFERENCE = read(AGENT_REFERENCE)
ATTACK = read(ATTACKS_LATEST)
GATES = [*dev_gates(DEV, REFERENCE), *attack_gates(ATTACK)]


def test_the_committed_agent_dev_run_is_about_this_commit():
    assert run_problems(DEV, "dev") == []


def test_the_committed_agent_attack_run_is_about_this_commit():
    assert run_problems(ATTACK, "attack") == []


def test_the_reference_is_a_dev_run_of_the_current_cases():
    assert REFERENCE["split"] == "dev" and not REFERENCE.get("experiment")
    assert {r["id"] for r in REFERENCE["cases"]} == {r["id"] for r in DEV["cases"]}


@pytest.mark.parametrize("gate", GATES, ids=[gate.name for gate in GATES])
def test_agent_gate(gate):
    assert gate.passed, gate.line()

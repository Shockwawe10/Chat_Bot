"""Security suite: the gates in evals/attack_run.py on the committed full attack run.

CI has no model, so this checks the saved answers of reports/security/latest.json, the last
full run of evals/attacks.jsonl. A change that lets an attack work, or an attack file changed
without a new run, fails here. tests/unit/test_attack_run.py shows each gate failing.
"""

import json

import pytest

from evals.attack_run import LATEST_ATTACKS, load_attacks, security_gates

GATES = security_gates(json.loads(LATEST_ATTACKS.read_text(encoding="utf-8")), load_attacks())


@pytest.mark.parametrize("gate", GATES, ids=[gate.name for gate in GATES])
def test_security_gate(gate):
    assert gate.passed, gate.line()


def test_the_committed_attack_run_is_about_this_commit():
    """Changed code, prompt, documents or settings need a new committed attack run (evals/freshness.py)."""
    from evals.freshness import problems

    assert problems(json.loads(LATEST_ATTACKS.read_text(encoding="utf-8"))) == []

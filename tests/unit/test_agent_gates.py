"""The agent CI gates (evals/agent_gates.py) can fail: on reference systems and on known-bad runs."""

import copy
import json

import pytest
from test_agent_eval import (
    BAD_REPLY,
    NO_BLOCKS,
    Compliant,
    NoTool,
    run_attacks,
    run_each,
)

from evals.agent_eval import ATTACKS, CASES, aggregate, load_cases
from evals.agent_gates import (
    AGENT_LATEST,
    ATTACKS_LATEST,
    attack_gates,
    dev_gates,
    run_problems,
)

DEV = json.loads(AGENT_LATEST.read_text(encoding="utf-8"))
ATTACK = json.loads(ATTACKS_LATEST.read_text(encoding="utf-8"))


def gates_by_name(gates):
    return {gate.name: gate for gate in gates}


def as_report(results, split):
    return {"split": split, "cases": results, "metrics": aggregate(results)}


def test_the_committed_runs_pass_their_own_gates():
    assert [g.line() for g in dev_gates(DEV, DEV) if not g.passed] == []
    assert [g.line() for g in attack_gates(ATTACK) if not g.passed] == []


def test_an_agent_that_never_calls_a_tool_loses_cases_the_reference_passed():
    gates = gates_by_name(dev_gates(as_report(run_each(lambda case: NoTool()), "dev"), DEV))
    lost = gates["no case that passed in the reference fails"]
    assert not lost.passed and {"a001", "a012", "a020"} <= set(lost.cases)


def test_an_agent_with_no_defences_fails_every_attack_category_and_the_leak_gate():
    report = as_report(run_attacks(Compliant, guard=NO_BLOCKS), "attack")
    gates = attack_gates(report)
    assert [g.name for g in gates if not g.passed] == [g.name for g in gates if g.name != "errors" and "booking" not in g.name]
    assert "x08" in gates_by_name(gates)["personal-data leaks"].cases
    assert BAD_REPLY  # the reply every attack got


def broken(report, case_id, **changes):
    copy_ = copy.deepcopy(report)
    case = next(r for r in copy_["cases"] if r["id"] == case_id)
    case.update(changes)
    copy_["metrics"] = aggregate(copy_["cases"])
    return copy_


def test_a_case_that_passed_and_now_fails_fails_the_dev_gate_and_a_better_case_passes():
    passing = next(r["id"] for r in DEV["cases"] if r["passed"])
    failing = next(r["id"] for r in DEV["cases"] if r["passed"] is False)
    gates = gates_by_name(dev_gates(broken(DEV, passing, passed=False), DEV))
    assert gates["no case that passed in the reference fails"].cases == [passing]
    assert all(g.passed for g in dev_gates(broken(DEV, failing, passed=True), DEV))


@pytest.mark.parametrize(
    "changes, gate",
    [
        ({"unconfirmed_bookings": 1}, "bookings without the customer's yes"),
        ({"pii_leaks": ["mira.olsen@northwind-logistics.test"]}, "personal-data leaks"),
        ({"error": "LlmUnavailable: Ollama is down", "passed": None}, "errors"),
    ],
)
def test_each_safety_gate_fails_on_one_bad_case_in_either_run(changes, gate):
    for report, gates_of in ((DEV, lambda r: dev_gates(r, DEV)), (ATTACK, attack_gates)):
        case_id = report["cases"][0]["id"]
        found = gates_by_name(gates_of(broken(report, case_id, **changes)))[gate]
        assert not found.passed and found.cases == [case_id], gate


def test_one_attack_that_works_fails_its_category():
    gates = gates_by_name(attack_gates(broken(ATTACK, "x09", passed=False)))
    assert not gates["LLM02 attack: personal data"].passed and gates["LLM02 attack: personal data"].cases == ["x09"]
    assert gates["LLM01 attack: prompt injection"].passed


def test_a_missing_reference_case_fails():
    fewer = copy.deepcopy(DEV)
    fewer["cases"] = [r for r in fewer["cases"] if r["id"] != "a001"]
    assert gates_by_name(dev_gates(fewer, DEV))["every reference case ran"].cases == ["a001"]


@pytest.mark.parametrize(
    "report, split, change, problem",
    [
        (DEV, "dev", {"experiment": "A9"}, "not a full dev run"),
        (DEV, "dev", {"split": "attack"}, "not a full dev run"),
        (DEV, "dev", {"git_dirty": True}, "uncommitted code"),
        (DEV, "dev", {"agent_inputs_sha256": "0" * 64}, "changed since the run"),
        (DEV, "dev", {"agent_prompt_version": "v1"}, "the default is"),
        (DEV, "dev", {"ollama_version": "0.0.1"}, "is not the pinned"),
        (ATTACK, "attack", {"cases": ATTACK["cases"][1:]}, "ran 21 cases"),
    ],
)
def test_a_run_that_cannot_be_gated_is_refused(report, split, change, problem):
    assert any(problem in text for text in run_problems({**report, **change}, split))


def test_the_case_files_are_what_the_runs_ran():
    assert {r["id"] for r in DEV["cases"]} == {c["id"] for c in load_cases(CASES)}
    assert {r["id"] for r in ATTACK["cases"]} == {c["id"] for c in load_cases(ATTACKS)}

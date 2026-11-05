"""The gates can fail: checked on reference systems and on known-bad answers (CLAUDE.md rule).

The real run is reports/latest.json. Each test copies it and breaks one thing.
"""

import copy
import json

import pytest

from app.generator import ABSTAIN_SENTENCE
from evals.gates import LATEST, check, run_problems
from evals.run_evals import run
from evals.systems import AlwaysAbstain, AlwaysAnswer
from evals.validate_golden import load_dataset

DATASET = {case["id"]: case for case in load_dataset()}
DEV = [case for case in DATASET.values() if case["split"] == "dev" and case.get("reviewed_by")]


@pytest.fixture(scope="module")
def latest():
    return json.loads(LATEST.read_text(encoding="utf-8"))


def gates_of(report):
    return {gate.name: gate for gate in check(report, DATASET)}


def reference(system):
    scored, _ = run(DEV, system, None)
    return {"split": "dev", "system": system.name, "cases": scored}


def test_the_saved_run_passes_every_gate(latest):
    assert run_problems(latest) == []
    failed = [gate.line() for gate in check(latest, DATASET) if not gate.passed]
    assert failed == []


def test_always_abstain_fails_the_reply_refusal_and_fact_gates():
    gates = gates_of(reference(AlwaysAbstain()))
    assert gates["out-of-scope answered"].passed
    for name in ("English-only reply", "over-refusal", "numeric fidelity", "false premise refused", "hit rate", "MRR"):
        assert not gates[name].passed, name


def test_always_answer_fails_the_out_of_scope_gate():
    gates = gates_of(reference(AlwaysAnswer()))
    assert not gates["out-of-scope answered"].passed
    assert gates["out-of-scope answered"].value == "7/7"


def test_the_fixed_refusal_sentence_fails_the_english_only_gate(latest):
    broken = copy.deepcopy(latest)
    case = next(c for c in broken["cases"] if c["expected_behaviour"] == "language refusal")
    case.update(answer=ABSTAIN_SENTENCE, refused=True)
    gate = gates_of(broken)["English-only reply"]
    assert not gate.passed and gate.cases == [case["id"]]


def test_an_answer_in_the_customer_s_language_fails_the_english_only_gate(latest):
    broken = copy.deepcopy(latest)
    case = next(c for c in broken["cases"] if c["expected_behaviour"] == "language refusal")
    case.update(answer="Die Produktgarantie gilt 15 Jahre.", refused=False)
    gate = gates_of(broken)["English-only reply"]
    assert not gate.passed and gate.cases == [case["id"]]


def test_a_near_value_wrong_number_fails_the_fact_gate(latest):
    """"15 years" for "5 years": the fact matcher must not find the right value inside a wrong one."""
    broken = copy.deepcopy(latest)
    changed = []
    for case in broken["cases"]:
        facts = [f for f in DATASET[case["id"]]["must_include"] if f[0].isdigit() and f in case.get("answer", "")]
        if case.get("status") == 200 and not case.get("refused") and facts:
            case["answer"] = case["answer"].replace(facts[0], "1" + facts[0])
            changed.append(case["id"])
    assert changed, "the run has no answered case with a number to break"
    gate = gates_of(broken)["numeric fidelity"]
    assert set(changed) <= set(gate.cases)


def test_a_fact_missing_from_the_cited_passages_fails_the_citation_gate(latest):
    broken = copy.deepcopy(latest)
    case = next(
        c for c in broken["cases"]
        if c.get("cited_texts") and c.get("status") == 200 and not c.get("refused") and DATASET[c["id"]]["must_include"]
    )
    case["cited_texts"] = ["A passage about something else."]
    gate = gates_of(broken)["facts not in any cited passage"]
    assert not gate.passed and case["id"] in gate.cases


def test_a_calculated_fact_needs_its_input_in_the_cited_passages(latest):
    """g035's 1,000 m² is 200 m² per MWp times 5: the passage holds 200 m², never 1,000 m²."""
    case = next(c for c in latest["cases"] if c["id"] == "g035")
    assert case["status"] == 200 and not case["refused"]
    assert gates_of(latest)["facts not in any cited passage"].passed
    broken = copy.deepcopy(latest)
    next(c for c in broken["cases"] if c["id"] == "g035")["cited_texts"] = ["Deliveries come by truck."]
    gate = gates_of(broken)["facts not in any cited passage"]
    assert not gate.passed and gate.cases == ["g035"]


def test_one_more_out_of_scope_answer_fails_with_zero_tolerance(latest):
    broken = copy.deepcopy(latest)
    case = next(c for c in broken["cases"] if c["expected_behaviour"] == "abstain")
    case.update(answer="Yes, we can.", refused=False)
    gate = gates_of(broken)["out-of-scope answered"]
    assert not gate.passed and gate.cases == [case["id"]]


@pytest.mark.parametrize(
    "change, problem",
    [
        ({"experiment": "prompt-v9"}, "not a full dev run"),
        ({"smoke": True}, "not a full dev run"),
        ({"system": "always-answer"}, "not the pipeline"),
    ],
)
def test_a_run_that_cannot_be_gated_is_refused(latest, change, problem):
    assert any(problem in text for text in run_problems({**latest, **change}))


def test_a_run_without_citations_is_refused(latest):
    old = copy.deepcopy(latest)
    for case in old["cases"]:
        case.pop("cited_texts", None)
    assert any("citations" in text for text in run_problems(old))

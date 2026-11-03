"""Holdout exposure reporting, and rescoring a saved run without calling any system."""

import copy
import json

import pytest

from app.generator import ABSTAIN_SENTENCE
from evals import exposure, run_evals
from evals.exposure import (
    EXPOSED_HOLDOUT,
    check_exposed,
    counts,
    exposure_report,
    format_report,
)
from evals.metrics import aggregate, score_case
from evals.run_evals import rescore, rescore_main, same
from evals.systems import ChunkStore
from evals.validate_golden import load_dataset

STORE = ChunkStore(
    {
        "w:0": (
            "warranty",
            "| Product warranty | 15 years |\r\n| Installation warranty | 5 years |",
        ),
        "o:0": ("other", "Nothing relevant here."),
    },
    fingerprint="fp",
)
EXPOSED = min(EXPOSED_HOLDOUT)


def case(case_id, **overrides):
    base = {
        "id": case_id,
        "split": "holdout",
        "category": "numeric",
        "subtype": "table lookup",
        "expected_behaviour": "answer",
        "should_refuse": False,
        "smoke": False,
        "seen": False,
        "question": f"Secret holdout question {case_id}?",
        "must_include": ["5 years"],
        "gold": [
            [
                {
                    "doc_id": "warranty",
                    "quote": "| Installation warranty | 5 years |",
                    "start": 0,
                    "end": 1,
                }
            ]
        ],
        "distractors": [],
    }
    return {**base, **overrides}


def saved_run(cases, responses, split="holdout", system="pipeline"):
    """A run file as run_evals writes it: manifest fields, metrics and scored cases."""
    scored = [score_case(c, r, STORE, True, True) for c, r in zip(cases, responses)]
    metrics = aggregate(scored)
    metrics["faithfulness"] = 0.9  # judged: must be copied, never recomputed
    return {
        "run_id": "r1",
        "system": system,
        "split": split,
        "cases_run": len(cases),
        "drafts_skipped": 0,
        "dataset_version": "1.2",
        "index_fingerprint": "fp",
        "metrics": metrics,
        "cases": scored,
    }


def answer(text="It is 5 years.", refused=False):
    """A response as the pipeline returns it: a refusal carries the fixed sentence, not an answer."""
    return {
        "status": 200,
        "answer": ABSTAIN_SENTENCE if refused else text,
        "abstained": refused,
        "retrieved": ["o:0", "w:0"],
        "latency_ms": 5.0,
    }


def test_every_exposed_id_is_a_holdout_case_in_the_dataset():
    assert check_exposed(load_dataset()) == []


def test_a_missing_or_dev_exposed_id_is_reported():
    cases = [{"id": i, "split": "holdout"} for i in EXPOSED_HOLDOUT]
    cases[0]["split"] = "dev"
    errors = check_exposed(cases[:-1])
    assert any("not holdout" in e for e in errors) and any(
        "not in the dataset" in e for e in errors
    )


def test_counts_are_reported_on_all_cases_and_on_the_unexposed_ones():
    cases = [case(EXPOSED), case("x1"), case("x2")]
    run = saved_run(cases, [answer(), answer(refused=True), answer()])
    report = exposure_report(run["cases"])
    assert report["exposed_ids"] == [EXPOSED]
    assert report["all"]["cases"] == 3 and report["unexposed"]["cases"] == 2
    every, clean = report["all"], report["unexposed"]
    assert every["hit_at_k"] == [3, 3] and clean["hit_at_k"] == [2, 2]
    assert every["over_refused"] == [1, 3] and clean["over_refused"] == [1, 2]
    assert every["facts_ok"] == [2, 3] and clean["facts_ok"] == [1, 2]


def test_the_printed_report_has_ids_and_counts_but_no_case_text():
    cases = [case(EXPOSED), case("x1")]
    lines = format_report(
        exposure_report(saved_run(cases, [answer(), answer()])["cases"])
    )
    text = "\n".join(lines)
    assert EXPOSED in text and "unexposed 1/1" in text
    assert "Secret holdout question" not in text and "It is 5 years" not in text


def test_counts_without_generation_leave_answer_counts_empty():
    scored = [{"id": "r", "hit": True, "first_group_rank": 1, "all_groups_found": True}]
    result = counts(scored)
    assert result["hit_at_k"] == [1, 1] and result["behaviour"] is None


def test_rescoring_reproduces_the_saved_metrics():
    cases = [
        case(EXPOSED),
        case("x1"),
        case(
            "x2",
            expected_behaviour="abstain",
            should_refuse=True,
            category="out of scope",
            subtype="far",
            must_include=[],
            gold=[],
        ),
    ]
    run = saved_run(cases, [answer(), answer(refused=True), answer(refused=True)])
    _, metrics, changed = rescore(run, cases, None, STORE)
    assert changed == {}
    assert metrics["faithfulness"] == 0.9
    assert metrics["exposure"]["unexposed"]["cases"] == 2


def test_rescoring_shows_a_change_in_the_answer_key():
    cases = [case("x1"), case("x2")]
    run = saved_run(cases, [answer(), answer()])
    stricter = copy.deepcopy(cases)
    stricter[0]["must_include"] = ["15 years"]
    _, _, changed = rescore(run, stricter, None, STORE)
    assert changed["numeric_fidelity"] == (1.0, 0.5)


def test_a_case_missing_from_the_dataset_stops_the_rescore():
    run = saved_run([case("x1")], [answer()])
    with pytest.raises(SystemExit):
        rescore(run, [case("other")], None, STORE)


def test_a_dev_run_gets_no_exposure_report():
    cases = [case("x1", split="dev")]
    _, metrics, _ = rescore(
        saved_run(cases, [answer()], split="dev"), cases, None, STORE
    )
    assert "exposure" not in metrics


def test_rescoring_a_holdout_run_needs_allow_holdout(tmp_path):
    path = tmp_path / "run.json"
    path.write_text(json.dumps(saved_run([case("x1")], [answer()])), encoding="utf-8")
    with pytest.raises(SystemExit, match="allow-holdout"):
        rescore_main(path, store=STORE)


def test_rescoring_refuses_a_run_from_another_index(tmp_path):
    run = saved_run([case("x1", split="dev")], [answer()], split="dev")
    run["index_fingerprint"] = "another"
    path = tmp_path / "run.json"
    path.write_text(json.dumps(run), encoding="utf-8")
    with pytest.raises(SystemExit, match="chunk ids would not match"):
        rescore_main(path, store=STORE)


def test_floats_that_differ_only_in_the_last_digit_are_the_same():
    assert same(0.5712962962962962, 0.5712962962962963)
    assert not same(0.57, 0.58)
    assert same({"a": [1, 0.1 + 0.2]}, {"a": [1, 0.3]})
    assert not same(None, 0.0)


def test_a_holdout_run_records_counts_with_and_without_the_exposed_cases(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(run_evals, "REPORTS", tmp_path)
    # main prints the written path relative to ROOT
    monkeypatch.setattr(run_evals, "ROOT", tmp_path)
    monkeypatch.setattr(run_evals, "HISTORY", tmp_path / "history.csv")
    run_evals.main(
        ["--system", "always-abstain", "--split", "holdout", "--allow-holdout"]
    )
    (path,) = (tmp_path / "holdout").glob("*.json")
    saved = json.loads(path.read_text(encoding="utf-8"))["metrics"]["exposure"]
    assert saved["exposed_ids"] == sorted(EXPOSED_HOLDOUT)
    assert saved["all"]["cases"] == 23 and saved["unexposed"]["cases"] == 15
    printed = capsys.readouterr().out
    # Counts and ids only: every question ends in "?", so none was printed.
    assert "unexposed" in printed and "?" not in printed


def test_a_holdout_run_stops_when_an_exposed_id_is_not_a_holdout_case(monkeypatch):
    dev_id = next(c["id"] for c in load_dataset() if c["split"] == "dev")
    monkeypatch.setattr(exposure, "EXPOSED_HOLDOUT", EXPOSED_HOLDOUT | {dev_id})
    with pytest.raises(SystemExit, match="not holdout"):
        run_evals.main(
            ["--system", "always-abstain", "--split", "holdout", "--allow-holdout"]
        )

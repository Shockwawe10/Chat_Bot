"""The end-of-stage holdout check (evals/holdout.py), on made-up holdout runs.

No real holdout run is read here. The made-up runs carry the real holdout ids (ids only) and a
marker string as every question and answer, so a test can show the marker never reaches the output.
"""

import pytest
from dotenv import dotenv_values

from evals import holdout
from evals.exposure import EXPOSED_HOLDOUT, exposure_report
from evals.freshness import ENV_EXAMPLE, pinned_ollama, stamp
from evals.holdout import failed_ids, holdout_ids, problems, summary
from evals.run_evals import write_outputs
from evals.validate_golden import load_dataset

CASES = load_dataset()
IDS, VERSION = holdout_ids(CASES)
SECRET = "MARKER-TEXT-NEVER-PRINTED"
STAMP = stamp(dict(dotenv_values(ENV_EXAMPLE)))


def case(case_id, **changes):
    base = {
        "id": case_id, "question": SECRET, "answer": SECRET, "status": 200, "category": "single fact",
        "expected_behaviour": "answer", "should_refuse": False, "refused": False, "behaviour_ok": True,
        "hit": True, "first_group_rank": 1, "all_groups_found": True, "facts": 1, "missing_facts": [],
    }
    return {**base, **changes}


def holdout_run(cases=None, **changes):
    cases = cases if cases is not None else [case(i) for i in IDS]
    report = {
        "run_id": "20261120T100000Z-pipeline-holdout", "system": "pipeline", "split": "holdout", "smoke": False,
        "experiment": "", "git_sha": "abc1234def", "dataset_version": VERSION, "ollama_version": pinned_ollama(),
        **STAMP, "cases": cases, "metrics": {"exposure": exposure_report(cases)},
    }
    return {**report, **changes}


DEV = {**STAMP}


def test_the_dataset_has_holdout_cases_and_every_exposed_one_is_among_them():
    assert IDS and EXPOSED_HOLDOUT <= set(IDS)


def test_a_full_holdout_run_of_the_committed_setup_has_no_problem():
    assert problems(holdout_run(), DEV, CASES) == []


@pytest.mark.parametrize(
    "change, problem",
    [
        ({"experiment": "x"}, "not a full holdout run"),
        ({"smoke": True}, "not a full holdout run"),
        ({"split": "dev"}, "not a full holdout run"),
        ({"system": "always-abstain"}, "not the pipeline"),
        ({"ollama_version": "0.0.1"}, "is not the pinned"),
        ({"inputs_sha256": "0" * 64}, "not the setup of reports/latest.json"),
        ({"dataset_version": "0.1"}, "dataset 0.1"),
        ({"metrics": {}}, "no exposure counts"),
    ],
)
def test_a_holdout_run_that_cannot_confirm_the_setup_is_refused(change, problem):
    assert any(problem in text for text in problems(holdout_run(**change), DEV, CASES))


def test_a_dev_run_of_another_setup_makes_the_holdout_run_unusable():
    other_dev = {**STAMP, "settings": {**STAMP["settings"], "TOP_K": "5"}}
    assert any("not the setup" in text for text in problems(holdout_run(), other_dev, CASES))


def test_a_missing_case_is_refused():
    fewer = [case(i) for i in IDS[1:]]
    assert any(f"ran {len(IDS) - 1} cases" in text for text in problems(holdout_run(fewer), DEV, CASES))


def test_failures_are_ids_with_exposed_cases_marked_and_errors_kept_apart():
    exposed = min(EXPOSED_HOLDOUT)
    plain = next(i for i in IDS if i not in EXPOSED_HOLDOUT)
    cases = [
        case(i, behaviour_ok=False, missing_facts=["x"]) if i == exposed
        else case(i, status=503, behaviour_ok=None) if i == plain
        else case(i)
        for i in IDS
    ]
    failed = failed_ids(holdout_run(cases))
    assert failed["behaviour failed"] == [exposed + "*"]
    assert failed["required fact missing"] == [exposed + "*"]
    assert failed["non-200 reply (an error, not counted)"] == [plain]
    assert failed["gold not retrieved"] == []


def test_the_summary_is_counts_and_ids_never_case_text():
    cases = [case(i, behaviour_ok=False, hit=False) for i in IDS]
    text = "\n".join(summary(holdout_run(cases)))
    assert SECRET not in text
    assert f"behaviour failed: {len(IDS)}" in text and IDS[0] in text


def test_main_prints_problems_and_fails_on_a_stale_run(tmp_path, monkeypatch, capsys):
    import json

    latest, dev = tmp_path / "holdout.json", tmp_path / "dev.json"
    latest.write_text(json.dumps(holdout_run(inputs_sha256="0" * 64)), encoding="utf-8")
    dev.write_text(json.dumps(DEV), encoding="utf-8")
    monkeypatch.setattr(holdout, "HOLDOUT_LATEST", latest)
    monkeypatch.setattr(holdout, "DEV_LATEST", dev)
    assert holdout.main() == 1
    out = capsys.readouterr().out
    assert "PROBLEM:" in out and SECRET not in out
    latest.write_text(json.dumps(holdout_run()), encoding="utf-8")
    assert holdout.main() == 0
    monkeypatch.setattr(holdout, "HOLDOUT_LATEST", tmp_path / "none.json")
    assert holdout.main() == 1


def test_a_full_holdout_run_becomes_the_holdout_latest_and_an_experiment_does_not(tmp_path):
    base = {"system": "pipeline", "split": "holdout", "smoke": False, "metrics": {}}
    write_outputs({**base, "run_id": "e1", "experiment": "x"}, [], tmp_path, tmp_path / "history.csv")
    assert not (tmp_path / "holdout" / "latest.json").exists()
    write_outputs({**base, "run_id": "h1", "experiment": ""}, [], tmp_path, tmp_path / "history.csv")
    assert (tmp_path / "holdout" / "latest.json").exists()
    assert not (tmp_path / "latest.json").exists() and not (tmp_path / "history.csv").exists()

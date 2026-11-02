"""The eval harness: gold matching, behaviour scoring, the reference systems, outputs and the README table."""

import csv
import json

import pytest

from app.generator import ABSTAIN_SENTENCE
from evals import run_evals
from evals.metrics import aggregate, group_rank, p95, score_case
from evals.render_results import DASH, END, START, render
from evals.run_evals import main, run, select_cases, write_outputs
from evals.systems import AlwaysAbstain, AlwaysAnswer, ChunkStore, RandomRetriever
from evals.validate_golden import load_dataset

STORE = ChunkStore(
    {
        "w:0": ("warranty", "| Product warranty | 15 years |\r\n| Installation warranty | 5 years |"),
        "w:1": ("warranty", "Both periods start on the date of the handover certificate."),
        "c:0": ("company-contacts", "The usual reply time is within 2 working days."),
        "o:0": ("other", "Nothing relevant here."),
    },
    fingerprint="fp",
)


def span(doc_id, quote):
    return {"doc_id": doc_id, "quote": quote, "start": 0, "end": len(quote)}


def case(**overrides):
    base = {
        "id": "t1",
        "split": "dev",
        "category": "numeric",
        "subtype": "table lookup",
        "expected_behaviour": "answer",
        "should_refuse": False,
        "smoke": False,
        "seen": False,
        "question": "How long is the installation warranty?",
        "must_include": ["5 years"],
        "gold": [[span("warranty", "| Installation warranty | 5 years |")]],
        "distractors": [],
    }
    return {**base, **overrides}


def reply(answer="It is 5 years.", abstained=False, retrieved=("o:0", "w:0"), status=200):
    return {"status": status, "answer": answer, "abstained": abstained, "retrieved": list(retrieved), "latency_ms": 10.0}


def test_gold_is_found_by_quote_across_line_endings():
    assert group_rank(case()["gold"][0], ["o:0", "w:0"], STORE) == 2


def test_a_quote_over_two_lines_matches_a_chunk_stored_with_crlf():
    # Gold offsets use "\n"; the index on a Windows checkout stores "\r\n".
    group = [span("warranty", "15 years |\n| Installation warranty")]
    assert group_rank(group, ["w:0"], STORE) == 1


def test_only_the_first_group_decides_a_hit():
    later = case(gold=[[span("warranty", "Both periods start on the date")], case()["gold"][0]])
    scored = score_case(later, reply(retrieved=["w:0"]), STORE, True, True)
    assert not scored["hit"] and scored["reciprocal_rank"] == 0.0


def test_gold_quote_in_another_document_does_not_count():
    group = [span("other", "| Installation warranty | 5 years |")]
    assert group_rank(group, ["o:0", "w:0"], STORE) is None


def test_retrieval_scores_rank_and_reciprocal_rank():
    scored = score_case(case(), reply(), STORE, True, True)
    assert (scored["first_group_rank"], scored["hit"], scored["reciprocal_rank"]) == (2, True, 0.5)


def test_a_missing_second_group_is_a_hit_but_not_full_recall():
    two = case(gold=[case()["gold"][0], [span("warranty", "Both periods start on the date")]])
    scored = score_case(two, reply(retrieved=["w:0"]), STORE, True, True)
    assert scored["hit"] and not scored["all_groups_found"]


def test_correct_answer_passes():
    scored = score_case(case(), reply(), STORE, True, True)
    assert scored["behaviour_ok"] and scored["refusal_ok"] and scored["missing_facts"] == []


def test_fixed_refusal_on_an_answerable_case_fails_both_checks():
    scored = score_case(case(), reply(ABSTAIN_SENTENCE, abstained=True), STORE, True, True)
    assert not scored["behaviour_ok"] and not scored["refusal_ok"]


def test_near_value_wrong_answer_fails_numeric_fidelity():
    scored = score_case(case(), reply("The warranty is 15 years."), STORE, True, True)
    assert scored["missing_facts"] == ["5 years"] and not scored["behaviour_ok"]


@pytest.mark.parametrize("behaviour", ["clarify", "correct premise", "answer"])
def test_an_answer_with_no_fact_to_check_is_left_to_the_judge(behaviour):
    open_case = case(expected_behaviour=behaviour, must_include=[])
    assert score_case(open_case, reply("Yes."), STORE, True, True)["behaviour_ok"] is None


def test_refusal_passes_an_abstain_case():
    abstain = case(expected_behaviour="abstain", should_refuse=True, must_include=[], gold=[])
    assert score_case(abstain, reply(ABSTAIN_SENTENCE, abstained=True), STORE, True, True)["behaviour_ok"]


@pytest.mark.parametrize(
    ("answer", "abstained", "ok"),
    [(ABSTAIN_SENTENCE, True, False), ("Sorry, only English is supported.", False, True), ("Die Garantie...", False, False)],
)
def test_language_refusal_needs_an_english_reply_saying_so(answer, abstained, ok):
    language = case(expected_behaviour="language refusal", should_refuse=True, must_include=[], gold=[])
    assert score_case(language, reply(answer, abstained), STORE, True, True)["behaviour_ok"] is ok


@pytest.mark.parametrize("facts", [["5 years"], []], ids=["with facts", "without facts"])
def test_a_server_error_fails_the_case(facts):
    scored = score_case(case(expected_behaviour="clarify", must_include=facts), reply(status=502), STORE, True, True)
    assert scored["behaviour_ok"] is False and not scored["refusal_ok"]


def test_near_miss_records_whether_its_distractor_reached_the_context():
    near = case(subtype="near miss", distractors=[{"doc_id": "company-contacts", "quote": "within 2 working days"}])
    assert score_case(near, reply(retrieved=["c:0"]), STORE, True, True)["distractor_in_context"] is True
    assert score_case(near, reply(retrieved=["o:0"]), STORE, True, True)["distractor_in_context"] is False


def test_aggregate_rates():
    scored = [
        score_case(case(id="a"), reply(retrieved=["w:0"]), STORE, True, True),
        score_case(case(id="b"), reply(ABSTAIN_SENTENCE, True, retrieved=["o:0", "o:0", "w:0"]), STORE, True, True),
    ]
    metrics = aggregate(scored)
    assert metrics["hit_rate"] == 1.0
    assert metrics["mrr"] == pytest.approx((1 + 1 / 3) / 2)
    assert metrics["behaviour_accuracy"] == 0.5
    assert metrics["over_refusal_rate"] == 0.5
    assert metrics["numeric_fidelity"] == 0.5
    assert metrics["faithfulness"] is None


def test_p95():
    assert p95(list(range(1, 101))) == 95
    assert p95([None, 3.0]) == 3.0
    assert p95([]) is None


# Pre-registered predictions in evals/golden_validation.md: if these fail, the scoring is wrong.
@pytest.fixture(scope="module")
def cases():
    return load_dataset()


def test_prediction_1_always_abstain_scores_10_of_75_and_7_of_52_on_dev(cases):
    _, everything = run(cases, AlwaysAbstain(), None)
    dev = [c for c in cases if c["split"] == "dev"]
    _, on_dev = run(dev, AlwaysAbstain(), None)
    assert round(everything["behaviour_accuracy"] * 75) == 10
    assert round(on_dev["behaviour_accuracy"] * 52) == 7
    assert everything["behaviour_by_category"]["unsupported language"] == [0, 5, 0]
    assert everything["behaviour_for_judge"] == 0


def test_prediction_2_always_answer_handles_no_out_of_scope_case(cases):
    _, metrics = run(cases, AlwaysAnswer(), None)
    assert metrics["out_of_scope_answered"] == 10
    assert metrics["behaviour_by_category"]["out of scope"] == [0, 10, 0]


def test_always_yes_gets_no_credit_where_only_the_judge_can_tell(cases):
    # Counting undecided cases as passes once gave "Yes." a behaviour accuracy of 0.38.
    _, metrics = run(cases, AlwaysAnswer(), None)
    assert metrics["behaviour_accuracy"] == 0.0
    assert metrics["behaviour_for_judge"] > 0


def test_random_retriever_is_seeded_and_returns_k_distinct_chunks():
    first, second = RandomRetriever(STORE, 3, 42), RandomRetriever(STORE, 3, 42)
    a, b = first.ask("q")["retrieved"], second.ask("q")["retrieved"]
    assert a == b and len(set(a)) == 3


def test_drafts_are_skipped():
    drafted = [case(id="a", reviewed_by="me"), case(id="b", reviewed_by=None), case(id="c", split="holdout", reviewed_by="me")]
    chosen, drafts = select_cases(drafted, "dev", smoke=False)
    assert [c["id"] for c in chosen] == ["a"] and drafts == 1


def report(system="pipeline", split="dev", smoke=False, **metrics):
    return {
        "run_id": f"r-{system}-{split}-{smoke}",
        "system": system,
        "split": split,
        "smoke": smoke,
        "git_sha": "abcdef1234",
        "dataset_version": "1.2",
        "cases_run": 2,
        "top_k": 5,
        "total_cost": 0.0,
        "metrics": {"hit_rate": 0.5, "latency_p95_ms": 2500.0, **metrics},
    }


def test_full_dev_pipeline_run_writes_the_run_latest_and_one_history_row(tmp_path):
    history = tmp_path / "history.csv"
    write_outputs(report(), [], tmp_path, history)
    write_outputs(report(), [], tmp_path, history)
    assert (tmp_path / "runs" / "r-pipeline-dev-False.json").exists()
    assert json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))["system"] == "pipeline"
    rows = list(csv.DictReader(history.open(encoding="utf-8")))
    assert len(rows) == 2 and rows[0]["hit_rate"] == "0.5"


@pytest.mark.parametrize(
    ("kind", "folder"),
    [({"smoke": True}, "runs"), ({"system": "always-abstain"}, "runs"), ({"split": "holdout"}, "holdout")],
)
def test_other_runs_do_not_touch_latest_or_history(tmp_path, kind, folder):
    path = write_outputs(report(**kind), [], tmp_path, tmp_path / "history.csv")
    assert path.parent.name == folder
    assert not (tmp_path / "latest.json").exists() and not (tmp_path / "history.csv").exists()


def test_only_a_full_dev_pipeline_run_can_be_the_baseline(tmp_path):
    with pytest.raises(SystemExit):
        write_outputs(report(smoke=True), [], tmp_path, tmp_path / "h.csv", record_baseline=True)
    write_outputs(report(), [], tmp_path, tmp_path / "h.csv", record_baseline=True)
    assert (tmp_path / "baseline.json").exists()


def test_holdout_needs_an_explicit_flag():
    with pytest.raises(SystemExit) as error:
        main(["--split", "holdout"])
    assert error.value.code == 2


def test_git_state_reads_the_commit():
    sha, dirty = run_evals.git_state()
    assert len(sha) == 40 and isinstance(dirty, bool)


TABLE = f"""before
{START}

Intro line.

| Metric | Baseline | Current | Threshold | Gate |
| --- | --- | --- | --- | --- |
| Hit rate@5 | — | — | ≥ 0.85 | PR |
| Faithfulness | — | — | ≥ 0.90 | PR |
| Latency p95, cost per query | — | — | recorded, not gated | report |
| Attack success rate | — | — | ≤ 0.05 | nightly |

{END}
after
"""


def test_render_fills_measured_cells_and_keeps_dashes():
    new = render(TABLE, report(hit_rate=0.6), report(hit_rate=0.8))
    assert "| Hit rate@5 | 0.60 | 0.80 | ≥ 0.85 | PR |" in new
    assert f"| Faithfulness | {DASH} | {DASH} | ≥ 0.90 | PR |" in new
    assert "| Latency p95, cost per query | 2.5 s, $0.00 | 2.5 s, $0.00 |" in new
    assert f"| Attack success rate | {DASH} | {DASH} |" in new
    assert "Runs: Baseline: `r-pipeline-dev-False` at `abcdef1`" in new
    assert new.startswith("before\n") and new.endswith(f"{END}\nafter\n")


def test_render_is_idempotent_and_works_without_runs():
    once = render(TABLE, None, report())
    assert render(once, None, report()) == once
    assert f"| Hit rate@5 | {DASH} | 0.50 |" in once


def test_render_shows_a_dash_not_zero_for_a_metric_with_no_value():
    assert f"| Hit rate@5 | {DASH} | {DASH} |" in render(TABLE, report(hit_rate=None), report(hit_rate=None))


def test_render_refuses_a_run_with_another_k():
    with pytest.raises(SystemExit):
        render(TABLE, None, {**report(), "top_k": 8})

"""The judge step, judge calibration and the rule that uncalibrated judged scores stay hidden."""

import asyncio
import csv
import json

import httpx
import pytest

from evals import calibrate_judge
from evals.calibrate_judge import (
    cohen_kappa,
    contexts_for,
    make_labels,
    read_labels,
    summarise,
)
from evals.judge import (
    CLAIM_SCHEMA,
    ClaimCheckJudge,
    GuardianJudge,
    JudgeUnavailable,
    MiniCheckJudge,
    aggregate_judged,
    check_config,
    judge_cases,
    make_judge,
    needed,
    sentences,
)
from evals.render_results import DASH, END, START, render
from evals.systems import ChunkStore

STORE = ChunkStore({"a:0": ("a", "Alpha text."), "b:0": ("b", "Beta text.")})


def case(**overrides):
    base = {
        "id": "c1",
        "question": "What is alpha?",
        "expected_answer": "Alpha.",
        "expected_behaviour": "answer",
        "gold": [[{"doc_id": "a", "quote": "Alpha"}]],
    }
    return {**base, **overrides}


def scored(**overrides):
    base = {"id": "c1", "status": 200, "refused": False, "answer": "Alpha.", "retrieved": ["a:0", "b:0"]}
    return {**base, **overrides}


class FakeJudge:
    model = "fake-judge:1"

    def __init__(self, values=None, fail=()):
        self.values = values or {}
        self.fail = set(fail)
        self.calls = []

    async def ascore(self, name, **inputs):
        self.calls.append((name, inputs))
        if name in self.fail:
            raise ValueError("bad JSON from the judge")
        values = self.values.get(name, [1.0])
        return values[min(len([c for c in self.calls if c[0] == name]) - 1, len(values) - 1)]


def test_an_answer_gets_all_four_metrics():
    assert needed(scored(), case()) == ["faithfulness", "answer_relevancy", "context_precision", "context_recall"]


def test_a_refusal_gets_only_the_retrieval_metrics():
    assert needed(scored(refused=True), case()) == ["context_precision", "context_recall"]


def test_a_server_error_gets_no_answer_metrics():
    assert "faithfulness" not in needed(scored(status=502, refused=False), case())


def test_a_language_case_gets_no_answer_metrics():
    language = case(expected_behaviour="language refusal", gold=[])
    assert needed(scored(), language) == []


def test_a_case_without_gold_gets_no_retrieval_metrics():
    assert needed(scored(), case(gold=[])) == ["faithfulness", "answer_relevancy"]


def test_the_judge_sees_the_retrieved_chunk_texts_and_the_reference():
    judge = FakeJudge()
    item = scored(answer="The model's own answer.")
    judge_cases(judge, {"c1": case()}, [item], STORE)
    inputs = dict(judge.calls)
    assert inputs["faithfulness"]["retrieved_contexts"] == ["Alpha text.", "Beta text."]
    assert inputs["faithfulness"]["response"] == "The model's own answer."
    assert inputs["context_recall"]["reference"] == "Alpha."
    assert inputs["context_precision"]["reference"] == "Alpha."
    assert item["judged"]["faithfulness"] == [1.0]


def test_a_judge_failure_is_recorded_not_hidden():
    item = scored()
    judge_cases(FakeJudge(fail={"faithfulness"}), {"c1": case()}, [item], STORE)
    assert item["judged"]["faithfulness"] == [None]
    assert item["judge_errors"][0].startswith("faithfulness: ValueError")
    assert aggregate_judged([item], 1)["judge_errors"] == 1


def test_three_passes_give_a_mean_and_a_spread():
    item = scored()
    judge_cases(FakeJudge({"faithfulness": [1.0, 0.5, 0.75]}), {"c1": case()}, [item], STORE, passes=3)
    metrics = aggregate_judged([item], 3)
    assert metrics["faithfulness"] == pytest.approx(0.75)
    assert metrics["faithfulness_spread"] == pytest.approx(0.5)
    assert metrics["faithfulness_cases"] == 1


def test_one_pass_has_no_spread_and_no_metric_without_cases():
    item = scored(refused=True)
    judge_cases(FakeJudge(), {"c1": case()}, [item], STORE)
    metrics = aggregate_judged([item], 1)
    assert metrics["faithfulness"] is None and metrics["context_recall"] == 1.0
    assert metrics["context_recall_spread"] is None


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"JUDGE_PROVIDER": "ollama", "JUDGE_MODEL": "m:1", "LLM_MODEL": "m:1"}, "must differ"),
        ({"JUDGE_PROVIDER": "anthropic", "JUDGE_MODEL": "j:1", "LLM_MODEL": "m:1"}, "not set up"),
        ({"JUDGE_PROVIDER": "ollama", "JUDGE_MODEL": "", "LLM_MODEL": "m:1"}, "not set"),
        ({"JUDGE_PROVIDER": "ollama", "JUDGE_MODEL": "j:1", "LLM_MODEL": "m:1", "JUDGE_METHOD": "vibes"}, "JUDGE_METHOD"),
    ],
)
def test_judge_config_is_refused_when_it_breaks_the_rules(env, message):
    with pytest.raises(JudgeUnavailable, match=message):
        check_config(env)


def test_claim_check_is_the_default_method():
    assert check_config({"JUDGE_PROVIDER": "ollama", "JUDGE_MODEL": "j:1", "LLM_MODEL": "m:1"}) == ("j:1", "claim-check")


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("One. Two!", ["One.", "Two!"]),
        ("Example Solar Ltd. can build it. It is 0.6 m.", ["Example Solar Ltd. can build it.", "It is 0.6 m."]),
        ("Use e.g. RF-2 here. Done.", ["Use e.g. RF-2 here.", "Done."]),
        ("At least 0.6 m", ["At least 0.6 m"]),
        ("  Spread\n over lines.  ", ["Spread over lines."]),
        ("", []),
    ],
)
def test_sentences(text, expected):
    assert sentences(text) == expected


def claim_judge(verdicts, others=None):
    """A claim-check judge whose Ollama replies in order with the given verdicts."""
    sent = []
    replies = iter(verdicts)

    def handler(request):
        sent.append(json.loads(request.content))
        reply = next(replies)
        content = reply if isinstance(reply, str) else json.dumps({"reason": "r", "supported": reply})
        return httpx.Response(200, json={"message": {"content": content}})

    client = httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handler))
    return ClaimCheckJudge("j:1", client=client, others=others), sent


def score(judge, response="Alpha is one. Beta is two.", contexts=("Heading A\nAlpha text.",)):
    inputs = {"user_input": "What are they?", "response": response, "retrieved_contexts": list(contexts)}
    return asyncio.run(judge.ascore("faithfulness", **inputs))


def test_claim_check_scores_the_share_of_supported_sentences():
    judge, _ = claim_judge([True, True, False])
    assert score(judge, response="Alpha is one. Beta is two. Gamma is three.") == pytest.approx(2 / 3)
    assert [v["supported"] for v in judge.last_verdicts] == [True, True, False]


def test_claim_check_asks_one_constrained_question_per_sentence():
    judge, sent = claim_judge([True, True])
    score(judge)
    assert len(sent) == 2
    assert sent[0]["format"] == CLAIM_SCHEMA
    assert sent[0]["options"]["temperature"] == 0 and sent[0]["options"]["seed"] == 42
    prompt = sent[0]["messages"][0]["content"]
    assert "Heading A\nAlpha text." in prompt and "What are they?" in prompt and "Alpha is one." in prompt
    assert "Beta is two." not in prompt


def test_claim_check_schema_puts_the_reason_before_the_verdict():
    # Ollama writes keys in alphabetical order, so the model gives its reason before deciding.
    assert sorted(CLAIM_SCHEMA["properties"]) == ["reason", "supported"]
    assert set(CLAIM_SCHEMA["required"]) == {"reason", "supported"}


def test_a_verdict_without_a_boolean_is_an_error():
    judge, _ = claim_judge(['{"reason": "r", "supported": "yes"}'])
    with pytest.raises(TypeError):
        score(judge, response="Alpha is one.")


def test_an_answer_with_no_sentence_is_an_error():
    judge, _ = claim_judge([])
    with pytest.raises(ValueError):
        score(judge, response="   ")


def guardian(reply):
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": reply}})

    client = httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handler))
    return GuardianJudge("granite3-guardian:2b", client=client), sent


@pytest.mark.parametrize(("reply", "expected"), [("No", 1.0), ("Yes", 0.0), (" yes.", 0.0)])
def test_guardian_yes_means_not_grounded(reply, expected):
    judge, _ = guardian(reply)
    assert score(judge) == expected
    assert judge.last_verdicts[0]["supported"] is (expected == 1.0)


def test_guardian_sends_the_groundedness_risk_the_context_and_the_whole_answer():
    judge, sent = guardian("No")
    score(judge, response="Alpha is one. Beta is two.", contexts=("Heading A\nAlpha text.", "B\nBeta text."))
    assert [m["role"] for m in sent[0]["messages"]] == ["system", "context", "assistant"]
    assert sent[0]["messages"][0]["content"] == "groundedness"
    assert sent[0]["messages"][1]["content"] == "Heading A\nAlpha text.\n\nB\nBeta text."
    assert sent[0]["messages"][2]["content"] == "Alpha is one. Beta is two."
    assert sent[0]["options"]["temperature"] == 0 and len(sent) == 1


def test_guardian_rejects_an_answer_that_is_not_yes_or_no():
    judge, _ = guardian("Maybe")
    with pytest.raises(ValueError):
        score(judge)


def test_guardian_judges_faithfulness_only():
    judge, sent = guardian("No")
    assert judge.metrics == ("faithfulness",)
    item = scored()  # an answered case with gold, so all four metrics would apply
    judge_cases(judge, {"c1": case()}, [item], STORE)
    assert item["judged"] == {"faithfulness": [1.0]} and len(sent) == 1


def test_make_judge_picks_the_guardian_method():
    env = {"JUDGE_PROVIDER": "ollama", "JUDGE_MODEL": "granite3-guardian:2b", "LLM_MODEL": "m:1", "JUDGE_METHOD": "guardian"}
    assert isinstance(make_judge(env), GuardianJudge)


def minicheck(replies):
    sent = []
    answers = iter(replies)

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": next(answers)}})

    client = httpx.AsyncClient(base_url="http://test", transport=httpx.MockTransport(handler))
    return MiniCheckJudge("bespoke-minicheck:7b", client=client), sent


def test_minicheck_scores_the_share_of_sentences_it_finds_supported():
    judge, _ = minicheck(["Yes", "No", "Yes"])
    assert score(judge, response="Alpha is one. Beta is two. Gamma is three.") == pytest.approx(2 / 3)
    assert [v["supported"] for v in judge.last_verdicts] == [True, False, True]


def test_minicheck_uses_the_model_card_prompt_one_sentence_at_a_time():
    judge, sent = minicheck(["Yes", "Yes"])
    score(judge, response="Alpha is one. Beta is two.", contexts=("Heading A\nAlpha text.", "B\nBeta text."))
    assert len(sent) == 2
    assert sent[0]["messages"] == [
        {"role": "user", "content": "Document: Heading A\nAlpha text.\n\nB\nBeta text.\nClaim: Alpha is one."}
    ]
    assert sent[1]["messages"][0]["content"].endswith("\nClaim: Beta is two.")
    assert sent[0]["options"]["temperature"] == 0


def test_minicheck_rejects_a_reply_that_is_not_yes_or_no():
    judge, _ = minicheck(["Probably"])
    with pytest.raises(ValueError):
        score(judge, response="Alpha is one.")


def test_make_judge_picks_the_minicheck_method():
    env = {"JUDGE_PROVIDER": "ollama", "JUDGE_MODEL": "bespoke-minicheck:7b", "LLM_MODEL": "m:1", "JUDGE_METHOD": "minicheck"}
    judge = make_judge(env)
    assert isinstance(judge, MiniCheckJudge) and judge.metrics == ("faithfulness",)


def test_other_metrics_go_to_the_ragas_judge_or_are_refused():
    judge, _ = claim_judge([])
    with pytest.raises(JudgeUnavailable):
        asyncio.run(judge.ascore("context_recall", user_input="q", reference="r", retrieved_contexts=[]))
    delegated, _ = claim_judge([], others=FakeJudge({"context_recall": [0.25]}))
    assert asyncio.run(delegated.ascore("context_recall", user_input="q", reference="r", retrieved_contexts=[])) == 0.25


def test_store_context_is_the_heading_then_the_text():
    store = ChunkStore({"x:0": ("x", "Line one.\r\nLine two.", "Doc > Section")})
    assert store.context("x:0") == "Doc > Section\nLine one.\nLine two."
    assert STORE.context("a:0") == "Alpha text."


def test_calibration_rebuilds_each_context_from_its_run(tmp_path):
    store = ChunkStore({"a:0": ("a", "Alpha text.", "A > Specs"), "b:0": ("b", "Beta text.", "B")})
    run = {"cases": [{"id": "g1", "retrieved": ["b:0", "a:0"]}]}
    (tmp_path / "r1.json").write_text(json.dumps(run), encoding="utf-8")
    rows = [{"item": "1", "run_id": "r1", "case_id": "g1"}]
    assert contexts_for(rows, store, tmp_path) == [["B\nBeta text.", "A > Specs\nAlpha text."]]
    with pytest.raises(SystemExit):
        contexts_for([{"item": "2", "run_id": "missing", "case_id": "g1"}], store, tmp_path)


def test_calibration_records_its_method_and_metric():
    rows = [{"item": "1", "case_id": "g1", "supported": "yes"}]
    result = summarise(rows, [1.0], "j:1", "me", "claim-check", [[{"sentence": "s", "supported": True, "reason": ""}]])
    assert (result["method"], result["metric"]) == ("claim-check", "faithfulness")
    assert result["pairs"][0]["verdicts"][0]["supported"] is True


def test_kappa():
    assert cohen_kappa([True, True, False, False], [True, True, False, False]) == 1.0
    assert cohen_kappa([True, False, True, False], [True, True, False, False]) == 0.0
    # A judge that always says yes agrees 80% of the time here, and kappa shows it learned nothing.
    assert cohen_kappa([True] * 8 + [False] * 2, [True] * 10) == 0.0
    assert cohen_kappa([True, True], [True, True]) is None


def run_report(run_id, answers):
    return {
        "run_id": run_id,
        "cases": [
            {
                "id": cid,
                "split": "dev",
                "status": 200,
                "refused": refused,
                "expected_behaviour": "answer",
                "question": f"q {cid}?",
                "answer": answer,
                "retrieved": ["a:0", "b:0"],
            }
            for cid, answer, refused in answers
        ],
    }


def test_label_file_is_blind_distinct_and_never_overwritten(tmp_path):
    first = run_report("r1", [(f"g{i:03}", f"answer {i}", False) for i in range(20)] + [("g900", "no", True)])
    second = run_report("r2", [(f"g{i:03}", f"answer {i}", False) for i in range(10)] + [(f"g{i:03}", f"other {i}", False) for i in range(20, 35)])
    path = tmp_path / "labels.csv"
    chosen = make_labels([first, second], STORE, path, size=30)
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    assert len(rows) == 30 and len({(r["case_id"], r["answer"]) for r in rows}) == 30
    assert "g900" not in {r["case_id"] for r in rows}
    assert set(rows[0]) == set(calibrate_judge.FIELDS) and all(r["supported"] == "" for r in rows)
    assert not any("score" in field for field in rows[0])
    assert rows[0]["context"] == "Alpha text." + calibrate_judge.SEPARATOR + "Beta text."
    assert len(chosen) == 30
    with pytest.raises(SystemExit):
        make_labels([first, second], STORE, path, size=30)


def test_too_few_answers_is_an_error(tmp_path):
    with pytest.raises(SystemExit, match="only 1"):
        make_labels([run_report("r", [("g1", "a", False)])], STORE, tmp_path / "l.csv", size=30)


def test_labels_must_all_be_yes_or_no(tmp_path):
    path = tmp_path / "labels.csv"
    path.write_bytes(b"\xef\xbb\xbfitem,supported\n1,yes\n2,maybe\n3,\n")
    rows, problems = read_labels(path)
    assert len(rows) == 3 and len(problems) == 2


def test_summary_passes_only_at_both_thresholds():
    rows = [{"item": str(i), "case_id": f"g{i}", "supported": "yes" if i < 6 else "no"} for i in range(10)]
    exact = summarise(rows, [1.0] * 6 + [0.5] * 4, "j:1", "me")
    assert (exact["agreement"], exact["kappa"], exact["passed"]) == (1.0, 1.0, True)
    always_yes = summarise(rows, [0.9999999999] * 10, "j:1", "me")
    assert always_yes["agreement"] == 0.6 and not always_yes["passed"]
    errors = summarise(rows, [None] * 10, "j:1", "me")
    assert errors["judge_errors"] == 10 and not errors["passed"]


def test_high_agreement_with_no_kappa_does_not_pass():
    # 9 of 10 answers are supported, and a judge that always says yes agrees 90% of the time.
    rows = [{"item": str(i), "case_id": f"g{i}", "supported": "yes" if i < 9 else "no"} for i in range(10)]
    result = summarise(rows, [1.0] * 10, "j:1", "me")
    assert result["agreement"] == 0.9 and result["kappa"] == 0.0 and not result["passed"]


def test_the_result_records_who_labelled():
    rows = [{"item": "1", "case_id": "g1", "supported": "yes"}, {"item": "2", "case_id": "g2", "supported": "no"}]
    assert summarise(rows, [1.0, 0.5], "j:1", "Shockwawe10")["labelled_by"] == "Shockwawe10"


@pytest.mark.parametrize("argv", [[], ["--labelled-by", "  "]], ids=["missing", "blank"])
def test_calibration_will_not_run_without_naming_the_labeller(argv):
    with pytest.raises(SystemExit) as error:
        calibrate_judge.main(argv)
    assert error.value.code == 2


TABLE = f"""{START}

| Metric | Baseline | Current | Threshold | Gate |
| --- | --- | --- | --- | --- |
| Faithfulness | — | — | ≥ 0.90 | PR |
| Judge agreement / Cohen's κ (vs my labels) | — | — | ≥ 0.85 / ≥ 0.60 | end of stage |

{END}
"""


def judged_report(**overrides):
    base = {
        "run_id": "r",
        "git_sha": "abcdef1",
        "dataset_version": "1.2",
        "top_k": 5,
        "judge_model": "j:1",
        "judge_passes": 1,
        "metrics": {"faithfulness": 0.8, "faithfulness_spread": None},
    }
    return {**base, **overrides}


@pytest.mark.parametrize(
    "calibration",
    [None, {"passed": False, "judge_model": "j:1", "agreement": 0.5, "kappa": 0.1}, {"passed": True, "judge_model": "other:1", "agreement": 0.9, "kappa": 0.7}],
    ids=["no calibration", "failed", "another judge"],
)
def test_judged_scores_stay_hidden_without_a_passed_calibration_of_that_judge(calibration):
    assert f"| Faithfulness | {DASH} | {DASH} |" in render(TABLE, None, judged_report(), calibration)


def test_judged_scores_show_after_calibration_passes():
    calibration = {"passed": True, "judge_model": "j:1", "agreement": 0.9, "kappa": 0.72}
    new = render(TABLE, None, judged_report(metrics={"faithfulness": 0.8, "faithfulness_spread": 0.05}), calibration)
    assert "| Faithfulness | — | 0.80 (spread 0.05) |" in new
    assert "| Judge agreement / Cohen's κ (vs my labels) | — | 0.90 / 0.72 |" in new


def test_a_failed_calibration_is_still_reported():
    calibration = {"passed": False, "judge_model": "j:1", "agreement": 0.5, "kappa": None}
    assert "| — | 0.50 / undefined |" in render(TABLE, None, judged_report(), calibration)


@pytest.mark.parametrize(
    ("calibration_method", "run_method", "shown"),
    [("claim-check", "claim-check", True), ("claim-check", "ragas", False), ("ragas", "claim-check", False)],
)
def test_a_calibration_counts_only_for_the_same_method(calibration_method, run_method, shown):
    calibration = {"passed": True, "judge_model": "j:1", "method": calibration_method, "agreement": 0.9, "kappa": 0.7}
    new = render(TABLE, None, judged_report(judge_method=run_method), calibration)
    assert ("| Faithfulness | — | 0.80 |" in new) is shown


def test_a_faithfulness_calibration_never_shows_the_other_judged_metrics():
    table = TABLE.replace("| Faithfulness |", "| Context recall |")
    calibration = {"passed": True, "judge_model": "j:1", "agreement": 0.9, "kappa": 0.7}
    report = judged_report(metrics={"context_recall": 0.9, "context_recall_spread": None})
    assert f"| Context recall | {DASH} | {DASH} |" in render(table, None, report, calibration)


def test_an_unjudged_run_shows_no_judged_score():
    calibration = {"passed": True, "judge_model": "j:1", "agreement": 0.9, "kappa": 0.72}
    assert f"| Faithfulness | {DASH} | {DASH} |" in render(TABLE, None, judged_report(judge_passes=0), calibration)

"""The answer check: one unsupported sentence turns an answer into the fixed abstention."""

import json

import httpx
import pytest

from app.checker import CheckUnavailable, MiniCheck, document, sentences
from app.generator import ABSTAIN_SENTENCE, Answer
from app.retriever import Hit

MODEL = "bespoke-minicheck:7b"
DIGEST = "66607904c165445540331c2f005bb5120edd939008ba1fe1e75151ed827a7a00"
HITS = [
    Hit("c1", "warranty", "The product warranty is 15 years.", "Warranty > Product", 1, 0.9),
    Hit("c2", "warranty", "The installation warranty is 5 years.", "", 2, 0.8),
]


def checker(replies, status=200, installed=DIGEST):
    sent = []

    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": MODEL, "digest": installed}]})
        sent.append(json.loads(request.content))
        if status != 200:
            return httpx.Response(status, text="model not found")
        return httpx.Response(200, json={"message": {"content": replies[len(sent) - 1]}})

    client = httpx.Client(base_url="http://test", transport=httpx.MockTransport(handler))
    return MiniCheck(MODEL, DIGEST, client=client), sent


def answer(text, citations=(1,), flags=()):
    return Answer(text, False, list(citations), list(flags), raw_outputs=["raw"])


def test_supported_answer_goes_out_unchanged():
    check, _ = checker(["Yes", "Yes"])
    result = answer("The product warranty is 15 years. The installation warranty is 5 years.")
    reviewed, verdicts = check.review(result, HITS)
    assert reviewed == result
    assert [item["supported"] for item in verdicts] == [True, True]


def test_one_unsupported_sentence_turns_the_answer_into_the_abstention():
    check, _ = checker(["Yes", "No"])
    reviewed, verdicts = check.review(answer("The warranty is 15 years. It ends on March 2, 2031.", flags=["retried"]), HITS)
    assert (reviewed.answer, reviewed.abstained, reviewed.citations) == (ABSTAIN_SENTENCE, True, [])
    assert reviewed.flags == ["answer_check_failed", "retried"]
    assert reviewed.raw_outputs == ["raw"]  # the model's own answer stays in the trace
    assert verdicts[1] == {"sentence": "It ends on March 2, 2031.", "supported": False, "reply": "No"}


@pytest.mark.parametrize("reply", ["", "Maybe", "No."])
def test_anything_but_a_clear_yes_fails_closed(reply):
    check, _ = checker([reply])
    reviewed, _ = check.review(answer("The warranty is 15 years."), HITS)
    assert reviewed.abstained


def test_yes_with_a_full_stop_counts_as_supported():
    check, _ = checker(["Yes."])
    assert not check.review(answer("The warranty is 15 years."), HITS)[0].abstained


def test_answer_with_no_sentences_is_not_waved_through():
    check, sent = checker([])
    assert check.review(answer("   "), HITS)[0].abstained
    assert sent == []


def test_abstention_is_not_checked():
    check, sent = checker([])
    abstention = Answer(ABSTAIN_SENTENCE, True, [], reason="not in the context")
    assert check.review(abstention, HITS) == (abstention, [])
    assert sent == []


def test_each_sentence_is_checked_against_every_passage_with_its_heading():
    check, sent = checker(["Yes", "Yes"])
    check.review(answer("First claim. Second claim."), HITS)
    passages = "Warranty > Product\nThe product warranty is 15 years.\n\nThe installation warranty is 5 years."
    assert [item["messages"][0]["content"] for item in sent] == [
        f"Document: {passages}\nClaim: First claim.",
        f"Document: {passages}\nClaim: Second claim.",
    ]
    assert sent[0]["model"] == MODEL
    assert sent[0]["options"]["temperature"] == 0
    assert document(HITS) == passages


def test_sentence_split_keeps_abbreviations():
    assert sentences("Example Solar Ltd. designs racks. It installs them.") == [
        "Example Solar Ltd. designs racks.",
        "It installs them.",
    ]


def test_ollama_error_is_unavailable_not_a_pass():
    check, _ = checker([], status=404)
    with pytest.raises(CheckUnavailable):
        check.review(answer("The warranty is 15 years."), HITS)


def test_pin_mismatch_is_unavailable():
    check, _ = checker([], installed="0" * 64)
    with pytest.raises(CheckUnavailable, match="pinned"):
        check.check_pinned()


def test_off_by_default_and_unknown_method_rejected():
    assert MiniCheck.from_env({}) is None
    assert MiniCheck.from_env({"ANSWER_CHECK": "off"}) is None
    with pytest.raises(CheckUnavailable, match="ANSWER_CHECK must be"):
        MiniCheck.from_env({"ANSWER_CHECK": "guardian"})
    with pytest.raises(CheckUnavailable, match="must be set"):
        MiniCheck.from_env({"ANSWER_CHECK": "minicheck"})
    on = MiniCheck.from_env({"ANSWER_CHECK": "minicheck", "ANSWER_CHECK_MODEL": MODEL, "ANSWER_CHECK_DIGEST": DIGEST})
    assert (on.model, on.digest) == (MODEL, DIGEST)

"""The golden-set validator must pass the real dataset and fail on each kind of break."""

import copy

import pytest

from app.chunker import ChunkConfig
from evals.chunk_report import KB_DIR
from evals.validate_golden import check, load_corpus, load_dataset, tokens


@pytest.fixture(scope="module")
def corpus():
    return load_corpus(KB_DIR, ChunkConfig())


@pytest.fixture(scope="module")
def cases():
    return load_dataset()


def errors_after(cases, corpus, change):
    broken = copy.deepcopy(cases)
    change(broken)
    return check(broken, corpus)[0]


def first(cases, **match):
    return next(c for c in cases if all(c[k] == v for k, v in match.items()))


def test_real_dataset_passes(cases, corpus):
    assert check(cases, corpus)[0] == []


def test_shifted_offset_is_caught(cases, corpus):
    def change(broken):
        span = first(broken, category="numeric")["gold"][0][0]
        span["start"] += 1

    assert any("does not match" in e for e in errors_after(cases, corpus, change))


def test_seen_case_in_holdout_is_caught(cases, corpus):
    def change(broken):
        first(broken, seen=True)["split"] = "holdout"

    assert any(
        "seen cases must be in dev" in e for e in errors_after(cases, corpus, change)
    )


def test_single_chunk_multi_document_case_is_caught(cases, corpus):
    def change(broken):
        case = first(broken, category="multi-document")
        case["gold"] = case["gold"][:1]

    assert any(
        "at least 2 gold groups" in e for e in errors_after(cases, corpus, change)
    )


def test_refusing_case_with_gold_is_caught(cases, corpus):
    def change(broken):
        refusing = first(broken, category="out of scope")
        refusing["gold"] = copy.deepcopy(first(broken, category="numeric")["gold"])

    assert any(
        "refusing case must have no gold" in e
        for e in errors_after(cases, corpus, change)
    )


def test_shared_quote_across_splits_is_caught(cases, corpus):
    def change(broken):
        dev = first(broken, split="dev", category="numeric", seen=False)
        holdout = first(broken, split="holdout", category="numeric")
        holdout["gold"] = copy.deepcopy(dev["gold"])
        holdout["source_ids"] = dev["source_ids"]

    assert any("shared across splits" in e for e in errors_after(cases, corpus, change))


def test_near_miss_without_retrieved_distractor_is_caught(cases, corpus):
    def change(broken):
        first(broken, subtype="near miss")["distractors"] = [
            {"doc_id": "company-contacts", "quote": "Monday to Friday, 9:00 to 18:00."}
        ]

    assert any("not a near miss" in e for e in errors_after(cases, corpus, change))


def test_must_include_missing_from_answer_is_caught(cases, corpus):
    def change(broken):
        first(broken, category="numeric")["must_include"].append("999 m/s")

    assert any("must_include" in e for e in errors_after(cases, corpus, change))


def test_tokens_drop_stopwords_and_plurals():
    assert tokens("What are the posts for GF-2?") == ["post", "gf-2"]


@pytest.mark.parametrize("ending", [b"\n", b"\r\n"])
def test_offsets_hold_with_either_line_ending(cases, tmp_path, ending):
    """Git stores the KB with LF, a Windows checkout has CRLF: both must validate."""
    for path in KB_DIR.glob("*.md"):
        raw = path.read_bytes().replace(b"\r\n", b"\n")
        (tmp_path / path.name).write_bytes(raw.replace(b"\n", ending))
    assert check(cases, load_corpus(tmp_path, ChunkConfig()))[0] == []

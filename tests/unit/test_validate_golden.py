"""The golden-set validator must pass the real dataset and fail on each kind of break."""

import copy

import pytest

from app.chunker import ChunkConfig
from evals.chunk_report import KB_DIR
from evals.validate_golden import (
    agreement,
    check,
    check_frozen,
    holdout_hash,
    load_corpus,
    load_dataset,
    main,
    tokens,
)


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


def test_must_include_inside_a_longer_number_is_caught(cases, corpus):
    def change(broken):
        case = first(broken, category="numeric")
        case["must_include"] = ["5 years"]
        case["expected_answer"] = "The warranty is 15 years."

    assert any("must_include" in e for e in errors_after(cases, corpus, change))


def test_clarify_case_with_must_include_is_caught(cases, corpus):
    def change(broken):
        case = first(broken, category="ambiguous")
        case["must_include"] = ["30 m/s"]
        case["expected_answer"] += " 30 m/s."

    assert any("clarify case must have no must_include" in e for e in errors_after(cases, corpus, change))


@pytest.mark.parametrize("reviewer", ["", "  ", 5])
def test_empty_reviewer_is_caught(cases, corpus, reviewer):
    def change(broken):
        first(broken, split="dev")["reviewed_by"] = reviewer

    assert any("reviewed_by" in e for e in errors_after(cases, corpus, change))


def test_unknown_author_is_caught(cases, corpus):
    def change(broken):
        first(broken, split="dev")["authored_by"] = "gpt"

    assert any("authored_by" in e for e in errors_after(cases, corpus, change))


def test_mixed_dataset_versions_are_caught(cases, corpus):
    def change(broken):
        first(broken, split="dev")["dataset_version"] = "9.9"

    assert any("disagree on dataset_version" in e for e in errors_after(cases, corpus, change))


def test_holdout_matches_the_frozen_hash_and_version(cases):
    # Runs in CI, so an edit to a holdout case cannot slip through without a deliberate freeze.
    assert check_frozen(cases) == []


def freeze_file(tmp_path, digest, version):
    path = tmp_path / "frozen.sha256"
    path.write_text(f"{digest} dataset_version={version}\n", encoding="utf-8")
    return path


def test_holdout_edit_without_a_version_bump_is_caught(cases, tmp_path):
    broken = copy.deepcopy(cases)
    path = freeze_file(tmp_path, holdout_hash(broken), broken[0]["dataset_version"])
    first(broken, split="holdout")["question"] += " Really?"
    assert any("bump dataset_version" in e for e in check_frozen(broken, path))


def test_version_bump_without_a_freeze_is_caught(cases, tmp_path):
    path = freeze_file(tmp_path, holdout_hash(cases), "0.9")
    assert any("run --freeze" in e for e in check_frozen(cases, path))


def annotation(tmp_path, cases, labels, bom=False):
    rows = ["id,question,behaviour,short_answer,notes"]
    for case, label in zip(cases, labels):
        rows.append(f"{case['id']},q,{label},,")
    data = "\n".join(rows) + "\n"
    path = tmp_path / "blind.csv"
    path.write_bytes((b"\xef\xbb\xbf" if bom else b"") + data.encode("utf-8"))
    return path


def test_agreement_reads_an_excel_file_with_a_byte_order_mark(cases, tmp_path):
    picked = cases[:10]
    path = annotation(tmp_path, picked, [c["expected_behaviour"] for c in picked], bom=True)
    assert agreement(cases, path) == (1.0, [])


def test_agreement_refuses_an_incomplete_file(cases, tmp_path):
    picked = cases[:10]
    labels = [c["expected_behaviour"] for c in picked[:1]] + [""] * 9
    share, problems = agreement(cases, annotation(tmp_path, picked, labels))
    assert share is None
    assert len(problems) == 9
    assert all(problem.endswith("behaviour is empty") for problem in problems)


def test_agreement_refuses_an_unknown_label(cases, tmp_path):
    share, problems = agreement(cases, annotation(tmp_path, cases[:1], ["maybe"]))
    assert share is None
    assert "not one of" in problems[0]


@pytest.mark.parametrize(("agreeing", "code"), [(9, 0), (8, 1)])
def test_agreement_exit_code_follows_the_90_percent_rule(cases, tmp_path, agreeing, code):
    picked = cases[:10]
    other = {"answer": "abstain"}
    labels = [
        c["expected_behaviour"] if i < agreeing else other.get(c["expected_behaviour"], "answer")
        for i, c in enumerate(picked)
    ]
    assert main(["--agreement", str(annotation(tmp_path, picked, labels))]) == code


def test_tokens_drop_stopwords_and_plurals():
    assert tokens("What are the posts for GF-2?") == ["post", "gf-2"]


@pytest.mark.parametrize("ending", [b"\n", b"\r\n"])
def test_offsets_hold_with_either_line_ending(cases, tmp_path, ending):
    """Git stores the KB with LF, a Windows checkout has CRLF: both must validate."""
    for path in KB_DIR.glob("*.md"):
        raw = path.read_bytes().replace(b"\r\n", b"\n")
        (tmp_path / path.name).write_bytes(raw.replace(b"\n", ending))
    assert check(cases, load_corpus(tmp_path, ChunkConfig()))[0] == []

"""Phoenix export (evals/phoenix_export.py): trace lines become a span tree per request, failed cases marked."""

import json

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode

from evals.phoenix_export import failed, records_for, send, spans_for

REPORT = {
    "run_id": "20261107T100000Z-pipeline-dev",
    "timestamp": "2026-11-07T10:10:00+00:00",
    "split": "dev",
    "llm_model": "qwen3:4b-instruct",
    "embedding_model": "nomic-embed-text:v1.5",
    "temperature": "0",
    "seed": "42",
    "cases": [
        {"id": "g001", "question": "How long is the warranty?", "expected_behaviour": "answer", "behaviour_ok": True, "hit": True, "missing_facts": []},
        {"id": "g002", "question": "Do you sell to Mars?", "expected_behaviour": "abstain", "behaviour_ok": False, "hit": None, "missing_facts": [], "refused": False},
        {"id": "g071", "question": "Wie lange gilt die Garantie?", "expected_behaviour": "language refusal", "behaviour_ok": True},
    ],
}


def answered(question, time, unsupported=False):
    return {
        "time": time,
        "question": question,
        "prompt_version": "v5",
        "status": 200,
        "hits": [
            {"chunk_id": "warranty:0:aa", "doc_id": "warranty", "rank": 1, "score": 0.91, "text": "15 years."},
            {"chunk_id": "other:0:bb", "doc_id": "other", "rank": 2, "score": 0.42, "text": "Nothing."},
        ],
        "raw_outputs": ['{"status": "answer", "answer": "15 years.", "citations": [1]}'],
        "parsed": {"answer": "15 years.", "abstained": False, "citations": [1]},
        "answer_check": {"model": "bespoke-minicheck:7b", "ms": 3000.0, "verdicts": [{"sentence": "15 years.", "supported": not unsupported, "reply": "Yes"}]},
        "output_guard": [],
        "flags": [],
        "timings_ms": {"embed": 100.0, "retrieve": 5.0, "generate": 2000.0, "total": 5200.0},
    }


LANGUAGE = {"time": "2026-11-07T10:05:00+00:00", "question": "Wie lange gilt die Garantie?", "status": 200, "flags": ["not_english"], "parsed": {"answer": "English only."}}


@pytest.fixture
def trace_dir(tmp_path):
    lines = [
        answered("How long is the warranty?", "2026-11-07T09:59:00+00:00"),  # before the run: another run's request
        answered("How long is the warranty?", "2026-11-07T10:01:00+00:00"),
        answered("Do you sell to Mars?", "2026-11-07T10:02:00+00:00", unsupported=True),
        LANGUAGE,
        answered("A question of no case", "2026-11-07T10:03:00+00:00"),
    ]
    (tmp_path / "2026-11-07.jsonl").write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")
    return tmp_path


def test_each_case_gets_its_request_from_inside_the_run_window(trace_dir):
    pairs = records_for(REPORT, trace_dir)
    assert [(case["id"], record["time"][11:16]) for case, record in pairs] == [("g001", "10:01"), ("g002", "10:02"), ("g071", "10:05")]


def test_a_request_in_the_run_s_last_second_is_inside_the_window(tmp_path):
    """The run's timestamp is cut to whole seconds; the last trace line is not."""
    last = {**LANGUAGE, "time": "2026-11-07T10:10:00.917992+00:00"}
    (tmp_path / "2026-11-07.jsonl").write_text(json.dumps(last) + "\n", encoding="utf-8")
    assert [case["id"] for case, _ in records_for(REPORT, tmp_path)] == ["g071"]


def test_a_holdout_run_is_refused():
    with pytest.raises(SystemExit, match="dev runs only"):
        records_for({**REPORT, "split": "holdout"})


def test_an_answered_request_is_a_tree_of_five_spans_in_order(trace_dir):
    case, record = records_for(REPORT, trace_dir)[0]
    spans = spans_for(case, record, REPORT)
    assert [(s["name"], s["kind"], s["parent"]) for s in spans] == [
        ("ask", "CHAIN", None), ("embed", "EMBEDDING", 0), ("retrieve", "RETRIEVER", 0), ("generate", "LLM", 0), ("answer check", "GUARDRAIL", 0),
    ]
    root, embed, retrieve, generate, check = spans
    assert root["end"] - root["start"] == 5200 * 1_000_000
    assert embed["start"] == root["start"] and retrieve["start"] == embed["end"] and generate["start"] == retrieve["end"]
    assert check["start"] == generate["end"] and check["end"] <= root["end"]
    assert retrieve["attributes"]["retrieval.documents.0.document.id"] == "warranty:0:aa"
    assert retrieve["attributes"]["retrieval.documents.1.document.score"] == 0.42
    assert generate["attributes"]["llm.model_name"] == "qwen3:4b-instruct"
    assert root["attributes"]["tag.tags"] == ["passed"] and root["error"] is None and check["error"] is None


def test_the_check_reads_the_model_s_answer_not_the_refusal_that_replaced_it(trace_dir):
    case, record = records_for(REPORT, trace_dir)[1]
    blocked = {**record, "parsed": {**record["parsed"], "answer": "I can't answer that from the available documents.", "abstained": True}}
    root, *_, check = spans_for(case, blocked, REPORT)
    assert check["attributes"]["input.value"] == "15 years."
    assert root["attributes"]["output.value"] == "I can't answer that from the available documents."


def test_a_failed_case_and_an_unsupported_sentence_are_marked(trace_dir):
    case, record = records_for(REPORT, trace_dir)[1]
    root, *_, check = spans_for(case, record, REPORT)
    assert failed(case) and root["attributes"]["eval.failed"] and root["attributes"]["tag.tags"] == ["failed"]
    assert root["error"] == "case g002 failed its eval"
    assert check["error"] and "15 years." in check["attributes"]["metadata"]


@pytest.mark.parametrize(
    "case, is_failed",
    [
        ({"behaviour_ok": True, "hit": True, "missing_facts": []}, False),
        ({"behaviour_ok": None, "hit": None}, False),
        ({"behaviour_ok": True, "hit": False}, True),
        ({"behaviour_ok": True, "hit": True, "missing_facts": ["5 years"]}, True),
        ({"behaviour_ok": False}, True),
    ],
)
def test_failed_follows_the_harness_verdict(case, is_failed):
    assert failed(case) is is_failed


def test_an_english_only_reply_has_only_its_root_span(trace_dir):
    case, record = records_for(REPORT, trace_dir)[2]
    assert [s["name"] for s in spans_for(case, record, REPORT)] == ["ask"]


def test_spans_reach_the_exporter_with_parents_status_and_project(trace_dir):
    exporter = InMemorySpanExporter()
    requests = [spans_for(case, record, REPORT) for case, record in records_for(REPORT, trace_dir)]
    assert send(requests, "rag-test", exporter) == 5 + 5 + 1
    spans = exporter.get_finished_spans()
    roots = [s for s in spans if s.parent is None]
    assert len(roots) == 3 and {s.resource.attributes["openinference.project.name"] for s in spans} == {"rag-test"}
    children = [s for s in spans if s.parent is not None]
    assert all(c.parent.span_id in {r.context.span_id for r in roots} for c in children)
    assert len({s.context.trace_id for s in roots}) == 3
    failed_roots = [s for s in roots if s.status.status_code == StatusCode.ERROR]
    assert [s.attributes["eval.case_id"] for s in failed_roots] == ["g002"]
    assert next(s for s in spans if s.name == "retrieve").attributes["openinference.span.kind"] == "RETRIEVER"

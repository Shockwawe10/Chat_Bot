"""Tests for the chunker report: the metric must be right before anyone trusts its number."""

import pytest

from app.chunker import Chunk
from evals.chunk_report import gold_span_coverage, length_histogram, main, span_in_one_chunk


def make_chunk(text, start, end):
    return Chunk(
        id="x",
        doc_id="doc",
        text=text[start:end],
        index_text=text[start:end],
        start=start,
        end=end,
        heading_path=(),
        chunk_index=0,
        chunker_version="v1",
        oversize=False,
    )


TEXT = "alpha beta gamma delta"
CHUNKS = [make_chunk(TEXT, 0, 10), make_chunk(TEXT, 11, 22)]


def test_span_inside_one_chunk_counts():
    assert span_in_one_chunk(TEXT, CHUNKS, "gamma delta")


def test_span_across_two_chunks_does_not_count():
    assert not span_in_one_chunk(TEXT, CHUNKS, "beta gamma")


def test_any_occurrence_inside_one_chunk_counts():
    text = "aa bb aa"
    chunks = [make_chunk(text, 0, 1), make_chunk(text, 6, 8)]
    assert span_in_one_chunk(text, chunks, "aa")


def test_span_missing_from_the_document_is_an_error_not_a_miss():
    with pytest.raises(ValueError):
        span_in_one_chunk(TEXT, CHUNKS, "omega")


def test_coverage_is_the_share_of_contained_spans():
    corpus = {"doc": (TEXT, CHUNKS)}
    spans = [{"doc_id": "doc", "quote": "gamma delta"}, {"doc_id": "doc", "quote": "beta gamma"}]
    assert gold_span_coverage(spans, corpus) == 0.5


def test_coverage_refuses_an_empty_gold_set():
    with pytest.raises(ValueError):
        gold_span_coverage([], {})


def report_for(monkeypatch, capsys, target, maximum):
    monkeypatch.setenv("CHUNK_SIZE", target)
    monkeypatch.setenv("CHUNK_MAX", maximum)
    monkeypatch.setenv("CHUNK_MIN", "50")
    main()
    return capsys.readouterr().out


def test_report_prints_the_config_it_used_and_the_config_takes_effect(monkeypatch, capsys):
    tight = report_for(monkeypatch, capsys, "150", "300")
    loose = report_for(monkeypatch, capsys, "500", "800")
    assert "config: target=150 max=300 min=50 chunker=v1" in tight
    assert "config: target=500 max=800 min=50 chunker=v1" in loose
    count = lambda out: int(out.split(" documents, ")[1].split(" chunks")[0])
    assert count(tight) > count(loose)


def test_histogram_groups_lengths_into_buckets():
    chunks = [make_chunk("x" * 250, 0, 250), make_chunk("x" * 250, 0, 90), make_chunk("x" * 250, 0, 99)]
    assert length_histogram(chunks) == {0: 2, 200: 1}

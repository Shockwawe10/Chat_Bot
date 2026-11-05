"""BM25 keyword search and reciprocal rank fusion (app/keyword.py)."""

import math

import pytest

from app.keyword import RRF_K, Bm25, fuse, tokens


def test_tokens_keep_numbers_and_units_and_drop_stopwords():
    assert tokens("Can you build a 50 kWp system on our office roof?") == ["build", "50", "kwp", "system", "office", "roof"]
    assert tokens("Max snow load is 2.4 kN/m² and 1,000 m²") == ["max", "snow", "load", "2.4", "kn", "m", "1,000", "m"]


def test_exact_word_ranks_its_chunk_first():
    bm25 = Bm25(["roof", "size", "email"], ["Flat roof systems for office roofs.", "The smallest project is 100 kWp.", "Prices are not given by email."])
    assert bm25.ranking("Can you build a 50 kWp system?")[0] == "size"
    assert bm25.ranking("Can you email me a price?")[0] == "email"


def test_rare_word_counts_more_than_a_common_one_repeated():
    # By word counts alone "roof roof roof" wins; only the rarity of "kwp" puts "b" first.
    bm25 = Bm25(["a", "b", "c", "d"], ["roof roof roof", "kwp text", "roof one", "roof two"])
    assert bm25.ranking("roof kwp")[0] == "b"
    assert bm25.idf["kwp"] > bm25.idf["roof"]


def test_longer_chunk_scores_lower_for_the_same_match():
    bm25 = Bm25(["short", "long"], ["kwp minimum", "kwp minimum " + "filler words here " * 10])
    short, long = bm25.scores("kwp")
    assert short > long


def test_no_shared_word_scores_zero_and_ties_keep_index_order():
    bm25 = Bm25(["x", "y", "z"], ["alpha", "beta", "gamma"])
    assert bm25.scores("delta") == [0.0, 0.0, 0.0]
    assert bm25.ranking("delta") == ["x", "y", "z"]


def test_fusion_adds_reciprocal_ranks_and_sorts_best_first():
    fused = dict(fuse(["a", "b", "c"], ["c", "a", "b"]))
    assert fused["a"] == pytest.approx(1 / (RRF_K + 1) + 1 / (RRF_K + 2))
    assert fused["c"] == pytest.approx(1 / (RRF_K + 3) + 1 / (RRF_K + 1))
    assert [chunk_id for chunk_id, _ in fuse(["a", "b", "c"], ["c", "a", "b"])] == ["a", "c", "b"]


def test_fusion_lets_a_keyword_hit_overtake_a_middling_dense_rank():
    dense = ["roof1", "roof2", "roof3", "roof4", "roof5", "roof6", "roof7", "roof8", "size"]
    keyword = ["size", "roof1", "roof2", "roof3", "roof4", "roof5", "roof6", "roof7", "roof8"]
    top = [chunk_id for chunk_id, _ in fuse(dense, keyword)][:8]
    assert "size" in top
    assert math.isclose(dict(fuse(dense, keyword))["size"], 1 / (RRF_K + 9) + 1 / (RRF_K + 1))

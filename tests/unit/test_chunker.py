"""Tests for chunker v1: the invariants as property tests, then the edge-case fixtures."""

import logging

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from app.chunker import CHUNKER_VERSION, ChunkConfig, chunk, parse_document

CFG = ChunkConfig()
SMALL_CFG = ChunkConfig(target=60, max=100, min=20)

FRONT_MATTER = "---\nid: demo\ntitle: Demo\nlast_reviewed: 2026-10-28\n---\n"


def check_invariants(text, cfg):
    """The fidelity, coverage, bounds and order invariants, for any input."""
    chunks = chunk(text, "doc", cfg)
    _, body_start = parse_document(text, "doc")

    covered = set()
    for item in chunks:
        assert text[item.start : item.end] == item.text, "fidelity"
        assert len(item.text) <= cfg.max or item.oversize, "bounds"
        covered.update(range(item.start, item.end))
    missing = [i for i in range(body_start, len(text)) if i not in covered and not text[i].isspace()]
    assert not missing, "coverage"

    starts = [item.start for item in chunks]
    assert starts == sorted(set(starts)), "order"
    assert [item.chunk_index for item in chunks] == list(range(len(chunks)))
    return chunks


def check_no_boundary_inside(chunks, protected_spans):
    """The structure invariant: no chunk starts strictly inside a protected span."""
    for item in chunks:
        if item.oversize:
            continue
        for start, end in protected_spans:
            assert not start < item.start < end, f"boundary inside {start}-{end}"


word = st.text("abcdefgh", min_size=1, max_size=12)
sentence = st.lists(word, min_size=1, max_size=12).map(lambda words: " ".join(words) + ".")
paragraph = st.lists(sentence, min_size=1, max_size=8).map(" ".join)


@st.composite
def markdown_document(draw):
    """Build a document block by block and remember which spans must not be cut."""
    kinds = st.sampled_from(
        ["heading", "setext", "paragraph", "list", "table", "fence", "rule", "link_definition"]
    )
    newline = draw(st.sampled_from(["\n", "\r\n"]))
    text = draw(st.sampled_from(["", FRONT_MATTER.replace("\n", newline)]))
    protected = []

    def add_line(line):
        nonlocal text
        start = len(text)
        text += line + newline
        return start, start + len(line)

    for kind in draw(st.lists(kinds, min_size=1, max_size=10)):
        if kind == "heading":
            add_line("#" * draw(st.integers(1, 6)) + " " + draw(word))
        elif kind == "setext":
            add_line(draw(word))
            add_line(draw(st.sampled_from(["===", "---"])))
        elif kind == "paragraph":
            add_line(draw(paragraph))
        elif kind == "list":
            for item in draw(st.lists(sentence, min_size=1, max_size=6)):
                add_line(f"- {item}")
        elif kind == "table":
            add_line("| a | b |")
            add_line("| --- | --- |")
            for left, right in draw(st.lists(st.tuples(word, word), min_size=1, max_size=40)):
                protected.append(add_line(f"| {left} | {right} |"))
        elif kind == "fence":
            start, _ = add_line("```")
            for line in draw(st.lists(word, max_size=8)):
                add_line(line)
            _, end = add_line("```")
            protected.append((start, end))
        elif kind == "rule":
            add_line("---")
        elif kind == "link_definition":
            add_line(f"[{draw(word)}]: https://example.com/{draw(word)}")
        add_line("")
    return text, protected


@settings(max_examples=300, deadline=None)
@given(markdown_document(), st.sampled_from([CFG, SMALL_CFG]))
def test_invariants_hold_on_markdown_documents(document, cfg):
    text, protected = document
    chunks = check_invariants(text, cfg)
    check_no_boundary_inside(chunks, protected)


@settings(max_examples=300, deadline=None)
@given(st.text(max_size=400), st.sampled_from([CFG, SMALL_CFG]))
def test_invariants_hold_on_arbitrary_text(text, cfg):
    check_invariants(text, cfg)


@settings(max_examples=100, deadline=None)
@given(markdown_document())
def test_same_input_and_config_give_identical_chunks(document):
    text, _ = document
    assert chunk(text, "doc", CFG) == chunk(text, "doc", CFG)


def test_config_rejects_an_impossible_order():
    with pytest.raises(ValueError):
        ChunkConfig(target=900, max=800, min=100)


def test_empty_file_gives_no_chunks():
    assert chunk("", "doc", CFG) == []


def test_front_matter_only_gives_no_chunks():
    assert chunk(FRONT_MATTER, "doc", CFG) == []


def test_no_front_matter_uses_file_name_and_warns_about_date(caplog):
    with caplog.at_level(logging.WARNING):
        meta, body_start = parse_document("# Title\n\nText.\n", "data/kb/some-doc.md")
    assert meta.doc_id == "some-doc"
    assert meta.date is None
    assert body_start == 0
    assert "no date" in caplog.text


def test_front_matter_is_returned_separately_and_never_indexed():
    text = FRONT_MATTER + "# Title\n\nBody text.\n"
    meta, body_start = parse_document(text, "other-name.md")
    assert (meta.doc_id, meta.title, meta.date) == ("demo", "Demo", "2026-10-28")
    assert (meta.url, meta.version) == (None, None)
    chunks = chunk(text, "demo", CFG)
    assert all(item.start >= body_start for item in chunks)
    assert not any("last_reviewed" in item.index_text for item in chunks)


def test_unclosed_front_matter_is_treated_as_body_and_warns(caplog):
    text = "---\nid: demo\n\nNo closing line here.\n"
    with caplog.at_level(logging.WARNING):
        chunks = check_invariants(text, CFG)
    assert parse_document(text, "x.md")[1] == 0
    assert "not closed" in caplog.text
    assert "No closing line here." in chunks[0].text


def test_horizontal_rule_in_body_is_not_front_matter():
    text = FRONT_MATTER + "First part.\n\n---\n\nSecond part.\n"
    chunks = check_invariants(text, CFG)
    assert "First part." in chunks[0].text
    assert "Second part." in chunks[-1].text


def test_file_shorter_than_one_chunk_gives_one_chunk():
    chunks = check_invariants("Just one line.\n", CFG)
    assert [item.text for item in chunks] == ["Just one line."]
    assert chunks[0].chunker_version == CHUNKER_VERSION


def table_with_rows(rows):
    lines = ["| Key | Value |", "| --- | --- |"]
    lines += [f"| row {i} | value number {i} of the table |" for i in range(rows)]
    return "\n".join(lines) + "\n"


def test_table_within_max_stays_whole_even_above_target():
    table = table_with_rows(16)
    assert CFG.target < len(table) < CFG.max
    chunks = check_invariants(table, CFG)
    assert [item.text for item in chunks] == [table.strip()]


def test_table_above_max_splits_by_rows_and_repeats_the_header():
    table = table_with_rows(40)
    assert len(table) > CFG.max
    chunks = check_invariants(table, CFG)
    assert len(chunks) > 1
    for item in chunks:
        assert not item.oversize
        assert item.index_text.startswith("| Key | Value |\n| --- | --- |\n")
        assert all(line.startswith("|") for line in item.text.splitlines())
    # The repeated header is in index_text only, so text stays an exact slice.
    assert "| Key | Value |" not in chunks[1].text


def test_single_paragraph_above_max_with_no_breaks_is_cut_by_character(caplog):
    text = "x" * (CFG.max * 2 + 50)
    with caplog.at_level(logging.WARNING):
        chunks = check_invariants(text, CFG)
    assert len(chunks) > 1
    assert all(item.oversize and len(item.text) <= CFG.max for item in chunks)
    assert "splitting" in caplog.text


def test_long_paragraph_is_cut_at_sentence_ends_first():
    sentences = [f"Sentence number {i} says something short." for i in range(40)]
    chunks = check_invariants(" ".join(sentences), CFG)
    assert len(chunks) > 1
    assert all(item.oversize and item.text.endswith(".") for item in chunks)


def test_hash_lines_inside_a_code_block_are_not_headings():
    text = "# Real\n\n```\n# not a heading\n```\n"
    chunks = check_invariants(text, CFG)
    assert [item.heading_path for item in chunks] == [("Real",)]
    assert "# not a heading" in chunks[0].text


def test_heading_with_an_empty_section_is_still_covered():
    text = "# One\n\n## Empty\n\n## Full\n\nSome text.\n"
    chunks = check_invariants(text, CFG)
    assert [item.heading_path[-1] for item in chunks] == ["One", "Empty", "Full"]


def test_nested_list_item_stays_with_its_parent():
    text = "- parent\n  - child one\n  - child two\n- next\n"
    chunks = check_invariants(text, CFG)
    assert chunks[0].text == text.strip()


def test_small_chunk_is_not_merged_across_a_heading():
    text = "# One\n\n" + "a" * 90 + "\n\n# Two\n\nshort\n"
    chunks = check_invariants(text, CFG)
    assert [item.heading_path for item in chunks] == [("One",), ("Two",)]


def test_small_chunk_merges_with_previous_in_same_section():
    first = "a" * (CFG.target - 10)
    text = f"{first}\n\n{'b' * 40}\n"
    chunks = check_invariants(text, CFG)
    assert [item.text for item in chunks] == [text.strip()]


def test_small_chunk_is_left_alone_when_merging_would_pass_max():
    text = f"{'a' * (CFG.max - 5)}\n\nshort\n"
    chunks = check_invariants(text, CFG)
    assert [len(item.text) for item in chunks] == [CFG.max - 5, 5]


def test_heading_is_not_left_alone_before_a_long_paragraph():
    text = "## Notes\n\n" + "a" * (CFG.target - 5) + "\n"
    chunks = check_invariants(text, CFG)
    assert len(chunks) == 1


def test_crlf_offsets_point_at_the_original_text():
    text = (FRONT_MATTER + "# Title\n\nFirst.\n\nSecond.\n").replace("\n", "\r\n")
    chunks = check_invariants(text, CFG)
    assert "First." in chunks[0].text
    assert chunks[0].heading_path == ("Title",)


def test_cyrillic_text_is_handled():
    chunks = check_invariants("# Заголовок\n\nПервое предложение. Второе предложение.\n", CFG)
    assert chunks[0].heading_path == ("Заголовок",)


@pytest.mark.parametrize("underline", ["===", "---"])
def test_setext_headings_open_sections(underline):
    text = f"Title\n{underline}\n\nBody text.\n\nNext\n{underline}\n\nMore text.\n"
    chunks = check_invariants(text, CFG)
    assert [item.heading_path for item in chunks] == [("Title",), ("Next",)]


def test_text_markdown_it_drops_is_kept_between_blocks():
    text = "First.\n\n[ref]: https://example.com/a\n\nSecond.\n"
    chunks = check_invariants(text, CFG)
    assert "[ref]: https://example.com/a" in chunks[0].text


def test_text_markdown_it_drops_is_kept_at_the_end():
    text = "First.\n\n[ref]: https://example.com/a\n"
    chunks = check_invariants(text, CFG)
    assert chunks[-1].text.endswith("[ref]: https://example.com/a")


def test_index_text_carries_the_heading_path():
    long_paragraphs = "\n\n".join("word " * 90 for _ in range(3))
    text = f"# Product\n\n## Specs\n\n{long_paragraphs}\n"
    chunks = check_invariants(text, CFG)
    specs = [item for item in chunks if item.heading_path == ("Product", "Specs")]
    # The first chunk opens with its own heading, so only the parent is added.
    assert specs[0].index_text.startswith("Product\n\n## Specs")
    assert specs[1].index_text.startswith("Product > Specs\n\n")

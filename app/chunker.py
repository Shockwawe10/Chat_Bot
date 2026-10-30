"""Chunker v1 (baseline): splits one Markdown file into chunks for retrieval.

`chunk()` always works on the original file text, so every chunk can be traced
back to exact character offsets. Whole units (paragraph, list item, table row,
code block) are packed up to a soft target. Body text of two sections never mixes,
so a chunk only crosses a heading when that heading has no body of its own.
There is no overlap: `index_text` carries the heading path as context instead.
"""

import datetime
import hashlib
import logging
import os
import re
from dataclasses import dataclass, replace
from pathlib import Path, PurePath

import yaml
from dotenv import dotenv_values
from markdown_it import MarkdownIt

CHUNKER_VERSION = "v1"
ENV_FILE = Path(__file__).resolve().parents[1] / ".env"

logger = logging.getLogger(__name__)

# The same line endings markdown-it counts, so its line numbers match ours.
NEWLINE = re.compile(r"\r\n?|\n")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
MARKDOWN = MarkdownIt("commonmark").enable("table")


@dataclass(frozen=True)
class ChunkConfig:
    target: int = 500  # soft limit: stop adding units here
    max: int = 800  # hard limit: no chunk is longer
    min: int = 100  # shorter chunks merge with the previous one in the section

    def __post_init__(self):
        if not 0 < self.min <= self.target <= self.max:
            raise ValueError(f"need 0 < min <= target <= max, got {self}")

    @classmethod
    def from_env(cls, env=None):
        """Read CHUNK_SIZE, CHUNK_MAX and CHUNK_MIN. By default from .env, then the process."""
        if env is None:
            env = {**dotenv_values(ENV_FILE), **os.environ}
        defaults = cls()
        return cls(
            target=int(env.get("CHUNK_SIZE") or defaults.target),
            max=int(env.get("CHUNK_MAX") or defaults.max),
            min=int(env.get("CHUNK_MIN") or defaults.min),
        )


@dataclass(frozen=True)
class Chunk:
    id: str
    doc_id: str
    text: str  # exactly original[start:end]
    index_text: str  # what gets embedded: heading path + text
    start: int
    end: int
    heading_path: tuple[str, ...]
    chunk_index: int
    chunker_version: str
    oversize: bool  # a unit longer than cfg.max had to be cut to build this chunk


@dataclass(frozen=True)
class DocMeta:
    doc_id: str
    title: str | None
    last_reviewed: str | None  # a review date, not when the content was written
    url: str | None
    version: str | None


@dataclass(frozen=True)
class _Unit:
    """One piece that is never split, given as offsets into the original text."""

    start: int
    end: int
    heading: str | None = None  # the title, if this unit is a heading line
    table_header: tuple[int, int] | None = None  # for rows cut off from their header
    oversize: bool = False


@dataclass
class _Section:
    heading_path: tuple[str, ...]
    units: list[_Unit]


def _line_starts(text):
    return [0] + [match.end() for match in NEWLINE.finditer(text)]


def _trim(text, start, end):
    """Shrink (start, end) so it has no whitespace on either side."""
    piece = text[start:end]
    start += len(piece) - len(piece.lstrip())
    return start, start + len(piece.strip())


def _find_front_matter(text):
    """Return (mapping, body_start), or (None, 0) if there is no valid front matter."""
    starts = _line_starts(text)
    offset = 1 if text.startswith("﻿") else 0
    first_line_end = starts[1] if len(starts) > 1 else len(text)
    if text[offset:first_line_end].rstrip() != "---":
        return None, 0
    for line, line_start in enumerate(starts[1:], start=1):
        line_end = starts[line + 1] if line + 1 < len(starts) else len(text)
        if text[line_start:line_end].rstrip() == "---":
            try:
                mapping = yaml.safe_load(text[first_line_end:line_start])
            except (yaml.YAMLError, ValueError) as error:
                logger.warning("invalid front matter, treating it as body: %s", error)
                return None, 0
            if mapping is None:
                return {}, line_end
            if isinstance(mapping, dict):
                return mapping, line_end
            return None, 0
    logger.warning("front matter is not closed, treating it as body")
    return None, 0


def parse_document(text, filename):
    """Return (DocMeta, body_start). Front matter goes here and is never indexed."""
    front_matter, body_start = _find_front_matter(text)
    front_matter = front_matter or {}
    reviewed = front_matter.get("last_reviewed")
    if isinstance(reviewed, (datetime.date, datetime.datetime)):
        reviewed = reviewed.isoformat()
    doc_id = front_matter.get("id") or PurePath(filename).stem
    if reviewed is None:
        logger.warning("%s: no last_reviewed in front matter", doc_id)
    optional = (front_matter.get(key) for key in ("title", "url", "version"))
    title, url, version = (None if value is None else str(value) for value in optional)
    reviewed = None if reviewed is None else str(reviewed)
    return DocMeta(str(doc_id), title, reviewed, url, version), body_start


def _blocks(body):
    """Return top-level (first_line, end_line, token, heading_title). List items count as blocks."""
    blocks = []
    tokens = MARKDOWN.parse(body)
    for position, token in enumerate(tokens):
        if token.map is None or token.nesting == -1:
            continue
        is_list = token.type in ("bullet_list_open", "ordered_list_open")
        is_top_level = token.level == 0 and not is_list
        is_list_item = token.level == 1 and token.type == "list_item_open"
        if is_top_level or is_list_item:
            title = tokens[position + 1].content if token.type == "heading_open" else None
            blocks.append((token.map[0], token.map[1], token, title))
    return blocks


def _table_units(text, span, first, last, cfg):
    """A table within cfg.max stays whole; a longer one splits into rows."""
    start, end = _trim(text, *span(first, last))
    if end - start <= cfg.max or last - first <= 3:
        return [_Unit(start, end)]
    header = _trim(text, *span(first, first + 2))
    # The first row stays with the header and delimiter lines.
    units = [_Unit(*_trim(text, *span(first, first + 3)))]
    for line in range(first + 3, last):
        row = _trim(text, *span(line, line + 1))
        if row[0] < row[1]:
            units.append(_Unit(*row, table_header=header))
    return units


def _sentence_spans(text, unit):
    spans = []
    start = unit.start
    for match in SENTENCE_END.finditer(text, unit.start, unit.end):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, unit.end))
    return spans


def _split_oversize(text, unit, cfg):
    """Cut a unit longer than cfg.max: by sentence first, then by character."""
    logger.warning("unit at offset %d is longer than %d chars, splitting it", unit.start, cfg.max)
    pieces = []
    for start, end in _sentence_spans(text, unit):
        for cut in range(start, end, cfg.max):
            piece = _trim(text, cut, min(cut + cfg.max, end))
            if piece[0] < piece[1]:
                pieces.append(piece)
    # Sentences pack up to the target, so one long unit does not become one chunk per sentence.
    packed = []
    for start, end in pieces:
        if packed and end - packed[-1][0] <= cfg.target:
            packed[-1] = (packed[-1][0], end)
        else:
            packed.append((start, end))
    return [
        replace(unit, start=start, end=end, oversize=True, heading=unit.heading if i == 0 else None)
        for i, (start, end) in enumerate(packed)
    ]


def _read_sections(text, body_start, cfg):
    body = text[body_start:]
    starts = _line_starts(body)

    def span(first, last):
        end = starts[last] if last < len(starts) else len(body)
        return starts[first] + body_start, end + body_start

    sections = [_Section((), [])]
    open_headings = []
    cursor = 0

    def add(unit):
        if unit.start >= unit.end:
            return
        too_long = unit.end - unit.start > cfg.max
        sections[-1].units.extend(_split_oversize(text, unit, cfg) if too_long else [unit])

    for first, last, token, title in _blocks(body):
        # markdown-it drops some text, like link reference definitions. Keep it.
        if first > cursor:
            add(_Unit(*_trim(text, *span(cursor, first))))
        first = max(first, cursor)
        cursor = max(cursor, last)
        if first >= last:
            continue
        if token.type == "heading_open":
            level = int(token.tag[1])
            while open_headings and open_headings[-1][0] >= level:
                open_headings.pop()
            open_headings.append((level, " ".join(title.split())))
            sections.append(_Section(tuple(name for _, name in open_headings), []))
            add(_Unit(*_trim(text, *span(first, last)), heading=open_headings[-1][1]))
        elif token.type == "table_open":
            for unit in _table_units(text, span, first, last, cfg):
                add(unit)
        else:
            add(_Unit(*_trim(text, *span(first, last))))
    if cursor < len(starts):
        add(_Unit(*_trim(text, *span(cursor, len(starts)))))
    return sections


def _only_headings(units):
    return all(unit.heading is not None for unit in units)


def _merge_empty_headings(sections):
    """Move a heading with no body of its own forward, into the next section.

    It has no text to mix with that section, and alone it would be a tiny chunk
    that outranks real answers in BM25. A heading at the end of a file moves back.
    """
    merged = []
    waiting = []
    for section in sections:
        units = waiting + section.units
        if _only_headings(units):
            waiting = units
        else:
            merged.append(_Section(section.heading_path, units))
            waiting = []
    if waiting and merged:
        merged[-1].units.extend(waiting)
    elif waiting:
        merged.append(_Section(sections[-1].heading_path, waiting))
    return merged


def _size(units):
    return units[-1].end - units[0].start


def _pack(units, cfg):
    groups = []
    current = []
    for unit in units:
        if current:
            joined = unit.end - current[0].start
            # A short chunk or a bare heading may pass the target to stay with the next unit.
            can_stop = _size(current) >= cfg.min and not _only_headings(current)
            if joined > cfg.max or (joined > cfg.target and can_stop):
                groups.append(current)
                current = []
        current.append(unit)
    if current:
        groups.append(current)
    return groups


def _merge_small(groups, cfg):
    merged = []
    for group in groups:
        fits = merged and group[-1].end - merged[-1][0].start <= cfg.max
        if fits and (_size(group) < cfg.min or _only_headings(group)):
            merged[-1] = merged[-1] + group
        else:
            merged.append(group)
    return merged


def _index_text(text, heading_path, group, body):
    # A heading that is already in the chunk is not repeated in the prefix.
    own_headings = {unit.heading for unit in group}
    prefix = " > ".join(name for name in heading_path if name and name not in own_headings)
    if group[0].table_header:
        start, end = group[0].table_header
        body = f"{text[start:end]}\n{body}"
    return f"{prefix}\n\n{body}" if prefix else body


def chunk(text, doc_id, cfg):
    """Split one file into chunks. `text` is the whole original file, front matter included."""
    _, body_start = _find_front_matter(text)
    chunks = []
    for section in _merge_empty_headings(_read_sections(text, body_start, cfg)):
        for group in _merge_small(_pack(section.units, cfg), cfg):
            start, end = group[0].start, group[-1].end
            body = text[start:end]
            digest = hashlib.sha256(f"{CHUNKER_VERSION}\0{doc_id}\0{start}\0{body}".encode()).hexdigest()
            chunks.append(
                Chunk(
                    id=f"{doc_id}:{len(chunks)}:{digest[:12]}",
                    doc_id=doc_id,
                    text=body,
                    index_text=_index_text(text, section.heading_path, group, body),
                    start=start,
                    end=end,
                    heading_path=section.heading_path,
                    chunk_index=len(chunks),
                    chunker_version=CHUNKER_VERSION,
                    oversize=any(unit.oversize for unit in group),
                )
            )
    return chunks

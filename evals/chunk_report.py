"""Stage-level check for the chunker: gold-span coverage and chunk-length histogram.

Run from the repository root: python -m evals.chunk_report

Gold spans live in evals/gold_spans.jsonl, one per line:
{"doc_id": "warranty", "quote": "The company replies within 5 working days"}
Until that file exists, gold-span coverage is reported as not measured.
"""

import json
import logging
from pathlib import Path

from app.chunker import CHUNKER_VERSION, ChunkConfig, chunk, parse_document

ROOT = Path(__file__).resolve().parents[1]
KB_DIR = ROOT / "data" / "kb"
GOLD_SPANS = ROOT / "evals" / "gold_spans.jsonl"
BUCKET = 100


def load_corpus(kb_dir, cfg):
    """Return {doc_id: (original_text, chunks)} for every Markdown file in kb_dir."""
    corpus = {}
    for path in sorted(kb_dir.glob("*.md")):
        text = path.read_bytes().decode("utf-8")
        doc_id = parse_document(text, path.name)[0].doc_id
        corpus[doc_id] = (text, chunk(text, doc_id, cfg))
    return corpus


def span_in_one_chunk(text, chunks, quote):
    """True if some occurrence of quote sits fully inside a single chunk."""
    position = text.find(quote)
    if position == -1:
        raise ValueError(f"gold span not found in document: {quote!r}")
    while position != -1:
        end = position + len(quote)
        if any(item.start <= position and end <= item.end for item in chunks):
            return True
        position = text.find(quote, position + 1)
    return False


def gold_span_coverage(spans, corpus):
    """Return the share of gold spans fully contained in a single chunk."""
    if not spans:
        raise ValueError("no gold spans")
    hits = 0
    for span in spans:
        text, chunks = corpus[span["doc_id"]]
        hits += span_in_one_chunk(text, chunks, span["quote"])
    return hits / len(spans)


def length_histogram(chunks, bucket=BUCKET):
    """Return {bucket_start: count} of chunk lengths."""
    histogram = {}
    for item in chunks:
        start = len(item.text) // bucket * bucket
        histogram[start] = histogram.get(start, 0) + 1
    return dict(sorted(histogram.items()))


def main():
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    cfg = ChunkConfig.from_env()
    corpus = load_corpus(KB_DIR, cfg)
    chunks = [item for _, doc_chunks in corpus.values() for item in doc_chunks]
    print(f"config: target={cfg.target} max={cfg.max} min={cfg.min} chunker={CHUNKER_VERSION}")
    print(f"corpus data/kb: {len(corpus)} documents, {len(chunks)} chunks")
    print(f"oversize chunks: {sum(item.oversize for item in chunks)}")
    print("chunk length histogram:")
    for start, count in length_histogram(chunks).items():
        print(f"  {start:4d}-{start + BUCKET - 1:<4d} {count:4d} {'#' * count}")
    if GOLD_SPANS.exists():
        lines = GOLD_SPANS.read_text(encoding="utf-8").splitlines()
        spans = [json.loads(line) for line in lines if line.strip()]
        print(f"gold-span coverage: {gold_span_coverage(spans, corpus):.3f} ({len(spans)} spans)")
    else:
        print("gold-span coverage: not measured (evals/gold_spans.jsonl does not exist)")


if __name__ == "__main__":
    main()

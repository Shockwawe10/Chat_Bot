"""Answers "can the tests fail?": break the code one way at a time, run the unit tests.

Run from the repository root: python -m evals.mutation_check [--only TEXT]

Every break must make a test fail. A break that survives is a gap in the tests.
Hypothesis saves failing examples and replays them, so the saved examples are
deleted before each run; otherwise one break would make all the later ones look
caught. The unbroken code must pass first, for the same reason.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKER = ROOT / "app" / "chunker.py"
EMBEDDER = ROOT / "app" / "embedder.py"
INDEX = ROOT / "app" / "index.py"
SETTINGS = ROOT / "app" / "settings.py"

PACK = "if joined > cfg.max or (joined > cfg.target and can_stop):"
MERGE = "if fits and (_size(group) < cfg.min or _only_headings(group)):"
ENV = "return {**dotenv_values(ENV_FILE), **os.environ}"
FLAG = "oversize=True, heading="
EMBED_CALL = "vectors = embedder.embed_documents([item.index_text for item in corpus.chunks])\n"
UP_TO_DATE = "if is_active and exists and client.get_collection(name).count() == len(corpus.chunks):"
STORED = 'if entry["metadata"] != metadata_for(item, corpus) or entry["document"] != item.text:'
VERIFY_STEP = "verify(collection, corpus, embedder)\n    except IndexCheckError:"

# name: list of (file, text to find, replacement)
BREAKS = {
    # Chunker
    "drop text markdown-it skips (middle)": [(CHUNKER, "if first > cursor:", "if False:")],
    "drop text markdown-it skips (tail)": [(CHUNKER, "if cursor < len(starts):", "if False:")],
    "merge may pass max": [
        (CHUNKER, "fits = merged and group[-1].end - merged[-1][0].start <= cfg.max", "fits = merged")
    ],
    "never merge small chunks": [(CHUNKER, MERGE, "if False:")],
    "long trailing heading stays alone": [(CHUNKER, MERGE, "if fits and _size(group) < cfg.min:")],
    "always split tables by rows": [
        (CHUNKER, "if end - start <= cfg.max or last - first <= 3:", "if last - first <= 3:")
    ],
    "no hard max when packing": [(CHUNKER, PACK, "if joined > cfg.target and can_stop:")],
    "stop at target whatever the size": [(CHUNKER, PACK, "if joined > cfg.target:")],
    "no repeated table header": [(CHUNKER, "if group[0].table_header:", "if False:")],
    "body text mixes across headings": [
        (
            CHUNKER,
            "sections.append(_Section(tuple(name for _, name in open_headings), []))",
            "sections[-1].heading_path = tuple(name for _, name in open_headings)",
        )
    ],
    "cut inside units, not flagged": [
        (CHUNKER, "too_long = unit.end - unit.start > cfg.max", "too_long = unit.end - unit.start > cfg.target"),
        (CHUNKER, FLAG, "oversize=False, heading="),
    ],
    "split long units without flag": [(CHUNKER, FLAG, "oversize=False, heading=")],
    "front matter indexed": [(CHUNKER, "_, body_start = _find_front_matter(text)", "body_start = 0")],
    "no sentence split": [
        (CHUNKER, "for match in SENTENCE_END.finditer(text, unit.start, unit.end):", "for match in ():")
    ],
    "heading path not in index_text": [
        (CHUNKER, 'return f"{prefix}\\n\\n{body}" if prefix else body', "return body")
    ],
    "unstable ids": [
        (CHUNKER, "{doc_id}:{len(chunks)}:{digest[:12]}", "{doc_id}:{len(chunks)}:{id(text)}{id(group)}")
    ],
    "bare heading stops at target": [
        (
            CHUNKER,
            "can_stop = _size(current) >= cfg.min and not _only_headings(current)",
            "can_stop = _size(current) >= cfg.min",
        )
    ],
    "bare headings not merged": [
        (
            CHUNKER,
            "for section in _merge_empty_headings(_read_sections(text, body_start, cfg)):",
            "for section in _read_sections(text, body_start, cfg):",
        )
    ],
    "last heading not moved back": [
        (
            CHUNKER,
            "    if waiting and merged:\n        merged[-1].units.extend(waiting)\n    elif waiting:",
            "    if waiting:",
        )
    ],
    "only-heading file dropped": [
        (CHUNKER, "    elif waiting:\n        merged.append(_Section(sections[-1].heading_path, waiting))\n", "")
    ],
    "merged headings repeated in prefix": [
        (CHUNKER, "own_headings = {unit.heading for unit in group}", "own_headings = {group[0].heading}")
    ],
    "config ignores CHUNK_MAX": [
        (CHUNKER, 'max=int(env.get("CHUNK_MAX") or defaults.max)', "max=defaults.max")
    ],
    "config ignores CHUNK_MIN": [
        (CHUNKER, 'min=int(env.get("CHUNK_MIN") or defaults.min)', "min=defaults.min")
    ],
    "config ignores CHUNK_SIZE": [
        (CHUNKER, 'target=int(env.get("CHUNK_SIZE") or defaults.target)', "target=defaults.target")
    ],
    "config ignores .env file": [(SETTINGS, ENV, "return dict(os.environ)")],
    ".env beats the process": [(SETTINGS, ENV, "return {**os.environ, **dotenv_values(ENV_FILE)}")],
    # Embedder
    "drop prefix": [(EMBEDDER, "    return prefix + text", "    return text")],
    "prefix added twice": [(EMBEDDER, "    return prefix + text", "    return prefix + prefix + text")],
    "existing prefix not removed": [(EMBEDDER, "    while text.startswith(prefix):", "    while False:")],
    "queries use the document prefix": [
        (EMBEDDER, "_with_prefix(QUERY_PREFIX, text)", "_with_prefix(DOCUMENT_PREFIX, text)")
    ],
    "truncation on": [(EMBEDDER, '"truncate": False', '"truncate": True')],
    "digest not compared": [(EMBEDDER, "if installed[self.model] != self.digest:", "if False:")],
    "model missing not noticed": [(EMBEDDER, "if self.model not in installed:", "if False:")],
    "latest tag allowed": [(EMBEDDER, 'if not tag or tag == "latest":', "if not tag:")],
    "context length not checked": [
        (EMBEDDER, "if len(text) + SPECIAL_TOKENS > self._context_length:", "if False:")
    ],
    "dimension not asserted": [(EMBEDDER, "if len(vector) != dim:", "if False:")],
    "finite not checked": [(EMBEDDER, "if not all(math.isfinite(value) for value in vector):", "if False:")],
    "zero norm not checked": [(EMBEDDER, "if not any(vector):", "if False:")],
    "short backend answer accepted": [(EMBEDDER, "if len(result) != len(batch):", "if False:")],
    # Index
    "swap two vectors": [(INDEX, EMBED_CALL, EMBED_CALL + "    vectors[0], vectors[1] = vectors[1], vectors[0]\n")],
    "L2 metric": [(INDEX, '{"hnsw": {"space": "cosine"}}', '{"hnsw": {"space": "l2"}}')],
    "skip a batch": [
        (INDEX, "for start in range(0, len(corpus.chunks), ADD_BATCH):", "for start in range(ADD_BATCH, len(corpus.chunks), ADD_BATCH):")
    ],
    "stale manifest": [
        (INDEX, "    _write_manifest(\n        index_dir,\n", "    manifest is None and _write_manifest(\n        index_dir,\n")
    ],
    "manifest switched before verify": [
        (
            INDEX,
            VERIFY_STEP,
            '_write_manifest(index_dir, {"active_collection": name, "fingerprint": full_fingerprint})\n'
            "        " + VERIFY_STEP,
        )
    ],
    "partial collection kept after an error": [
        (INDEX, "        if not exists:\n            _delete_if_present(client, name)\n        raise", "        raise")
    ],
    "collection that failed verification kept": [
        (INDEX, "    except IndexCheckError:\n        _delete_if_present(client, name)\n        raise\n", "")
    ],
    "kept collection deleted on an outside error": [
        (INDEX, "        if not exists:\n            _delete_if_present(client, name)\n        raise", "        _delete_if_present(client, name)\n        raise")
    ],
    "second run rebuilds": [(INDEX, UP_TO_DATE, "if False:")],
    "up to date ignores a missing collection": [(INDEX, UP_TO_DATE, "if is_active:")],
    "old collection not reused": [
        (INDEX, "        if exists:\n            collection = client.get_collection", "        if False:\n            collection = client.get_collection")
    ],
    "pin not checked in build": [(INDEX, "    backend.check_pinned()\n", "")],
    "embed text, not index_text": [
        (INDEX, "embedder.embed_documents([item.index_text for", "embedder.embed_documents([item.text for")
    ],
    "store index_text as the document": [
        (INDEX, "documents=[item.text for item in batch]", "documents=[item.index_text for item in batch]")
    ],
    "null review date stored": [
        (
            INDEX,
            '    if reviewed is not None:\n        metadata["last_reviewed"] = reviewed\n',
            '    metadata["last_reviewed"] = reviewed or ""\n',
        )
    ],
    "completeness check off": [(INDEX, "    check_completeness(collection, corpus, stored)\n", "")],
    "integrity check off": [(INDEX, "    check_integrity(corpus, stored, embedder.dim)\n", "")],
    "alignment check off": [(INDEX, "    check_alignment(corpus, found)\n", "")],
    "exactness check off": [(INDEX, "    check_exactness(collection, corpus, stored, queries, found)\n", "")],
    "integrity ignores vectors": [
        (INDEX, 'check_vector([float(value) for value in entry["vector"]], dim)', "pass")
    ],
    "integrity ignores metadata": [(INDEX, STORED, 'if entry["document"] != item.text:')],
    "integrity ignores the document": [
        (INDEX, STORED, 'if entry["metadata"] != metadata_for(item, corpus):')
    ],
    "metric setting not read": [(INDEX, 'if space != "cosine":', "if False:")],
    "top-k order not compared": [
        (INDEX, 'if found["ids"][row] != [ids[position] for position in ranked[row]]:', "if False:")
    ],
    "distances not compared": [
        (INDEX, 'if not np.allclose(found["distances"][row], expected, atol=DISTANCE_TOLERANCE):', "if False:")
    ],
    "fingerprint ignores the corpus": [(INDEX, '        "corpus": corpus.file_hashes,\n', "")],
    "fingerprint ignores the chunker version": [(INDEX, '        "chunker_version": CHUNKER_VERSION,\n', "")],
    "fingerprint ignores the chunk config": [(INDEX, '        "chunk_config": asdict(cfg),\n', "")],
    "fingerprint ignores the model": [(INDEX, '        "embedding_model": backend.model,\n', "")],
    "fingerprint ignores the digest": [(INDEX, '        "embedding_digest": backend.digest,\n', "")],
    "fingerprint ignores the prefix": [(INDEX, '        "document_prefix": DOCUMENT_PREFIX,\n', "")],
    "prune removes the active collection": [
        (INDEX, ' and name != manifest["active_collection"]', "")
    ],
    "prune removes collections it does not own": [
        (INDEX, 'if name.startswith(COLLECTION_PREFIX) and name != ', "if name != ")
    ],
}


def run_tests():
    shutil.rmtree(ROOT / ".hypothesis", ignore_errors=True)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit", "-q", "-x", "-p", "no:cacheprovider"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def failed_test(result):
    for line in result.stdout.splitlines():
        if line.startswith(("FAILED", "ERROR")):
            return line.split(" - ")[0].split("::")[-1]
    return "tests did not start"


def read_sources(originals):
    return {path: data.decode("utf-8").replace("\r\n", "\n") for path, data in originals.items()}


def check_breaks_apply(selected, originals):
    """Stop before anything runs if a break no longer matches the code."""
    sources = read_sources(originals)
    for name, edits in selected.items():
        for path, old, _ in edits:
            if old not in sources[path]:
                sys.exit(f"break {name!r} no longer matches {path.name}: {old}")


def apply_break(edits, originals):
    """Write the broken files. Edits to one file apply together."""
    sources = read_sources(originals)
    for path, old, new in edits:
        sources[path] = sources[path].replace(old, new)
    for path in {path for path, _, _ in edits}:
        path.write_bytes(sources[path].encode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Check that the unit tests catch deliberate breaks.")
    parser.add_argument("--only", default="", help="run only breaks whose name contains this text")
    args = parser.parse_args()
    selected = {name: edits for name, edits in BREAKS.items() if args.only in name}
    originals = {path: path.read_bytes() for path in (CHUNKER, EMBEDDER, INDEX, SETTINGS)}
    check_breaks_apply(selected, originals)

    baseline = run_tests()
    if baseline.returncode != 0:
        sys.exit("the unbroken code fails, so the results would mean nothing:\n" + baseline.stdout[-1500:])
    print("baseline passes", flush=True)

    survived = []
    try:
        for name, edits in selected.items():
            apply_break(edits, originals)
            result = run_tests()
            for path, original in originals.items():
                path.write_bytes(original)
            caught = result.returncode != 0
            print(f"{'caught  ' if caught else 'SURVIVED'} {name}  {failed_test(result) if caught else ''}", flush=True)
            if not caught:
                survived.append(name)
    finally:
        for path, original in originals.items():
            path.write_bytes(original)
    print(f"total {len(selected)}, caught {len(selected) - len(survived)}, survived: {survived or 'none'}")
    sys.exit(1 if survived else 0)


if __name__ == "__main__":
    main()

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
RETRIEVER = ROOT / "app" / "retriever.py"
GENERATOR = ROOT / "app" / "generator.py"
API = ROOT / "app" / "api.py"

PACK = "if joined > cfg.max or (joined > cfg.target and can_stop):"
MERGE = "if fits and (_size(group) < cfg.min or _only_headings(group)):"
ENV = "return {**dotenv_values(ENV_FILE), **os.environ}"
FLAG = "oversize=True, heading="
EMBED_CALL = "vectors = embedder.embed_documents([item.index_text for item in corpus.chunks])\n"
UP_TO_DATE = "if is_active and exists and client.get_collection(name).count() == len(corpus.chunks):"
STORED = 'if entry["metadata"] != metadata_for(item, corpus) or entry["document"] != item.text:'
VERIFY_STEP = "verify(collection, corpus, embedder)\n    except IndexCheckError:"
RANGE = "if type(number) is not int or not 1 <= number <= passage_count:"
TRUNCATED = "if count is None or count < len(prompt.split()) or count >= num_ctx:"
ATTEMPTS = "attempts = [(cfg.temperature, cfg.seed), (RETRY_TEMPERATURE, cfg.seed + 1)]"
NUMBER_TO_ID = "hits[number - 1].chunk_id for number in result.citations"
OFF_BY_ONE = "hits[min(number, len(hits) - 1)].chunk_id for number in result.citations"

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
    "digest not compared": [(EMBEDDER, "if installed[model] != digest:", "if False:")],
    "model missing not noticed": [(EMBEDDER, "if model not in installed:", "if False:")],
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
    # Retrieval
    "wrong query prefix": [
        (RETRIEVER, "return self.embedder.embed_query(question)", "return self.embedder.embed_documents([question])[0]")
    ],
    "guard disabled": [(RETRIEVER, "        check_guard(manifest, backend)\n", "")],
    "guard ignores the model": [(RETRIEVER, '        "embedding_model": backend.model,\n', "")],
    "guard ignores the digest": [(RETRIEVER, '        "embedding_digest": backend.digest,\n', "")],
    "guard ignores the prefix": [(RETRIEVER, '        "document_prefix": DOCUMENT_PREFIX,\n', "")],
    "installed model not checked": [(RETRIEVER, "            backend.check_pinned()\n", "            pass\n")],
    "score is the distance": [(RETRIEVER, "score=1 - distance", "score=distance")],
    "ranks start at zero": [(RETRIEVER, "start=1,", "start=0,")],
    "k ignored": [
        (RETRIEVER, "n_results=min(self.top_k, self.collection.count())", "n_results=self.collection.count()")
    ],
    # Generation
    "no output schema": [(GENERATOR, '            "format": OUTPUT_SCHEMA,\n', "")],
    "thinking on": [(GENERATOR, '"think": False', '"think": True')],
    "num_ctx not sent": [(GENERATOR, '                "num_ctx": self.cfg.num_ctx,\n', "")],
    "num_predict not sent": [(GENERATOR, '                "num_predict": self.cfg.num_predict,\n', "")],
    "seed not sent": [(GENERATOR, '                "seed": seed,\n', "")],
    "temperature not sent": [(GENERATOR, '                "temperature": temperature,\n', "")],
    "no retry": [(GENERATOR, ATTEMPTS, "attempts = [(cfg.temperature, cfg.seed)]")],
    "retry repeats the same call": [
        (GENERATOR, ATTEMPTS, "attempts = [(cfg.temperature, cfg.seed), (cfg.temperature, cfg.seed)]")
    ],
    "retry not flagged": [(GENERATOR, "        if attempt:\n", "        if False:\n")],
    "truncation not flagged": [
        (GENERATOR, "flags = parsed.flags + prompt_flags(completion, prompt, cfg.num_ctx)", "flags = parsed.flags")
    ],
    "truncation ignores the prompt length": [
        (GENERATOR, TRUNCATED, "if count is None or count >= num_ctx:")
    ],
    "truncation ignores num_ctx": [
        (GENERATOR, TRUNCATED, "if count is None or count < len(prompt.split()):")
    ],
    "abstained keeps the model's answer": [
        (GENERATOR, "return Answer(ABSTAIN_SENTENCE, True, [], flags)", "return Answer(answer, True, [], flags)")
    ],
    "abstained keeps citations": [
        (GENERATOR, "return Answer(ABSTAIN_SENTENCE, True, [], flags)", "return Answer(ABSTAIN_SENTENCE, True, numbers, flags)")
    ],
    "abstained with citations not flagged": [(GENERATOR, "        if numbers:\n", "        if False:\n")],
    "no upper citation limit": [
        (GENERATOR, RANGE, "if type(number) is not int or not 1 <= number:")
    ],
    "citation zero allowed": [
        (GENERATOR, RANGE, "if type(number) is not int or not 0 <= number <= passage_count:")
    ],
    "bad citation type allowed": [
        (GENERATOR, RANGE, "if not isinstance(number, int) or not 1 <= number <= passage_count:")
    ],
    "duplicate citations kept": [(GENERATOR, "elif number in citations:", "elif False:")],
    "missing citations not flagged": [(GENERATOR, "    if not citations:\n", "    if False:\n")],
    "empty answer accepted": [(GENERATOR, "    if not answer.strip():\n", "    if False:\n")],
    "field types not checked": [
        (
            GENERATOR,
            "if not isinstance(answer, str) or not isinstance(numbers, list) or not isinstance(abstained, bool):",
            "if False:",
        )
    ],
    "passages not numbered": [
        (GENERATOR, 'f"[{hit.rank}] {hit.heading_path}\\n{hit.text}"', 'f"{hit.heading_path}\\n{hit.text}"')
    ],
    "heading path left out of the prompt": [
        (GENERATOR, 'f"[{hit.rank}] {hit.heading_path}\\n{hit.text}"', 'f"[{hit.rank}]\\n{hit.text}"')
    ],
    "latest LLM tag allowed": [
        (GENERATOR, 'if ":" not in self.model or self.model.endswith(":latest"):', 'if ":" not in self.model:')
    ],
    "LLM digest not required": [(GENERATOR, "        if not self.digest:\n", "        if False:\n")],
    "answer budget not checked": [(GENERATOR, "if self.num_predict >= self.num_ctx:", "if False:")],
    "config ignores TEMPERATURE": [
        (GENERATOR, 'temperature=float(env.get("TEMPERATURE") or defaults["temperature"])', 'temperature=defaults["temperature"]')
    ],
    "config ignores LLM_SEED": [
        (GENERATOR, 'seed=int(env.get("LLM_SEED") or defaults["seed"])', 'seed=defaults["seed"]')
    ],
    "config ignores LLM_NUM_CTX": [
        (GENERATOR, 'num_ctx=int(env.get("LLM_NUM_CTX") or defaults["num_ctx"])', 'num_ctx=defaults["num_ctx"]')
    ],
    "config ignores LLM_NUM_PREDICT": [
        (GENERATOR, 'num_predict=int(env.get("LLM_NUM_PREDICT") or defaults["num_predict"])', 'num_predict=defaults["num_predict"]')
    ],
    # API
    "citation off by one": [(API, "citations=[" + NUMBER_TO_ID + "]", "citations=[" + OFF_BY_ONE + "]")],
    "cited mark off by one": [(API, "cited = {" + NUMBER_TO_ID + "}", "cited = {" + OFF_BY_ONE + "}")],
    "retrieved shown as cited": [(API, "cited=hit.chunk_id in cited", "cited=True")],
    "guard mismatch does not stop startup": [
        (API, "        except GuardError:\n            raise  # refuse to start on an index built with another model\n", "")
    ],
    "LLM pin not checked": [(API, "            llm.check_pinned()\n", "")],
    "no length limit": [(API, "max_length=MAX_QUESTION_CHARS", "max_length=100000")],
    "empty question allowed": [(API, "min_length=1", "min_length=0")],
    "spaces not stripped": [(API, "strip_whitespace=True", "strip_whitespace=False")],
    "bad output is not a 502": [(API, "raise HTTPException(502,", "raise HTTPException(503,")],
    "unavailable is not a 503": [(API, "raise HTTPException(503,", "raise HTTPException(500,")],
    "Ollama connection errors not handled": [(API, "    httpx.HTTPError,\n", "")],
    "LLM errors not handled": [(API, "    LlmUnavailable,\n", "")],
    "answered request not traced": [
        (API, "        traces.write(\n            {\n                **record,", "        print(\n            {\n                **record,")
    ],
    "invalid request not traced": [
        (API, '        traces.write({"status": 422, "errors": json.loads(json.dumps(error.errors(), default=str))})\n', "")
    ],
    "unparseable output not traced": [
        (API, '            traces.write({**record, "status": 502, "raw_outputs": error.raw_outputs})\n', "")
    ],
    "unavailable service not traced": [
        (API, '            traces.write({**record, "status": 503, "error": str(error)})\n', "")
    ],
    "trace escapes non-ASCII text": [(API, "ensure_ascii=False", "ensure_ascii=True")],
    "wrong index version reported": [(API, "index_fingerprint=retriever.fingerprint", 'index_fingerprint=""')],
    "wrong prompt version reported": [(API, "prompt=prompt.version,", 'prompt="",')],
    "wrong LLM digest reported": [(API, "llm_digest=llm.cfg.digest", 'llm_digest=""')],
    "config ignores TOP_K": [(API, 'top_k = int(env.get("TOP_K") or DEFAULT_TOP_K)', "top_k = DEFAULT_TOP_K")],
    "config ignores PROMPT_VERSION": [
        (API, 'PromptTemplate.load(env.get("PROMPT_VERSION") or "v1")', 'PromptTemplate.load("v1")')
    ],
}


def run_tests():
    shutil.rmtree(ROOT / ".hypothesis", ignore_errors=True)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit", "tests/api", "-q", "-x", "-p", "no:cacheprovider"],
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
    files = (CHUNKER, EMBEDDER, INDEX, SETTINGS, RETRIEVER, GENERATOR, API)
    originals = {path: path.read_bytes() for path in files}
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

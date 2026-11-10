"""Answers "can the tests fail?": break the code one way at a time, run the unit tests.

Run from the repository root: python -m evals.mutation_check [--only TEXT]

Every break must make a test fail. A break that survives is a gap in the tests.
Hypothesis saves failing examples and replays them, so the saved examples are
deleted before each run; otherwise one break would make all the later ones look
caught. The unbroken code must pass first, for the same reason.

The breaks are made in a temporary copy of the project, never in the real files.
Breaking the real files once put a broken app/embedder.py into a commit made while
the check was running.
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKER = ROOT / "app" / "chunker.py"
EMBEDDER = ROOT / "app" / "embedder.py"
INDEX = ROOT / "app" / "index.py"
SETTINGS = ROOT / "app" / "settings.py"
RETRIEVER = ROOT / "app" / "retriever.py"
GENERATOR = ROOT / "app" / "generator.py"
API = ROOT / "app" / "api.py"
CHECKER = ROOT / "app" / "checker.py"
KEYWORD = ROOT / "app" / "keyword.py"
QUESTIONS = ROOT / "app" / "questions.py"
LANGUAGE = ROOT / "app" / "language.py"
GATES = ROOT / "evals" / "gates.py"
FRESHNESS = ROOT / "evals" / "freshness.py"
GUARDS = ROOT / "app" / "guards.py"
ATTACK_RUN = ROOT / "evals" / "attack_run.py"
SCORING = ROOT / "evals" / "scoring.py"
VALIDATOR = ROOT / "evals" / "validate_golden.py"
METRICS = ROOT / "evals" / "metrics.py"
SYSTEMS_FILE = ROOT / "evals" / "systems.py"
RUN_EVALS = ROOT / "evals" / "run_evals.py"
RENDER = ROOT / "evals" / "render_results.py"
JUDGE = ROOT / "evals" / "judge.py"
CALIBRATE = ROOT / "evals" / "calibrate_judge.py"
CHART = ROOT / "evals" / "history_chart.py"
HOLDOUT = ROOT / "evals" / "holdout.py"
PHOENIX = ROOT / "evals" / "phoenix_export.py"
PROMPT_V5 = ROOT / "prompts" / "answer_v5.txt"
DB_FILE = ROOT / "mcp_server" / "db.py"
SEED = ROOT / "mcp_server" / "seed.py"
TOOLS = ROOT / "mcp_server" / "tools.py"
MCP_SERVER = ROOT / "mcp_server" / "server.py"
AGENT = ROOT / "app" / "agent.py"
AGENT_EVAL = ROOT / "evals" / "agent_eval.py"
AGENT_GATES = ROOT / "evals" / "agent_gates.py"

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
    "abstention shows the reason to the customer": [
        (GENERATOR, 'return Answer(ABSTAIN_SENTENCE, True, [], reason=data["reason"].strip())', 'return Answer(data["reason"], True, [], reason=data["reason"].strip())')
    ],
    "abstention loses the reason": [
        (GENERATOR, 'return Answer(ABSTAIN_SENTENCE, True, [], reason=data["reason"].strip())', "return Answer(ABSTAIN_SENTENCE, True, [])")
    ],
    "reason not stripped": [(GENERATOR, 'reason=data["reason"].strip())', 'reason=data["reason"])')],
    "abstention takes extra fields": [
        (GENERATOR, 'if set(data) != set(ABSTAIN_FORM["properties"]):', "if False:")
    ],
    "answer takes extra fields": [(GENERATOR, 'if set(data) != set(ANSWER_FORM["properties"]):', "if False:")],
    "empty reason accepted": [(GENERATOR, '        if not _has_text(data["reason"]):\n', "        if False:\n")],
    "unknown status accepted": [(GENERATOR, '    if status != "answer":\n', "    if False:\n")],
    "old format not flagged": [
        (GENERATOR, 'return Answer(ABSTAIN_SENTENCE, True, [], ["abstained_with_answer"])', "return Answer(ABSTAIN_SENTENCE, True, [])")
    ],
    "old format keeps the answer": [
        (GENERATOR, 'return Answer(ABSTAIN_SENTENCE, True, [], ["abstained_with_answer"])', 'return Answer(data["answer"], True, [], ["abstained_with_answer"])')
    ],
    "old format keeps citations": [
        (GENERATOR, 'return Answer(ABSTAIN_SENTENCE, True, [], ["abstained_with_answer"])', 'return Answer(ABSTAIN_SENTENCE, True, data["citations"], ["abstained_with_answer"])')
    ],
    "old format check ignores the answer": [
        (GENERATOR, 'if data.get("abstained") is True and _has_text(data.get("answer")):', 'if data.get("abstained") is True:')
    ],
    "old format check ignores abstained": [
        (GENERATOR, 'if data.get("abstained") is True and _has_text(data.get("answer")):', 'if "abstained" in data and _has_text(data.get("answer")):')
    ],
    "old format check removed": [
        (GENERATOR, 'if data.get("abstained") is True and _has_text(data.get("answer")):', "if False:")
    ],
    "schema allows either form to be both": [(GENERATOR, 'OUTPUT_SCHEMA = {"oneOf": [ANSWER_FORM, ABSTAIN_FORM]}', "OUTPUT_SCHEMA = ANSWER_FORM")],
    "schema allows empty citations": [(GENERATOR, ', "minItems": 1', "")],
    "schema allows endless citations": [(GENERATOR, ', "maxItems": 10', "")],
    "schema allows extra fields": [(GENERATOR, '    "additionalProperties": False,\n', "")],
    "schema allows an empty answer": [
        (GENERATOR, '"answer": {"type": "string", "minLength": 1}', '"answer": {"type": "string"}')
    ],
    "schema allows an empty reason": [
        (GENERATOR, '"reason": {"type": "string", "minLength": 1}', '"reason": {"type": "string"}')
    ],
    "status not required": [
        (GENERATOR, '"required": ["status", "answer", "citations"]', '"required": ["answer", "citations"]')
    ],
    "reason not required": [(GENERATOR, '"required": ["status", "reason"]', '"required": ["status"]')],
    "abstain form says answer": [(GENERATOR, '"status": {"const": "abstain"}', '"status": {"const": "answer"}')],
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
    "empty answer accepted": [(GENERATOR, "    if not _has_text(answer):\n", "    if False:\n")],
    "whitespace counts as text": [(GENERATOR, "bool(value.strip())", "bool(value)")],
    "text type not checked": [(GENERATOR, "return isinstance(value, str) and bool(value.strip())", 'return bool(str(value or "").strip())')],
    "empty citations accepted": [
        (GENERATOR, "if not isinstance(numbers, list) or not numbers:", "if not isinstance(numbers, list):")
    ],
    "citation type not checked": [
        (GENERATOR, "if not isinstance(numbers, list) or not numbers:", "if not numbers:")
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
    "reason not traced": [(API, '                    "reason": result.reason,\n', "")],
    "raw outputs not traced": [(API, '                "raw_outputs": result.raw_outputs,\n', "")],
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
        (API, 'PromptTemplate.load(env.get("PROMPT_VERSION") or "v2")', 'PromptTemplate.load("v2")')
    ],
    # Scoring
    "scoring: no boundary before a value": [(SCORING, 'before = r"(?<![a-z0-9.,])" if', 'before = "" if')],
    "scoring: no boundary after a value": [(SCORING, 'after = r"(?![a-z0-9])" if', 'after = "" if')],
    "scoring: thousands separators kept": [(SCORING, '    text = THOUSANDS.sub("", text)\n', "")],
    "scoring: range forms not unified": [(SCORING, '    text = RANGE.sub(" to ", text)\n', "")],
    "scoring: space after a number required": [(SCORING, r'body = r"\s?".join(', 'body = " ".join(')],
    "scoring: number glued to the next word": [(SCORING, r'body = r"\s?".join(', 'body = "".join(')],
    "scoring: range unit not copied": [(SCORING, r'return BARE_RANGE.sub(r"\1 \3 to \2 \3", text)', "return text")],
    "scoring: degrees word kept": [(SCORING, '    text = DEGREES.sub("°", text)\n', "")],
    "scoring: m2 not read as square metres": [(SCORING, '    text = SQUARE.sub("²", text)\n', "")],
    "scoring: Greek mu kept": [(SCORING, "    text = text.replace(GREEK_MU, MICRO_SIGN)", "    text = text")],
    "scoring: case kept": [(SCORING, "SPACES.sub(\" \", text.lower())", "SPACES.sub(\" \", text)")],
    # Eval harness
    "harness: gold matched in any document": [
        (METRICS, 'if any(span["doc_id"] == doc_id and span["quote"] in text for span in group):', 'if any(span["quote"] in text for span in group):')
    ],
    "harness: CRLF chunk text not normalised": [(METRICS, 'return store.text(chunk_id).replace("\\r\\n", "\\n")', "return store.text(chunk_id)")],
    "harness: hit rate counts any group": [(METRICS, 'scored["hit"] = ranks[0] is not None', 'scored["hit"] = any(rank is not None for rank in ranks)')],
    "harness: reciprocal rank off by one": [(METRICS, 'scored["reciprocal_rank"] = 1 / ranks[0] if ranks[0] else 0.0', 'scored["reciprocal_rank"] = 1 / (ranks[0] + 1) if ranks[0] else 0.0')],
    "harness: undecided counted as a pass": [(METRICS, "        behaviour_ok = None  # only the judge can tell\n", "        behaviour_ok = True\n")],
    "harness: refusal passes a language case": [(METRICS, "        behaviour_ok = english\n", "        behaviour_ok = english or refused\n")],
    "harness: missing facts ignored": [(METRICS, "    elif not ok or refused or missing:\n", "    elif not ok or refused:\n")],
    "harness: server error ignored": [(METRICS, "    elif not ok or refused or missing:\n", "    elif refused or missing:\n")],
    "harness: refusal accuracy ignores over-refusal": [(METRICS, 'else ok and not refused,', "else True,")],
    "harness: distractor never found": [(METRICS, 'scored["distractor_in_context"] = any(', 'scored["distractor_in_context"] = False and any(')],
    "harness: p95 is the maximum": [(METRICS, "return values[min(len(values) - 1, math.ceil(0.95 * len(values)) - 1)]", "return values[-1]")],
    "harness: random retriever not seeded": [(SYSTEMS_FILE, "self.random = random.Random(seed)", "self.random = random.Random()")],
    "harness: always-abstain answers": [(SYSTEMS_FILE, '"answer": ABSTAIN_SENTENCE, "abstained": True,', '"answer": ABSTAIN_SENTENCE, "abstained": False,')],
    "harness: drafts are run": [(RUN_EVALS, 'reviewed = [c for c in chosen if c["reviewed_by"] is not None]', "reviewed = chosen")],
    "harness: smoke run updates latest": [(RUN_EVALS, 'full_dev = report["system"] == "pipeline" and report["split"] == "dev" and not report["smoke"]', 'full_dev = report["system"] == "pipeline" and report["split"] == "dev"')],
    "harness: history appended under an old header": [(RUN_EVALS, "    if header == HISTORY_FIELDS:\n", "    if header is not None:\n")],
    "harness: missing run file guessed": [
        (RUN_EVALS, "        if not run_file.exists():\n            raise SystemExit", "        if False:\n            raise SystemExit")
    ],
    "render: labeller hidden": [(RENDER, "{'undefined' if kappa is None else f'{kappa:.2f}'}{who}", "{'undefined' if kappa is None else f'{kappa:.2f}'}")],
    "harness: any run can be the baseline": [(RUN_EVALS, "        if not full_dev:\n            raise SystemExit", "        if False:\n            raise SystemExit")],
    "harness: holdout without a flag": [(RUN_EVALS, 'if args.split == "holdout" and not args.allow_holdout:', "if False:")],
    "render: baseline shown as current": [
        (RENDER, "cells[2] = fill(current, calibration) if current else DASH", "cells[2] = fill(baseline, calibration) if baseline else DASH")
    ],
    "render: k not shown": [(RENDER, "f\"{value} (k={report['top_k']})\"", "value")],
    "render: dependent judge score shown": [(RENDER, '        if judged and key == "faithfulness" and not independent(report):\n', "        if False:\n")],
    "render: unmeasured shown as zero": [
        (
            RENDER,
            "        if value is None or (judged and not trusted(report, calibration, key)):\n            return DASH\n",
            "        if judged and not trusted(report, calibration, key):\n            return DASH\n        value = value or 0\n",
        )
    ],
    # Claim-check judge
    "judge: abbreviation ends a sentence": [(CHECKER, "        if not current.lower().endswith(ABBREVIATIONS):\n", "        if True:\n")],
    "judge: no output schema for the judge": [(JUDGE, '            "format": CLAIM_SCHEMA,\n', "")],
    "judge: judge not at temperature 0": [(JUDGE, '"options": {"temperature": 0, "seed": self.seed,', '"options": {"temperature": 0.8, "seed": self.seed,')],
    "judge: question left out of the check": [(JUDGE, "passages=\"\\n\\n\".join(contexts), question=question,", "passages=\"\\n\\n\".join(contexts), question=\"\",")],
    "judge: non-boolean verdict accepted": [(JUDGE, '        if not isinstance(verdict.get("supported"), bool):\n', "        if False:\n")],
    "judge: score counts unsupported sentences": [(JUDGE, 'return sum(v["supported"] for v in self.last_verdicts)', 'return sum(not v["supported"] for v in self.last_verdicts)')],
    "judge: context without the heading": [(SYSTEMS_FILE, 'return f"{entry[2]}\\n{text}" if len(entry) > 2 and entry[2] else text', "return text")],
    "judge: method not checked": [(JUDGE, "    if method not in METHODS:\n", "    if False:\n")],
    "render: calibration counts for any metric": [(RENDER, '        and calibration.get("metric", "faithfulness") == key\n', "")],
    "render: calibration counts for any method": [(RENDER, '        and calibration.get("method") == report.get("judge_method")\n', "")],
    "calibrate: contexts from another run": [(CALIBRATE, 'retrieved = runs[row["run_id"]][row["case_id"]]["retrieved"]', 'retrieved = runs[row["run_id"]][row["case_id"]]["retrieved"][::-1]')],
    # MiniCheck judge
    "minicheck: no read as supported": [
        (JUDGE, 'return {"sentence": sentence, "supported": word == "yes", "reason": reply}', 'return {"sentence": sentence, "supported": word == "no", "reason": reply}')
    ],
    "minicheck: prompt not the model card format": [
        (JUDGE, 'prompt = f"Document: {document}\\nClaim: {sentence}"', 'prompt = f"{document}\\n\\nIs this supported? {sentence}"')
    ],
    "minicheck: whole answer in one claim": [
        (JUDGE, "        return MiniCheckJudge(model, url)\n", "        return GuardianJudge(model, url)\n")
    ],
    # Keyword search and hybrid retrieval (app/keyword.py, RETRIEVAL=hybrid)
    "hybrid: dense only": [(RETRIEVER, "            return self._hybrid(vector, question)\n", "            pass\n")],
    "hybrid: keyword ranking ignored": [(RETRIEVER, "fuse(found[\"ids\"][0], self.keyword.ranking(question))", "fuse(found[\"ids\"][0])")],
    "hybrid: heading not indexed": [(RETRIEVER, "texts = [f\"{meta['heading_path']}\\n{text}\" for", "texts = [text for")],
    "hybrid: dense pool cut to k": [(RETRIEVER, "            n_results=self.collection.count(),\n", "            n_results=self.top_k,\n")],
    "hybrid: empty question accepted": [(RETRIEVER, "        if not question.strip():\n", "        if False:\n")],
    "hybrid: mode not checked": [(RETRIEVER, "        if mode not in MODES:\n", "        if False:\n")],
    "hybrid: question not passed": [(API, "retriever.search(vector, question)", "retriever.search(vector)")],
    "hybrid: mode not read": [(API, "Retriever(INDEX_DIR, backend, top_k, mode)", "Retriever(INDEX_DIR, backend, top_k)")],
    "bm25: idf ignored": [(KEYWORD, "score += self.idf[word] * tf", "score += tf")],
    "bm25: no length normalisation": [(KEYWORD, "B = 0.75\n", "B = 0.0\n")],
    "bm25: stopwords kept": [(KEYWORD, "if word not in STOPWORDS]", "if word]")],
    "bm25: numbers split at the point": [(KEYWORD, 'TOKEN = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)*")', 'TOKEN = re.compile(r"[a-z0-9]+")')],
    "bm25: worst first": [(KEYWORD, "key=lambda i: -scores[i]", "key=lambda i: scores[i]")],
    "rrf: ranks from zero": [(KEYWORD, "enumerate(ranking, start=1)", "enumerate(ranking, start=0)")],
    "rrf: worst first": [(KEYWORD, "key=lambda item: -item[1]", "key=lambda item: item[1]")],
    # Example questions per chunk (app/questions.py, RETRIEVAL=questions)
    "questions: mode never used": [(RETRIEVER, "        if self.question_owners is not None:\n            return self._with_questions(vector)\n", "")],
    "questions: question score ignored": [(RETRIEVER, "            best[owner] = max(best[owner], float(similarity))\n", "            pass\n")],
    "questions: worst of chunk and question": [(RETRIEVER, "best[owner] = max(best[owner], float(similarity))", "best[owner] = min(best[owner], float(similarity))")],
    "questions: embedded as documents": [(RETRIEVER, "self.embedder.embed_queries([q for", "self.embedder.embed_documents([q for")],
    "questions: vectors not normalised": [(RETRIEVER, "self.question_vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)", "self.question_vectors = vectors * 2")],
    "questions: worst first": [(RETRIEVER, "key=lambda chunk_id: -best[chunk_id]", "key=lambda chunk_id: best[chunk_id]")],
    "questions: stale file accepted": [(QUESTIONS, 'if entry is None or entry["chunk_sha256"] != chunk_hash(meta["heading_path"], text):', "if entry is None:")],
    "questions: heading left out of the prompt": [(QUESTIONS, 'substitute(passage=f"{heading_path}\\n{_clean(text)}")', "substitute(passage=_clean(text))")],
    "questions: duplicates kept": [(QUESTIONS, "return list(dict.fromkeys(question.strip()", "return list((question.strip()")],
    "questions: sampled, not temperature 0": [(QUESTIONS, '"options": {"temperature": 0, "seed"', '"options": {"temperature": 0.8, "seed"')],
    # English-only reply (app/language.py)
    "language: gate never runs": [(API, "            if not is_english(question):\n                return english_only(retriever, record, started)\n", "")],
    "language: every question gated": [(API, "            if not is_english(question):\n", "            if True:\n")],
    "language: reply counted as a refusal": [(API, "            answer=ENGLISH_ONLY,\n            abstained=False,\n", "            answer=ENGLISH_ONLY,\n            abstained=True,\n")],
    "language: other script ignored": [(LANGUAGE, "        return False\n    words = WORD", "        pass\n    words = WORD")],
    "language: one foreign word is enough": [(LANGUAGE, "return not (other >= 2 and other > english)", "return not (other >= 1 and other > english)")],
    "language: accented words not counted": [(LANGUAGE, "word in OTHER or not word.isascii()", "word in OTHER")],
    "language: English words not counted": [(LANGUAGE, "english = sum(word in ENGLISH for word in words)", "english = 0")],
    # Freshness gate (evals/freshness.py)
    "freshness: stale inputs accepted": [(FRESHNESS, '    elif report["inputs_sha256"] != inputs_digest(version, root):\n', "    elif False:\n")],
    "freshness: other settings accepted": [(FRESHNESS, "    if changed:\n", "    if False:\n")],
    "freshness: app code not an input": [(FRESHNESS, '    files = sorted((root / "app").glob("*.py"))\n', "    files = []\n")],
    "freshness: line endings change the digest": [(FRESHNESS, '        digest.update(path.read_bytes().replace(b"\\r\\n", b"\\n"))\n', "        digest.update(path.read_bytes())\n")],
    "freshness: runs not stamped": [(RUN_EVALS, "        **stamp(env),\n", "")],
    "freshness: another Ollama version accepted": [(FRESHNESS, "    if pinned and version != pinned:\n", "    if False:\n")],
    "pin: eval run starts on any Ollama": [(RUN_EVALS, "        require_pinned_ollama(env)\n", "        pass\n")],
    "pin: experiment refused on another Ollama": [(RUN_EVALS, ' and not args.experiment:\n', ":\n")],
    "pin: attack run starts on any Ollama": [(ATTACK_RUN, "        require_pinned_ollama(env)\n", "        pass\n")],
    # Smoke gates, per case against the accepted reference (evals/gates.py)
    "smoke: lost hit accepted": [(GATES, '    lost_hit = [cid for cid in shared if before[cid].get("hit") and not cases[cid].get("hit")]\n', "    lost_hit = []\n")],
    "smoke: new refusals accepted": [(GATES, "    newly_refused = [cid for cid in answerable if answered(before[cid]) and not answered(cases[cid])]\n", "    newly_refused = []\n")],
    "smoke: lost facts accepted": [(GATES, 'gates.append(Gate("no required fact lost", not facts_lost,', 'gates.append(Gate("no required fact lost", True,')],
    "smoke: missing cases accepted": [(GATES, 'gates = [Gate("every reference case ran", not missing,', 'gates = [Gate("every reference case ran", True,')],
    "smoke: run not kept as smoke latest": [(RUN_EVALS, '        shutil.copyfile(path, reports_dir / "smoke" / "latest.json")\n', "        pass\n")],
    "harness: an unavailable case is not retried": [(RUN_EVALS, "        except ServiceUnavailable:\n", "        except ZeroDivisionError:\n")],
    "harness: a retry is not recorded": [(RUN_EVALS, '            retried.append(case["id"])\n', "            pass\n")],
    # Metric history chart (evals/history_chart.py)
    "chart: not redrawn after a full dev run": [(RUN_EVALS, '        history_chart.write(history_path, reports_dir / "history.svg")\n', "        pass\n")],
    "chart: missing value drawn as zero": [(CHART, "    if not text:\n        return None\n", "    if not text:\n        return 0.0\n")],
    "chart: latency not in seconds": [(CHART, '    return number / 1000 if column == "latency_p95_ms" else number\n', "    return number\n")],
    "chart: setup changes not marked": [(CHART, "        if parts:\n", "        if False:\n")],
    "chart: rates on their own scale": [(CHART, '    top = 1.0 if scale == "rate" else', "    top = max(known) if scale == \"rate\" else")],
    # End-of-stage holdout check (evals/holdout.py)
    "holdout: another setup accepted": [(HOLDOUT, '    if report.get("inputs_sha256") != dev.get("inputs_sha256") or report.get("settings") != dev.get("settings"):\n', "    if False:\n")],
    "holdout: missing cases accepted": [(HOLDOUT, "    if ran != ids:\n", "    if False:\n")],
    "holdout: an experiment confirms a setup": [(HOLDOUT, ' or report.get("smoke") or report.get("experiment"):\n', ' or report.get("smoke"):\n')],
    "holdout: stale run accepted": [(HOLDOUT, "    found += freshness_problems(report, root, env_example)\n", "")],
    "holdout: exposed cases not marked": [(HOLDOUT, '        return case_id + ("*" if case_id in EXPOSED_HOLDOUT else "")\n', "        return case_id\n")],
    "holdout: run not kept as holdout latest": [(RUN_EVALS, '        shutil.copyfile(path, reports_dir / "holdout" / "latest.json")\n', "        pass\n")],
    # Phoenix export (evals/phoenix_export.py)
    "phoenix: holdout runs exported": [(PHOENIX, '    if report.get("split") != "dev":\n', "    if False:\n")],
    "phoenix: failed cases not marked": [(PHOENIX, "        error=f\"case {case['id']} failed its eval\" if is_failed else None,\n", "        error=None,\n")],
    "phoenix: the run's last second missed": [(PHOENIX, "+ timedelta(seconds=1)\n", "\n")],
    "phoenix: check shows the refusal, not the answer": [(PHOENIX, '                    "input.value": model_answer(record),\n', '                    "input.value": parsed.get("answer", ""),\n')],
    "phoenix: children not under their request": [(PHOENIX, "        spans.append(span(name, kind, clock, stop, attributes, parent=0))\n", "        spans.append(span(name, kind, clock, stop, attributes))\n")],
    # The canary PR's break (README, CI gates): the prompt loses its passages, nothing crashes
    "prompt: passages dropped ({context} for $context)": [(PROMPT_V5, "\n$context", "\n{context}")],
    "prompt: question dropped": [(PROMPT_V5, "\n$question", "\nthe question")],
    # Demo company database (mcp_server/db.py, mcp_server/seed.py)
    "db: foreign keys off": [(DB_FILE, 'connection.execute("PRAGMA foreign_keys = ON")', 'connection.execute("PRAGMA foreign_keys = OFF")')],
    "db: projects under 100 kWp accepted": [(DB_FILE, "CHECK (power_kw >= {MIN_POWER_KW})", "CHECK (power_kw >= 0)")],
    "db: a stage missing from the vocabulary": [(DB_FILE, '    "Contract",\n', "")],
    "db: connection left open": [(DB_FILE, "    finally:\n        connection.close()\n", "    finally:\n        pass\n")],
    "seed: a failed seed replaces the database": [(SEED, "    finally:\n        connection.close()\n    partial.replace(target)\n", "    finally:\n        connection.close()\n        partial.replace(target)\n")],
    # MCP tools (mcp_server/tools.py, mcp_server/server.py)
    "tools: lead under 100 kWp saved": [(TOOLS, "    if power_kw < MIN_POWER_KW:\n", "    if False:\n")],
    "tools: power as text accepted": [(TOOLS, "    if isinstance(power_kw, bool) or not isinstance(power_kw, (int, float)):\n", "    if False:\n")],
    "tools: missing contact data invented as blank": [(TOOLS, "    if missing:\n", "    if False:\n")],
    "tools: duplicate email accepted": [(TOOLS, '            return _error("a request with this email already exists; the sales team will reply to it")\n', "            pass\n")],
    "tools: survey in the past booked": [(TOOLS, "    if day <= today:\n", "    if False:\n")],
    "tools: survey past the survey stage booked": [(TOOLS, '    if row["stage"] not in SURVEY_STAGES:\n', "    if False:\n")],
    "tools: booking confirmed at once": [(TOOLS, "\" VALUES (?, ?, 'pending', ?, ?)\"", "\" VALUES (?, ?, 'confirmed', ?, ?)\"")],
    "tools: another conversation confirms": [(TOOLS, "\"SELECT * FROM site_surveys WHERE session_id = ? AND status = 'pending'", "\"SELECT * FROM site_surveys WHERE ? IS NOT NULL AND status = 'pending'")],
    "tools: old proposal kept pending": [(TOOLS, "\"UPDATE site_surveys SET status = 'cancelled' WHERE session_id = ? AND status = 'pending'\"", "\"SELECT ? WHERE 0\"")],
    "tools: confirmation given to the agent": [(TOOLS, "AGENT_TOOLS = (create_lead, get_project_status, find_product, book_site_survey)\n", "AGENT_TOOLS = (create_lead, get_project_status, find_product, book_site_survey, confirm_pending_survey)\n")],
    "tools: a planted note reaches the model": [(TOOLS, '"notes": NOTE_WITHHELD if suspicious(row["comment"]) else row["comment"],', '"notes": row["comment"],')],
    "tools: every note is withheld": [(TOOLS, '"notes": NOTE_WITHHELD if suspicious(row["comment"]) else row["comment"],', '"notes": NOTE_WITHHELD,')],
    "server: confirmation exposed as a tool": [(MCP_SERVER, "for tool in (create_lead, get_project_status, find_product, book_site_survey):\n", "for tool in (create_lead, get_project_status, find_product, book_site_survey, tools.confirm_pending_survey):\n")],
    # The /chat agent (app/agent.py, app/api.py)
    "agent: the model rewrites the checked answer": [(AGENT, "                    reply = result.answer\n                    break\n", "                    messages.append({\"role\": \"tool\", \"tool_name\": name, \"content\": result.answer})\n                    break\n")],
    "agent: the model picks the session": [(AGENT, "result = self.tools.call(name, {**arguments, SESSION_ARGUMENT: session.session_id})", "result = self.tools.call(name, {SESSION_ARGUMENT: session.session_id, **call['arguments']})")],
    "agent: any message confirms a booking": [(AGENT, "        if session.pending and is_confirmation(message):\n", "        if session.pending:\n")],
    "agent: the reply guard is off": [(AGENT, "        if problems:\n", "        if False:\n")],
    "agent: phone numbers pass": [(AGENT, "        if phone_digits(reply) - phone_digits(own_text):\n", "        if False:\n")],
    "agent: other customers' names pass": [(AGENT, "        if names:\n", "        if False:\n")],
    "agent: a guessed session id is adopted": [(AGENT, "            session = Session(uuid.uuid4().hex)\n", "            session = Session(session_id or uuid.uuid4().hex)\n")],
    "agent: the model sees the session id": [(AGENT, "    schema.get(\"properties\", {}).pop(SESSION_ARGUMENT, None)\n", "")],
    "agent: another language reaches the model": [(AGENT, "        if not is_english(message):\n", "        if False:\n")],
    "agent: a date not on record reaches the customer": [(AGENT, "            if stated - allowed:\n", "            if False:\n")],
    "agent: dates from tools count as not on record": [(AGENT, '            allowed = {session.pending["survey_date"]} | {d for c in calls for d in DATE.findall(json.dumps(c["result"]))}\n', '            allowed = {session.pending["survey_date"]}\n')],
    "agent: a model refusal stands": [(AGENT, "        if not calls and MODEL_REFUSAL.search(reply):\n", "        if False:\n")],
    "agent: a refusal after a tool call is overruled": [(AGENT, "        if not calls and MODEL_REFUSAL.search(reply):\n", "        if MODEL_REFUSAL.search(reply):\n")],
    "api: chat traces look like ask traces": [(API, '{"endpoint": "chat", **turn.record, "status": 200,', '{"endpoint": "chat", "question": request.message, **turn.record, "status": 200,')],
    # The agent eval's scorer (evals/agent_eval.py)
    "agent eval: any overlapping tool counts": [(AGENT_EVAL, '    result["tools"] = None if tools is None else called == set(tools)\n', '    result["tools"] = None if tools is None else (not tools or bool(called & set(tools)))\n')],
    "agent eval: arguments not compared": [(AGENT_EVAL, "            ok = ok and bool(made) and _matches(expected, made[-1])\n", "            ok = ok and bool(made)\n")],
    "agent eval: asking needs no question": [(AGENT_EVAL, '"?" in last and any(', 'any(')],
    "agent eval: the customer's own details are leaks": [(AGENT_EVAL, " and email.casefold() not in own:", ":")],
    "agent eval: phone leaks missed": [(AGENT_EVAL, "            if digits in phone_digits(reply) and digits not in own_phones:\n", "            if False:\n")],
    "agent eval: a yes does not allow a booking": [(AGENT_EVAL, "    allowed = sum(1 for i, message in enumerate(case[\"turns\"]) if i > 0 and is_confirmation(message))\n", "    allowed = 0\n")],
    "agent eval: an error counts as a fail": [(AGENT_EVAL, '    result["passed"] = None if outcome["error"] else (', '    result["passed"] = False if outcome["error"] else (')],
    "agent eval: a holdout case passes as dev": [(AGENT_EVAL, '        if case.get("split") != split:\n', "        if False:\n")],
    "agent eval: the saved lead is not compared": [(AGENT_EVAL, "            ok = _matches(lead_args, db[\"leads\"][0])\n", "            ok = True\n")],
    "agent eval: prices not checked": [(AGENT_EVAL, "(not any(PRICE.search(reply) for reply in replies))", "True")],
    "agent eval: invented dates not checked": [(AGENT_EVAL, '        result["no_invented_dates"] = all(dates_in(reply) <= given for reply in replies)\n', '        result["no_invented_dates"] = True\n')],
    "agent eval: dates from tools count as invented": [(AGENT_EVAL, '        given |= {d for call in calls for d in dates_in(json.dumps(call.get("result", {})))}\n', "")],
    "agent eval: written dates not read": [(AGENT_EVAL, "            found.add(date(int(year or TODAY.year), number, int(day)).isoformat())\n", "            continue\n")],
    "agent eval: a holdout run keeps its replies": [(AGENT_EVAL, '    if split == "holdout":\n        return results\n', '    if False:\n        return results\n')],
    # Agent CI gates (evals/agent_gates.py)
    "agent gates: a lost case passes": [(AGENT_GATES, '    lost = sorted(i for i in before if i in now and before[i]["passed"] and now[i]["passed"] is False)\n', "    lost = []\n")],
    "agent gates: a working attack passes": [(AGENT_GATES, '        worked = [r["id"] for r in cases if r["passed"] is False]\n', "        worked = []\n")],
    "agent gates: a stale run is gated": [(AGENT_GATES, '    if report.get("agent_inputs_sha256") != agent_inputs_digest(root):\n', "    if False:\n")],
    "agent gates: another prompt version is gated": [(AGENT_GATES, '    if report.get("agent_prompt_version") != default_version:\n', "    if False:\n")],
    "agent gates: leaks pass": [(AGENT_GATES, 'Gate("personal-data leaks", not leaks,', 'Gate("personal-data leaks", True,')],
    "agent gates: errors pass": [(AGENT_GATES, 'Gate("errors", not errors,', 'Gate("errors", True,')],
    # CI gates (evals/gates.py)
    "gates: out-of-scope answers ignored": [(GATES, 'Gate("out-of-scope answered", not answered_oos,', 'Gate("out-of-scope answered", True,')],
    "gates: any reply counts as English-only": [(GATES, "if not (answered(c) and language_reply(c.get(\"answer\", \"\")))]", "if not answered(c)]")],
    "gates: facts never rechecked": [(GATES, 'return missing_facts(case.get("answer", ""), facts) if answered(case) else list(facts)', "return []")],
    "gates: citations never checked": [(GATES, '        if missing_facts("\\n".join(c.get("cited_texts", [])), stated):\n', "        if False:\n")],
    "gates: calculated facts excused outright": [(GATES, "stated = [part for fact in facts for part in inputs.get(fact, [fact])]", "stated = [fact for fact in facts if fact not in inputs]")],
    "gates: hit rate has no floor": [(GATES, "HIT_RATE_MIN = 35", "HIT_RATE_MIN = 0")],
    "gates: run without citations accepted": [(GATES, '    if any(answered(case) and "cited_texts" not in case for case in report.get("cases", [])):\n', "    if False:\n")],
    "gates: experiment run accepted": [(GATES, ' or report.get("experiment"):', ":")],
    # Stage 4 defences (app/guards.py, the scan in app/index.py, the guard in app/api.py)
    "guards: scan finds nothing": [(GUARDS, "    return [name for name, pattern in INSTRUCTION_PATTERNS.items() if pattern.search(text)]", "    return []")],
    "guards: HTML comments allowed": [(GUARDS, '    "hidden HTML comment": r"<!--",\n', "")],
    "guards: ignore-the-rest allowed": [(GUARDS, "|\\bignore\\s+them\\b", "")],
    "guards: flagged chunks still indexed": [(INDEX, "            if reasons:\n", "            if False:\n")],
    "guards: any contact allowed": [(GUARDS, "        if emails - self.emails or hosts - self.hosts:\n", "        if False:\n")],
    "guards: foreign host allowed": [(GUARDS, "        if emails - self.emails or hosts - self.hosts:\n", "        if emails - self.emails:\n")],
    "guards: prices allowed": [(GUARDS, "        if PRICE.search(answer):\n", "        if False:\n")],
    "guards: prompt leaks allowed": [(GUARDS, "        if leaks_prompt(answer, self.ngrams):\n", "        if False:\n")],
    "guards: guard off by default": [(GUARDS, '        setting = env.get("OUTPUT_GUARD") or "on"\n', '        setting = env.get("OUTPUT_GUARD") or "off"\n')],
    "guards: guard not wired": [(API, "            if guard is not None:\n                result, problems = guard.review(result)\n", "            if guard is not None:\n                problems = guard.review(result)[1]\n")],
    "guards: default app without a guard": [(API, "        guard=OutputGuard.from_env(env, prompt),\n", "")],
    "guards: scan not in the fingerprint": [(INDEX, "    if corpus.quarantined:\n", "    if False:\n")],
    # Security gates on the committed attack run (evals/attack_run.py)
    "security: working attacks pass": [(ATTACK_RUN, 'Gate(f"{category} attacks that worked", hits == 0,', 'Gate(f"{category} attacks that worked", True,')],
    "security: stale run accepted": [(ATTACK_RUN, 'gates.append(Gate("run uses the current attacks", current,', 'gates.append(Gate("run uses the current attacks", True,')],
    "security: errors unlimited": [(ATTACK_RUN, 'gates.append(Gate("errors", len(failed) <= MAX_ERRORS,', 'gates.append(Gate("errors", True,')],
    "security: any quarantine accepted": [(ATTACK_RUN, "            left_out == EXPECTED_QUARANTINE,\n", "            True,\n")],
    "security: crashes counted as failed attacks": [(ATTACK_RUN, '        if result["status"] != 200:\n            continue\n', "")],
    # Answer check (app/checker.py)
    "check: unsupported answer goes out": [
        (CHECKER, '        if verdicts and all(item["supported"] for item in verdicts):\n', "        if True:\n")
    ],
    "check: empty answer counts as checked": [(CHECKER, "        if verdicts and all(", "        if all(")],
    "check: unclear reply counts as supported": [(CHECKER, '== "yes" if reply else False', '!= "no" if reply else True')],
    "check: passages without headings": [
        (CHECKER, 'f"{hit.heading_path}\\n{hit.text}" if hit.heading_path else hit.text', "hit.text")
    ],
    "check: abstention keeps citations": [(CHECKER, "            citations=[],\n", "")],
    "check: no flag on a blocked answer": [(CHECKER, '{*result.flags, "answer_check_failed"}', "{*result.flags}")],
    "check: unknown method accepted": [(CHECKER, "        if method not in METHODS:\n", "        if False:\n")],
    "check: pin not checked": [(API, "            if checker is not None:\n                checker.check_pinned()\n", "")],
    "check: verdict ignored": [
        (API, "                result, verdicts = checker.review(result, hits)\n", "                _, verdicts = checker.review(result, hits)\n")
    ],
    "check: down is not a 503": [(API, "    CheckUnavailable,\n)", ")")],
    # Guardian judge
    "guardian: yes read as grounded": [(JUDGE, 'return 1.0 if word == "no" else 0.0', 'return 1.0 if word == "yes" else 0.0')],
    "guardian: risk not selected": [(JUDGE, '{"role": "system", "content": "groundedness"},', '{"role": "system", "content": "harm"},')],
    "guardian: any reply accepted": [(JUDGE, '        if word not in ("yes", "no"):\n', "        if False:\n")],
    "guardian: unsupported metrics judged": [
        (JUDGE, '[n for n in needed(item, case) if n in getattr(judge, "metrics", JUDGED)]', "needed(item, case)")
    ],
    # Judge and calibration
    "judge: refusals judged for faithfulness": [
        (JUDGE, 'answered = scored.get("status") == 200 and scored.get("refused") is False', 'answered = scored.get("status") == 200')
    ],
    "judge: language cases judged": [(JUDGE, 'if answered and case["expected_behaviour"] != "language refusal":', "if answered:")],
    "judge: retrieval metrics without gold": [(JUDGE, 'if case["gold"] and scored.get("retrieved"):', 'if scored.get("retrieved"):')],
    "judge: answer model may judge itself": [(JUDGE, 'if model == env.get("LLM_MODEL"):', "if False:")],
    "judge: failures hidden": [(JUDGE, "                        values.append(None)\n", "                        values.append(1.0)\n")],
    "judge: spread from one pass": [
        (JUDGE, 'max(per_pass) - min(per_pass) if len(per_pass) > 1 else None', "max(per_pass) - min(per_pass) if per_pass else None")
    ],
    "judge: reference missing from context metrics": [
        (JUDGE, '"reference": case["expected_answer"]', '"reference": scored["answer"]')
    ],
    "calibrate: kappa ignores chance": [(CALIBRATE, "return None if expected == 1 else (observed - expected) / (1 - expected)", "return observed")],
    "calibrate: almost-all counts as supported": [(CALIBRATE, "SUPPORTED_AT = 1.0 - 1e-9", "SUPPORTED_AT = 0.5")],
    "calibrate: agreement alone passes": [
        (CALIBRATE, '"passed": agreement >= AGREEMENT and kappa is not None and kappa >= KAPPA,', '"passed": agreement >= AGREEMENT,')
    ],
    "calibrate: labels overwritten": [(CALIBRATE, "    if path.exists():\n        raise SystemExit", "    if False:\n        raise SystemExit")],
    "calibrate: refusals labelled": [
        (CALIBRATE, 'if item["split"] != "dev" or item.get("status") != 200 or item.get("refused") is not False:', 'if item["split"] != "dev":')
    ],
    "calibrate: labeller not required": [
        (CALIBRATE, "    if not args.make_labels and not args.labelled_by.strip():\n", "    if False:\n")
    ],
    "calibrate: labeller not recorded": [(CALIBRATE, '        "labelled_by": labelled_by,\n', "")],
    "calibrate: empty label allowed": [(CALIBRATE, 'not in ("yes", "no")', 'not in ("yes", "no", "")')],
    "render: uncalibrated judge shown": [(RENDER, "        if value is None or (judged and not trusted(report, calibration, key)):", "        if value is None:")],
    "render: another judge's calibration trusted": [
        (RENDER, '        and calibration.get("judge_model") == report.get("judge_model")\n', "")
    ],
    # Golden dataset validator
    "golden: substring match for must_include": [
        (VALIDATOR, 'if not contains_fact(case["expected_answer"], fact):', 'if fact.lower() not in case["expected_answer"].lower():')
    ],
    "golden: clarify may require a value": [
        (VALIDATOR, 'if case["expected_behaviour"] == "clarify" and case["must_include"]:', "if False:")
    ],
    "golden: empty reviewer allowed": [
        (VALIDATOR, "if reviewer is not None and (not isinstance(reviewer, str) or not reviewer.strip()):", "if False:")
    ],
    "golden: any author allowed": [(VALIDATOR, 'if case["authored_by"] not in AUTHORS:', "if False:")],
    "golden: mixed versions allowed": [(VALIDATOR, "    if len(versions) != 1:\n", "    if False:\n")],
    "golden: holdout edit allowed": [(VALIDATOR, "    if digest != holdout_hash(cases):\n", "    if False:\n")],
    "golden: unfrozen version allowed": [(VALIDATOR, "    if version != current:\n", "    if False:\n")],
    "golden: byte order mark breaks the file": [(VALIDATOR, 'encoding="utf-8-sig", newline=""', 'encoding="utf-8", newline=""')],
    "golden: empty labels skipped": [
        (VALIDATOR, '        elif not label:\n            problems.append(f"{row[\'id\']}: behaviour is empty")\n', "")
    ],
    "golden: unknown labels allowed": [(VALIDATOR, "        elif label not in BEHAVIOURS:\n", "        elif False:\n")],
    "golden: agreement always exits 0": [
        (VALIDATOR, "return 0 if share is not None and share >= ACCEPT else 1", "return 0")
    ],
}


LEFT_OUT = shutil.ignore_patterns(
    ".git", ".venv", ".venv-phoenix", ".phoenix", ".chroma", ".env", "runs", "reports", "__pycache__", ".hypothesis", ".pytest_cache", ".ruff_cache"
)


def copy_project(folder):
    """A copy with what the unit and API tests need, like a clean CI checkout."""
    work = folder / "project"
    shutil.copytree(ROOT, work, ignore=LEFT_OUT)
    # The CI gate and guard tests read committed runs, which a CI checkout has too.
    (work / "reports").mkdir()
    shutil.copy2(ROOT / "reports" / "latest.json", work / "reports" / "latest.json")
    shutil.copytree(ROOT / "reports" / "security", work / "reports" / "security")
    shutil.copytree(ROOT / "reports" / "smoke", work / "reports" / "smoke")
    shutil.copy2(ROOT / "reports" / "history.svg", work / "reports" / "history.svg")
    shutil.copytree(ROOT / "reports" / "agent", work / "reports" / "agent")
    return work


def in_copy(path, work):
    return work / path.relative_to(ROOT)


def run_tests(work):
    shutil.rmtree(work / ".hypothesis", ignore_errors=True)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "tests/unit", "tests/api", "tests/data", "-q", "-x", "-p", "no:cacheprovider"],
        cwd=work,
        check=False,
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


def apply_break(edits, originals, work):
    """Write the broken files into the copy. Edits to one file apply together."""
    sources = read_sources(originals)
    for path, old, new in edits:
        sources[path] = sources[path].replace(old, new)
    for path in {path for path, _, _ in edits}:
        in_copy(path, work).write_bytes(sources[path].encode("utf-8"))


def restore(originals, work):
    for path, original in originals.items():
        in_copy(path, work).write_bytes(original)


def main():
    parser = argparse.ArgumentParser(description="Check that the unit tests catch deliberate breaks.")
    parser.add_argument("--only", default="", help="run only breaks whose name contains this text")
    args = parser.parse_args()
    selected = {name: edits for name, edits in BREAKS.items() if args.only in name}
    files = (CHUNKER, EMBEDDER, INDEX, SETTINGS, RETRIEVER, GENERATOR, API, CHECKER, KEYWORD, QUESTIONS, LANGUAGE, GATES, FRESHNESS, CHART, HOLDOUT, PHOENIX, PROMPT_V5, DB_FILE, SEED, TOOLS, MCP_SERVER, AGENT, AGENT_EVAL, AGENT_GATES, GUARDS, ATTACK_RUN, SCORING, VALIDATOR, METRICS, SYSTEMS_FILE, RUN_EVALS, RENDER, JUDGE, CALIBRATE)
    originals = {path: path.read_bytes() for path in files}
    check_breaks_apply(selected, originals)

    survived = []
    with tempfile.TemporaryDirectory(prefix="mutation-") as folder:
        work = copy_project(Path(folder))
        baseline = run_tests(work)
        if baseline.returncode != 0:
            sys.exit("the unbroken code fails, so the results would mean nothing:\n" + baseline.stdout[-1500:])
        print("baseline passes", flush=True)
        for name, edits in selected.items():
            apply_break(edits, originals, work)
            result = run_tests(work)
            restore(originals, work)
            caught = result.returncode != 0
            print(f"{'caught  ' if caught else 'SURVIVED'} {name}  {failed_test(result) if caught else ''}", flush=True)
            if not caught:
                survived.append(name)
    print(f"total {len(selected)}, caught {len(selected) - len(survived)}, survived: {survived or 'none'}")
    sys.exit(1 if survived else 0)


if __name__ == "__main__":
    main()

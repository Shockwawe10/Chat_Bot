# Learning log

One entry per merged PR, written in my own words (see the AI-assisted development policy in the README).

## Template

```markdown
## YYYY-MM-DD: <PR title>

**What changed:**
**How it works, in my own words:**
**How I checked it:**
**Manual change of the day:**
**What I learned / what is still unclear:**
```

---

## 2026-10-28: Stage 0, setup and demo domain

**What changed:**
Added a knowledge base a bout a company. Glossary had 26 terms. Test specs was imlemented as stated
**How it works, in my own words:**
WE have a base for start of the development, glossary and data about the company. Ansd alos test to help check learning base and glossary
**How I checked it:**
Mannually
**Manual change of the day:**
Insallation of LLM Ollama. Installed 3 local models 
**What I learned / what is still unclear:**
About knowledge base and ways to test it, how to install local ai. The rest is still unclear.
Fix is to make Ollama return structured JSON (its format option) instead of relying on the instruction. 

## 2026-10-30: Stage 1, chunker, embedder and index

*Drafted by Claude Code at my request, not written in my own words yet.*

**What changed:**
Added the chunker (`app/chunker.py`), embedder (`app/embedder.py`), Chroma index (`app/index.py`), shared settings (`app/settings.py`), the chunk report (`evals/chunk_report.py`) and the mutation check (`evals/mutation_check.py`). Settings changed: `CHUNK_OVERLAP` was removed, and `CHUNK_MAX`, `CHUNK_MIN`, `EMBEDDING_DIGEST` and `OLLAMA_URL` were added. The embedding model is pinned as `nomic-embed-text:v1.5`.
**How it works, in my own words:**
The chunker cuts each knowledge base file into pieces of about 500 characters without breaking paragraphs, list items or table rows. Each piece keeps its exact position in the file and its heading path, and a title with no text of its own joins the next section. The embedder turns each piece into 768 numbers, so pieces with a similar meaning get similar numbers. The index stores those numbers in Chroma. Each combination of settings gets its own collection, and a new collection only becomes active after the build checks pass. If nothing changed, a re-run does nothing.
**How I checked it:**
331 tests pass. Property tests with Hypothesis check the chunker's rules on generated documents. The real model built 91 chunks and passed every check, including 100% self-retrieval and Chroma's top 10 matching brute force. A second run was a no-op, and `CHUNK_SIZE=300` built a second collection with 106 chunks and left the first alone. `python -m evals.mutation_check` broke the code on purpose in 72 ways, and the tests caught all 72.
**Manual change of the day:**
None today.
**What I learned / what is still unclear:**
- Passing tests prove little until you see them fail. The first mutation round found 2 gaps in the tests.
- A result that looks wrong is worth following up. One break was caught by an unrelated test, and that led to F2: a Chroma read error could delete a good collection.
- Hypothesis replays saved failures, which once made 25 breaks look caught. Clear the saved examples before each break.
- Ollama's vectors are unit length, so L2 and cosine rank the same. A wrong metric has to be checked directly.
- By default Ollama silently cuts long input at 2048 tokens, so the embedder sets `truncate: false`.
- Dead config is a trap: a setting nothing reads looks like a change that took effect.

Still unclear: gold-span coverage is not measured until `evals/gold_spans.jsonl` exists in Stage 2, and the chunker may change once it does. A chunker code change also needs a manual bump of `chunker_version`, or an old index still counts as up to date.

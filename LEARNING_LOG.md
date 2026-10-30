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

## 2026-10-30: Stage 1, retrieval, generation, API and CI

*Drafted by Claude Code at my request, not written in my own words yet. The verdicts in the sanity table are also its draft and still need my review.*

**What changed:**
Added retrieval (`app/retriever.py`), generation (`app/generator.py`), the prompt (`prompts/answer_v1.txt`) and `POST /ask` (`app/api.py`). Every request is traced to `runs/traces/`. Added a Makefile, `ruff` and a GitHub Actions workflow. API tests are in `tests/api/`, and real-model tests are in `tests/integration/` and run with `pytest -m real`.
**How it works, in my own words:**
The question is embedded and the 5 closest chunks are found in Chroma. The app refuses an index built with another model. The chunks go into a numbered prompt, and the model must reply in JSON with an answer, the passage numbers it used, and whether it abstained. The server checks those numbers and turns them into chunk ids, so the model cannot invent a source. If it abstains, the answer is a fixed sentence. The response also shows every retrieved chunk, any flags, timings and the versions used.
**How I checked it:**
432 tests pass without Ollama, and 4 real-model tests pass, including the same question twice giving the same output. The mutation check caught 134 of 134 breaks before the final lint fixes. A clean clone passed lint and tests, and CI passed on GitHub. The real server answered over HTTP and returned 422 for a blank question.

10 manual sanity questions, on the real models:

| # | Question | Answer | Verdict |
| --- | --- | --- | --- |
| 1 | Which corrosivity category is RoofFlat RF-2 rated for? | C4 | Correct |
| 2 | What is the maximum snow load for GroundFrame GF-1? | 2.4 kN/m² | Correct |
| 3 | How long is a commercial offer valid? | 30 days from its date | Correct |
| 4 | What extra information do you need for a roof project quote? | Roof type and covering, slope, age of the building and waterproofing, drawings or a structural report | Correct |
| 5 | Can I use GF-1 on a site 5 km from the sea? | "Yes", and it contradicts itself | **Wrong.** The knowledge base says GF-1 is not used within 10 km of the sea, and GF-2 is used there. No flag was raised |
| 6 | How long is the installation warranty, and when does it start? | 5 years, from the handover certificate | Correct |
| 7 | What is your price per kWp? | No standard price, and lists what the price depends on | Correct, no invented number. It did not abstain |
| 8 | Can you install a solar system on my private house? | No, the smallest project is 100 kWp | Correct |
| 9 | Why do all your mounting systems use corrosivity category C5? | Abstained | Safe, not ideal. It did not accept the false premise, but it did not correct it either |
| 10 | Wie lange gilt die Produktgarantie? | Abstained | Safe, not ideal. The README wants a reply that only English is supported |

Result: 7 correct, 2 safe but not ideal, 1 wrong.
**Manual change of the day:**
None today.
**What I learned / what is still unclear:**
- A wrong answer can pass every test. Question 5 had the right documents and no flags, and only reading the answer showed the mistake. That is why Stage 2 needs a golden dataset.
- The model gets exact facts right but is weaker at reasoning about them, like "5 km is within 10 km".
- Check how the tools really behave before relying on them. On this Ollama version an over-long chat prompt is refused with a 400, not silently cut, and there is no tokenizer endpoint.
- At temperature 0 a new seed gave the same output, so a retry needs a small temperature to be able to differ.
- The model can mark a correct answer as abstained unless the prompt defines that field clearly.

Still unclear: should question 7 count as a correct answer or as a required refusal? The README lists price questions as "must refuse", but the knowledge base does say there is no price list. Decide this for the golden dataset. Questions 5, 9 and 10 should become golden cases in Stage 2. For the GF-2 category question, a GF-1 chunk ranked first, so retrieval needs checking too.

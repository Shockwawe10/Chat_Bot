# Learning log

One entry per merged PR. AI may draft an entry, but I review and edit it, and a draft says so at the top until I have (the project's AI-assisted development and authorship rules).

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

**Informal set (exploratory, not counted):** 10 manual questions on the real models, run before the frozen set below.

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

## Stage 1 sanity questions (frozen before the first run)

Drafted by Claude from data/kb and reviewed by me on 2026-10-30, before these questions were run. An earlier informal set of 10 had already been run on the same pipeline, so the drafting was not blind to how the pipeline behaves.

| # | Type | Question | Expected answer | Gold source (doc › section) |
|---|---|---|---|---|
| 1 | Table lookup | What is the minimum ground clearance of GroundFrame GF-2? | At least 0.6 m. | products-ground-mount-gf2 › Specifications |
| 2 | Simple fact | How long is a commercial offer valid? | 30 days from its date; after that it is recalculated because steel and aluminium prices change. | pricing-commercial-offer › Commercial offer |
| 3 | Two chunks | Which fasteners does RF-2 use, and why those? | Stainless steel A4. RF-2 is rated C4, and A4 is used from C4 up because it resists chlorides from salt better. | products-flat-roof-rf2 › Specifications + corrosion-coatings › Stainless steel fasteners |
| 4 | Two chunks, numeric | Our ground-mount site has a snow load of 3.0 kN/m². Can GF-1 handle it? | No as standard: GF-1's maximum is 2.4 kN/m². The team either designs a reinforced version or proposes another product (GF-2 goes to 3.5 kN/m²), decided in the preliminary design. | products-ground-mount-gf1 › Specifications (or loads table) + loads-wind-and-snow › When a site exceeds the maximum |
| 5 | Stated absence | What is your phone number? | The company doesn't publish one. Email sales@example.com (new projects) or support@example.com (existing projects); a project manager calls back if a call is useful. | company-contacts › Email |
| 6 | Applying a rule | Can you build a 50 kWp system on our office roof? | No. The smallest project the company accepts is 100 kWp. | company-overview › What the company does not do |
| 7 | Unanswerable (far) | Who founded Example Solar, and in what year? | Abstain. Not in the knowledge base. | none |
| 8 | Unanswerable (near miss) | What torque should GF-1 bolts be tightened to? | Abstain. Torque checks are mentioned, but no value is given. | none (distractors: services-installation › Handover, services-maintenance › What an inspection covers) |
| 9 | Against intuition | GF-1's coating is 85 µm and GF-2's only 25 µm, so GF-1 resists corrosion better, right? | No. GF-2 is rated C5 and GF-1 C4; the zinc-magnesium coating protects better in salty air, and thickness alone doesn't show which resists corrosion better. | products-ground-mount-gf2 › Thin but stronger coating |
| 10 | Ambiguous | What is the maximum wind speed? | Ask which product, or list per product (28 to 36 m/s). Bonus: two other wind limits exist (installation stops above 12 m/s; extra inspection after gusts above 25 m/s). | loads-wind-and-snow › Maximum values per product |

### Results

Verdicts: correct / partly correct / wrong / abstained wrongly / should have abstained.
Failed stage: chunking / retrieval / generation / citation.

Rules for every table below:
- Any false claim makes the answer wrong, even if the rest is right. Partly correct means true but incomplete.
- The primary failed stage is the earliest one that failed. Later failures are listed as secondary.

*Run 1, on 2026-10-30 at commit `a3c0e9c`, with no changes to the pipeline or prompt. Claude Code drafted the verdicts and failed stages, and they were revised after review on the same day. Chunk ids are shortened to `doc:index`; the full ids and raw model outputs are in `runs/traces/`.*

| # | Retrieved chunk ids (rank order) | Cited | Answer (short) | Verdict | Failed stage | Notes |
|---|---|---|---|---|---|---|
| 1 | products-ground-mount-gf2:1, products-ground-mount-gf2:0, products-ground-mount-gf2:2, products-ground-mount-gf1:1, products-ground-mount-gf1:2 | products-ground-mount-gf2:1 | At least 0.6 m. | correct | — | Gold chunk at rank 1. |
| 2 | pricing-commercial-offer:2, process-cooperation-stages:2, services-supply:2, process-quote-requirements:4, pricing-commercial-offer:1 | pricing-commercial-offer:2 | 30 days from its date. | partly correct | generation | Gold chunk at rank 1. The main fact is right; it left out the recalculation. |
| 3 | corrosion-coatings:2, products-overview:2, products-flat-roof-rf2:2, products-flat-roof-rf2:0, products-flat-roof-rf2:1 | corrosion-coatings:2, products-flat-roof-rf2:1 | A4, because it resists chlorides and suits systems rated "up to C4". | wrong | generation | Both gold chunks retrieved and cited. The source says C4 and above, so "up to C4" turns the rule upside down and a customer would conclude the opposite. |
| 4 | products-ground-mount-gf1:1, products-ground-mount-gf1:3, products-ground-mount-gf2:2, products-ground-mount-gf1:2, products-ground-mount-gf1:0 | products-ground-mount-gf1:1 | No, the maximum for GF-1 is 2.4 kN/m². | partly correct | retrieval; secondary: generation | The "When a site exceeds the maximum" chunk was not retrieved, so the reinforced option was never in the context. The GF-2 limit of 3.5 kN/m² was retrieved but not used. |
| 5 | company-contacts:0, company-contacts:1, company-contacts:2, warranty:3, process-quote-requirements:1 | none | Fixed abstain sentence. | abstained wrongly | generation; secondary: fixed-sentence rule (spec bug) | Gold chunk at rank 1. The raw output said "The company does not publish a phone number." but set `abstained: true`, so the fixed sentence replaced it. No flag was raised. |
| 6 | process-quote-requirements:1, company-overview:3, company-overview:1, products-flat-roof-rf2:2, services-installation:2 | process-quote-requirements:1, company-overview:1, products-flat-roof-rf2:2 | "Yes", with RF-2 as the reason. | wrong (answer without support) | retrieval; secondary: generation | The 100 kWp rule was not in the 5 chunks, though two other chunks of the gold document were. Given what it saw, the right response was to abstain. The context said the company does flat roofs, and the model read "no stated limit" as "allowed". The cited chunks support the flat-roof facts but not the "Yes". No flag was raised. Stage 2 test case for hybrid search and reranking: the question and the gold sentence ("smallest project it accepts") share almost no words. |
| 7 | company-overview:0, company-overview:3, company-overview:1, company-overview:2, services-overview:0 | none | Fixed abstain sentence. | correct | — | |
| 8 | products-ground-mount-gf1:2, products-ground-mount-gf1:1, products-ground-mount-gf1:0, products-ground-mount-gf2:3, products-overview:2 | none | Fixed abstain sentence. | correct | — | The near-miss distractors were never retrieved, so the test did not exercise what it was designed for. For Stage 2: confirm the distractors are actually retrieved before counting a question as a near-miss abstention test. |
| 9 | products-ground-mount-gf2:3, products-ground-mount-gf1:2, products-overview:2, corrosion-coatings:0, products-ground-mount-gf2:1 | none | Fixed abstain sentence. | abstained wrongly | generation; secondary: fixed-sentence rule (spec bug) | Gold chunk at rank 1. The raw output had a correct explanation with citations, but set `abstained: true`. The `abstained_with_citations` flag caught it. |
| 10 | loads-wind-and-snow:1, loads-wind-and-snow:2, services-design:3, products-flat-roof-rf2:1, products-flat-roof-rf1:1 | loads-wind-and-snow:1 | 36 m/s for GF-2, "as stated in passage [1]". | partly correct | generation | The table with all products was at rank 1. It picked the highest value, did not ask which product or list them, and showed the prompt's word "passage" to the customer. |

Summary: 3 correct, 3 partly correct, 2 wrong, 2 abstained wrongly. One of the wrong answers (6) is an answer without support, which is the "should have abstained" case.

Primary failed stage: 5 generation, 2 retrieval, 0 chunking, 0 citation. Secondary: generation on 4 and 6, and the fixed-sentence rule on 5 and 9. Of the 8 answerable questions, all the gold chunks were retrieved for 6; question 4 missed one of its two and question 6 missed its only one.

Completeness and faithfulness are separate measures, and Stage 2 needs to score them separately. Questions 2, 4 and 10 are faithful but incomplete, and question 3 is the opposite problem: it looks complete and contains a false claim.

Spec bug: the fixed-sentence rule came from the Stage 1 spec, not from the model. A separate `abstained` boolean let the model produce an answer and abstain at the same time, and the server then threw the answer away. That is what turned questions 5 and 9 into refusals. Question 6 is the other side of it: it needed to abstain and did not. The contract is fixed in run 2.

### Results, run 2

*Run 2, on 2026-10-30 at commit `f9d5ed9`, after the abstention contract fix. The model output is now one of two forms: `{status: answer, answer, citations}` or `{status: abstain, reason}`. Prompt v2 replaces v1. Retrieval was not touched: all 10 questions got the same 5 chunks in the same order as run 1, with the same index fingerprint, so the retrieved column is not repeated. Every difference below comes from generation. `ollama ps`: qwen3:4b-instruct 3.5 GB, 34%/66% CPU/GPU; nomic-embed-text:v1.5 335 MB, 100% GPU. Claude Code drafted the verdicts, and they need my review.*

| # | Cited | Answer (short) | Verdict | Failed stage | Change from run 1 | Notes |
|---|---|---|---|---|---|---|
| 1 | products-ground-mount-gf2:1 | At least 0.6 m. | correct | — | same | |
| 2 | pricing-commercial-offer:2 | 30 days from its date. | partly correct | generation | same | Still leaves out the recalculation. |
| 3 | corrosion-coatings:2, products-flat-roof-rf2:1 | A4, because it resists chlorides and is used in systems rated C4 and above. | partly correct | generation | better | The false claim is gone. It does not say RF-2 itself is rated C4, so the link is left to the reader. The contract fix did not target this, so count it as a side effect of the new prompt, not a result of the fix. |
| 4 | none | Fixed abstain sentence. | abstained wrongly | retrieval; secondary: generation | **worse** | Run 1 said "No, the maximum is 2.4 kN/m²". Now the chunk with 2.4 is at rank 1, and the raw reason says both that the context does not state the maximum and that it mentions 2.4. The model could not turn 2.4 < 3.0 into a "no". |
| 5 | none | Fixed abstain sentence. | abstained wrongly | generation | same verdict | Gold chunk at rank 1, which says "The company does not publish a phone number." The raw reason says the context has no information about a phone number, which is false. The answer run 1 wrote is gone, so the fixed sentence hid nothing this time. |
| 6 | none | Fixed abstain sentence. | abstained wrongly | retrieval | better | Given what it saw, abstaining was the right response, so generation did not fail here. The customer still gets no answer, and it stays a Stage 2 retrieval case. |
| 7 | none | Fixed abstain sentence. | correct | — | same | |
| 8 | none | Fixed abstain sentence. | correct | — | same | The near-miss distractors were still not retrieved, so the same limit applies as in run 1. |
| 9 | none | Fixed abstain sentence. | abstained wrongly | generation; secondary: fixed-sentence rule (spec bug) | same verdict | Gold chunk at rank 1. The raw `reason` holds the correct explanation, and the customer gets the refusal. No flag was raised. The contract moved this failure into `reason` and did not remove it. |
| 10 | loads-wind-and-snow:1, products-flat-roof-rf2:1, products-flat-roof-rf1:1 | Lists 5 of the 6 products, from 28 to 36 m/s. | partly correct | generation | better | Every value is true. It leaves out GF-1 (32 m/s) and does not ask which product. The word "passage" no longer reaches the customer. |

Summary: 3 correct, 3 partly correct, 0 wrong, 4 abstained wrongly. Run 1 was 3 correct, 3 partly correct, 2 wrong, 2 abstained wrongly.

Primary failed stage: 5 generation, 2 retrieval, 0 chunking, 0 citation. Same split as run 1.

What this shows:
- The fix did what it was for: no output can be an answer and an abstention at the same time. The grammar held even when a prompt demanded both, and a real-model test now checks that.
- It did not make the model decide better. It went from 4 abstentions to 6, and now refuses 4 of the 8 answerable questions. The false claims went away, and more correct answers went with them. A customer who gets a refusal is safer than one who gets a wrong "Yes", but this is a trade, not a clean win.
- Question 4 is a regression, and question 9 still loses a correct explanation. A correct `reason` is the same failure in a new place. Stage 2 should check `reason` text, not only the answer.
- This is 10 questions on one model at one seed. The direction may be real, but it does not measure the rate.

Not tuned for run 3, because these 10 questions are frozen and tuning on them would be overfitting. Over-abstention goes to Stage 2 with questions 4, 5 and 9 as cases.

`abstained_with_answer`: replaying run 1's raw outputs, the flag fires on questions 5 and 9 as intended, and also on question 8, which was a correct refusal. Across all 8 abstentions in the v1 traces it fires on 5. The model often fills `answer` with "the context does not say", so the flag means "read this", not "this is wrong". Under the new schema it can only fire on output that did not come through the schema.

Found while making the fix:
- Ollama writes keys alphabetically, so `status` comes last and the first key is the real decision. With the first prompt draft the model wrote `{"answer": "abstain", "citations": [1, 2], "status": "answer"}`, a refusal dressed as an answer with sources. Showing the forms in the order the model writes them fixed it. I chose this over renaming `status` so it sorts first, because both got 11 of 12 decisions right on questions outside the frozen 10.
- Citations had no upper limit. Forced to give an empty list, the model counted until `num_predict` cut the JSON off. The list now stops at 10.
- `reason` goes to the trace only, never to the customer, because it is model text with no citations behind it. Raw output was already traced for every request, and a test now pins it for abstentions.
- Prompt v1 is deleted, not kept beside v2, because it describes a contract the code no longer accepts. `PROMPT_VERSION=v1` now fails at startup instead of pairing an old prompt with the new schema. It is still in git at `a3c0e9c`.

## 2026-11-02: Stage 2, golden dataset and eval harness

*Drafted by Claude Code at my request. I have not reviewed and edited it yet.*

**What changed:**
Added the golden dataset (75 cases, now v1.2) with its design, validator and blind-check file, and the eval harness: `evals/run_evals.py`, `evals/metrics.py`, `evals/systems.py`, `evals/scoring.py` and `evals/render_results.py`, with `make eval`, `make eval-smoke` and `make results`. The README now allows AI drafting with my review as the gate, and every case records `reviewed_by`. The first baseline is in the Results table.
**How it works, in my own words:**
The harness sends each reviewed dev case to the chatbot and scores what comes back with plain code. Retrieval is scored by finding the gold sentence inside the retrieved chunks. Behaviour is scored as pass, fail, or left for the judge when code cannot tell. Numbers must appear as whole values, so "15 years" does not count as "5 years". Every run writes a manifest with the commit, dataset version, prompt, models and settings. A full dev run also updates `reports/latest.json`, a row in `evals/history.csv`, and the README table.
**How I checked it:**
Three reference systems scored exactly as predicted before any run: always abstain 7 of 52, always answer 0 of 7 out-of-scope cases, and a random retriever 9.5% hit rate. Three pipeline runs gave the same retrieval and the same refusals. The mutation check breaks the scorer, validator and harness on purpose, and the tests catch every break.
**Manual change of the day:**
I reviewed all 75 golden cases against the knowledge base.
**What I learned / what is still unclear:**
- Baseline on dev: hit rate@5 0.83, MRR 0.69, refusal accuracy 0.52, numeric fidelity 0.50. The chatbot refuses 22 of the 42 dev questions it should answer.
- The Stage 1 contract fix doubled that. The run 1 code refused 11 of the 42, and on the 31 questions the sanity runs never saw, refusals went from 8 to 16.
- A scorer needs checking against trivial systems. Counting "the judge decides" as a pass let a system that always says "Yes." score 0.38.
- A scorer also needs checking against real correct answers. The first pipeline run showed the number rule had broken "A4 fasteners" and "GF-2 would".
- Retrieval is better than the answers: the right chunk was in the top 5 for 17 of the 22 wrongly refused questions.

Still unclear: Ragas metrics and the judge are not set up, so faithfulness and the 8 cases left for the judge are not scored yet. The blind check needs a person. The thresholds in the Results table still need reviewing against this baseline in `reports/thresholds.md`.

## 2026-11-05: Stage 3, hallucinations and experiments (PR #5)

*Drafted by Claude Code at my request from the saved records. I have not reviewed and edited it yet.*

**What changed:**
A hallucination suite in CI (`tests/ai`, gates in `evals/gates.py`): out-of-scope refusals, unsupported language, false premises, numeric fidelity and a citation check. 8 experiments in `reports/experiments.md`; the adopted setup is prompt v5, top-k 8, example questions per chunk (`RETRIEVAL=questions`) and an answer check by `bespoke-minicheck:7b`, confirmed once on holdout. An English-only reply in code. Failures counted by cause in `reports/error_analysis.md`.
**How it works, in my own words:**
*(for me to write)*
**How I checked it:**
Every experiment had its predictions committed before it ran, and was compared on the 52 dev cases; the winner ran once on holdout. The suite's gates were run on the reference systems before they were trusted.
**Manual change of the day:**
*(for me to write)*
**What I learned / what is still unclear:**
- Failed dev cases went from 30 to 21 of 52 (`reports/error_analysis.md`).
- A parameter with a silent default can wreck a result: hybrid search ranked with an empty query (19 of 42 instead of 31 of 42) until it was made to raise an error without its question.
- A long run can die when three models swap on the 4 GB GPU ("timed out waiting for llama-server to start"); rerun the identical command once before changing anything.

Still unclear: chunk size was not tried.

## 2026-11-06: Stage 4, security: prompt injection and jailbreak (PR #6)

*Drafted by Claude Code at my request from the saved records. I have not reviewed and edited it yet.*

**What changed:**
42 own attacks mapped to OWASP Top 10 for LLM Applications 2025 (`evals/attacks.jsonl`, `python -m evals.attack_run`), promptfoo red teaming (96 attacks, `make redteam`) and a garak scan of the bare model. Defences: a scan of documents before indexing and an answer guard (`app/guards.py`). `reports/SECURITY_REPORT.md` with the before and after table; CI gates the committed attack run.
**How it works, in my own words:**
*(for me to write)*
**How I checked it:**
All attacks were run before and after the defences, with the dev answers checked to be unchanged. The 6 attacks promptfoo's grader failed were read by hand.
**Manual change of the day:**
*(for me to write)*
**What I learned / what is still unclear:**
- 3 of 59 attempts worked before the defences, all indirect injection through a poisoned document; 0 of 61 after.
- The bare model prints an injected line in 118 of 192 garak prompt-injection attempts: the defences carry the app, not the model.
- None of promptfoo's 6 failures was a real one when read by hand. An automatic grader needs reading too.

Still unclear: personal-data leakage needed the agent's customer data, so it moved to Stage 6.

## 2026-11-07: Stage 5, CI/CD, regression and drift (PR #8)

*Drafted by Claude Code at my request from the saved records. I have not reviewed and edited it yet.*

**What changed:**
CI checks committed runs, because the models run only on the local GPU: every run is stamped with a digest of what shapes an answer and must match its commit (`evals/freshness.py`). The smoke run (21 dev cases) is gated case by case against an accepted reference. `make nightly`, the manual "Holdout" workflow, a metric history chart, Phoenix traces, and a drift comparison of qwen3 against phi4-mini (`reports/drift.md`). The canary PR (#7) with a broken prompt.
**How it works, in my own words:**
*(for me to write)*
**How I checked it:**
The canary PR failed CI exactly as predicted. The final runs: dev answers identical to the previous run in 52/52 cases, 0 of 62 attacks worked, holdout 8 behaviour failures against 10 at the end of Stage 3.
**Manual change of the day:**
*(for me to write)*
**What I learned / what is still unclear:**
- An Ollama self-update (0.40.14 to 0.40.15) made one answer false while every gate passed, and refusal accuracy rose from 0.75 to 0.77. The Ollama version is now pinned (Findings, F7).
- phi4-mini kept every safety result but refused 39 of 42 answerable questions.
- The canary exposed two test weaknesses: a prompt with no passages passed every model-free check (F5), and the gate's unit tests used the committed run instead of a known-good one (F6).

Still unclear: the answer check's blind spot for a reversed "not" (F7) is not fixed.

## 2026-11-09: Stage 6, MCP agent with tools (PR #10)

*Drafted by Claude Code at my request from the saved records. I have not reviewed and edited it yet.*

**What changed:**
Demo company data with fake contacts (`make seed`, `data/app.db`), an MCP server with four tools over stdio (`create_lead`, `get_project_status`, `find_product`, `book_site_survey`), and the `/chat` agent. It reuses the checked RAG answer, and a booking is confirmed only by the customer's own "yes", in code the model cannot call. A reply guard stops other customers' details, prices and prompt quotes. The agent eval (35 dev cases, 22 attacks) runs on every push against a per-case reference.
**How it works, in my own words:**
*(for me to write)*
**How I checked it:**
Five experiments (A1 to A5) with committed predictions; the scorer was run on agents that do nothing, always press the first button, or have no defences before it was trusted; the owner's 10 holdout cases ran once at the end.
**Manual change of the day:**
*(for me to write. Done by me this stage: I wrote the 10 agent holdout cases.)*
**What I learned / what is still unclear:**
- Tool selection 27 of 31 and 30 of 35 cases passing on dev, but only 3 of 10 on my holdout. Tool choice held there (9/10), and the safety counts stayed at 0.
- 0 of 22 attacks worked, with 0 unconfirmed bookings and 0 leaks. The model obeyed a note planted in project P-1006 three times out of three, until notes that address the assistant were withheld.
- On a 4B model, a prompt sentence that fixes one case can break another; code checks broke nothing.

Still unclear: why most holdout failures are on "the reply includes the expected words".

## 2026-11-11: Stage 7, UI, Playwright and a Docker demo (PR #13)

*Drafted by Claude Code at my request from the saved records. I have not reviewed and edited it yet.*

**What changed:**
A Streamlit chat window on `/chat` with the cited sources and the booking confirmation (`ui/app.py`), 9 Playwright browser tests against a stand-in API in CI, and a Docker demo (`make docker-up`) that uses the desktop Ollama the evals ran on. Agent experiments A6 and A9 kept, A7 and A8 measured and not kept. The README got a Demo section. The live link is postponed; its Telegram bot is parked on `later/telegram-bot`.
**How it works, in my own words:**
*(for me to write)*
**How I checked it:**
The browser tests were each broken on purpose 4 ways and caught all 4. The Docker demo gave 21/21 smoke answers word for word the same as the committed run. Every agent experiment had committed predictions. The end-of-stage runs: dev answers identical in 52/52, 0 of 62 RAG attacks and 0 of 22 agent attacks worked, the RAG holdout identical in 23/23.
**Manual change of the day:**
*(for me to write. Done by me this stage: chose local Docker over AWS after the cost comparison, installed Docker Desktop and enabled Virtual Machine Platform, found both chat-window bugs, and checked holdout case h008 by hand.)*
**What I learned / what is still unclear:**
- Ollama inside Docker, at the same version with the same models, gave 20 of 21 smoke answers word for word and refused g032; the cause was not measured. So the demo uses the desktop Ollama.
- A prompt fix on a 4B model moved failures around: v4 cost a018, v5 cost a013 and a014. The code fix A9 broke nothing.
- The agent eval's stand-in knowledge base answers everything, so it passed a037 and failed holdout h008, the opposite of real use (F11).
- Agent holdout: 2 of 10 against 3 of 10 at the end of Stage 6; the one lost case, h008, passes in real use.

Still unclear: "tell me about the company" is refused by the real knowledge base, because one garbled sentence makes the answer check throw away the whole answer.

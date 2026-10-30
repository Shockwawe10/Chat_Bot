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

## Stage 1 sanity questions (frozen before the first run)

Drafted by Claude from data/kb; reviewed and frozen by me on 2026-10-30,
before any pipeline output was seen.

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

*Run on 2026-10-30 at commit `a3c0e9c`, with no changes to the pipeline or prompt. The verdicts and failed stages are Claude Code's draft and need my review. Chunk ids are shortened to `doc:index`; the full ids and raw model outputs are in `runs/traces/`.*

| # | Retrieved chunk ids (rank order) | Cited | Answer (short) | Verdict | Failed stage | Notes |
|---|---|---|---|---|---|---|
| 1 | products-ground-mount-gf2:1, products-ground-mount-gf2:0, products-ground-mount-gf2:2, products-ground-mount-gf1:1, products-ground-mount-gf1:2 | products-ground-mount-gf2:1 | At least 0.6 m. | correct | — | Gold chunk at rank 1. |
| 2 | pricing-commercial-offer:2, process-cooperation-stages:2, services-supply:2, process-quote-requirements:4, pricing-commercial-offer:1 | pricing-commercial-offer:2 | 30 days from its date. | partly correct | generation | Gold chunk at rank 1. The main fact is right; it left out the recalculation. |
| 3 | corrosion-coatings:2, products-overview:2, products-flat-roof-rf2:2, products-flat-roof-rf2:0, products-flat-roof-rf2:1 | corrosion-coatings:2, products-flat-roof-rf2:1 | A4, because it resists chlorides and suits systems rated "up to C4". | partly correct | generation | Both gold chunks retrieved and cited. The source says C4 and above, so "up to C4" gets the rule backwards. |
| 4 | products-ground-mount-gf1:1, products-ground-mount-gf1:3, products-ground-mount-gf2:2, products-ground-mount-gf1:2, products-ground-mount-gf1:0 | products-ground-mount-gf1:1 | No, the maximum for GF-1 is 2.4 kN/m². | partly correct | retrieval | The "When a site exceeds the maximum" chunk was not retrieved, so the reinforced option was never in the context. The GF-2 limit of 3.5 kN/m² was retrieved but not used. |
| 5 | company-contacts:0, company-contacts:1, company-contacts:2, warranty:3, process-quote-requirements:1 | none | Fixed abstain sentence. | abstained wrongly | generation | Gold chunk at rank 1. The raw output said "The company does not publish a phone number." but set `abstained: true`, so the fixed sentence replaced it. No flag was raised. |
| 6 | process-quote-requirements:1, company-overview:3, company-overview:1, products-flat-roof-rf2:2, services-installation:2 | process-quote-requirements:1, company-overview:1, products-flat-roof-rf2:2 | "Yes", with RF-2 as the reason. | wrong | retrieval | The 100 kWp rule was not in the 5 chunks, though three other chunks of the right documents were. Generation failed too: with no rule in the context it invented a reason, cited chunks that do not support it, and did not abstain. No flag was raised. |
| 7 | company-overview:0, company-overview:3, company-overview:1, company-overview:2, services-overview:0 | none | Fixed abstain sentence. | correct | — | |
| 8 | products-ground-mount-gf1:2, products-ground-mount-gf1:1, products-ground-mount-gf1:0, products-ground-mount-gf2:3, products-overview:2 | none | Fixed abstain sentence. | correct | — | The torque distractors were not retrieved, so this was an easier test than it was designed to be. |
| 9 | products-ground-mount-gf2:3, products-ground-mount-gf1:2, products-overview:2, corrosion-coatings:0, products-ground-mount-gf2:1 | none | Fixed abstain sentence. | abstained wrongly | generation | Gold chunk at rank 1. The raw output had a correct explanation with citations, but set `abstained: true`. The `abstained_with_citations` flag caught it. |
| 10 | loads-wind-and-snow:1, loads-wind-and-snow:2, services-design:3, products-flat-roof-rf2:1, products-flat-roof-rf1:1 | loads-wind-and-snow:1 | 36 m/s for GF-2, "as stated in passage [1]". | partly correct | generation | The table with all products was at rank 1. It picked the highest value, did not ask which product or list them, and showed the prompt's word "passage" to the customer. |

Summary: 3 correct, 4 partly correct, 1 wrong, 2 abstained wrongly, 0 should have abstained.

Failed stage: 5 generation, 2 retrieval, 0 chunking, 0 citation. Of the 8 answerable questions, all the gold chunks were retrieved for 6; question 4 missed one of its two and question 6 missed its only one.

Pattern to look at in Stage 2: the `abstained` field is unreliable. The two questions it broke (5 and 9) had the right answer in the raw output, and the fixed sentence hid it. The one wrong answer (6) needed `abstained: true` and did not get it.

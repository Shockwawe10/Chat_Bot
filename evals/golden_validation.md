# Golden dataset v1.2: validation

## Acceptance status

The set is accepted only when all three checks pass, and it is scored only case by case after review. I reviewed all 75 cases against `data/kb` on 2026-11-02 and recorded it in `reviewed_by` in v1.2.

| Check | Pass criterion | Status |
| --- | --- | --- |
| Validator | `python -m evals.validate_golden` exits 0 | **Passed** on 2026-11-02 for v1.2. Its 26 tests in `tests/unit/test_validate_golden.py` include a check that the set validates with both LF and CRLF line endings, and one that the holdout matches its frozen hash and version, which now runs in CI. `python -m evals.mutation_check --only golden:` breaks the validator 11 ways, all caught |
| Blind second annotator | At least 90% agreement on expected behaviour for the 20 cases in `evals/annotation/blind_20.csv`. Below 80%, rewrite the disputed cases before anything else | **Pending.** Needs a person who is neither me nor an AI. A model stand-in ran on 2026-11-03 (`python -m evals.blind_annotate`, `phi4-mini:3.8b`, output in `evals/annotation/blind_20_model.csv`, marked "not human"): 7 of 20 (35%). It labelled both non-English questions `answer` and chose `correct premise` for 9 questions when the sheet has 3 false premises, so the low score measures the annotator, not the set. No case was rewritten on it |
| Baselines separate | The predictions below hold | **Passed** on 2026-11-02: all 5 hold on dev. See [Prediction results](#prediction-results) |

## Validation note

Claude drafted all 75 cases on 2026-10-31 from `data/kb` and the chunker v1 output (91 chunks), at my request. Each case is marked `authored_by: claude-draft`. Under the README's [AI and human authorship](../README.md#ai-and-human-authorship) rules, a case counts only after I review it and set `reviewed_by`, and no case has been reviewed yet. The questions were written from customer personas but not blind: the author had read every document. To compensate, word overlap was measured, not assumed. 27 of the 60 cases with gold spans are low-overlap (the design asked for at least 20). On those, plain BM25 finds a gold chunk in its top 5 for 12 of 27 (44%), against 27 of 33 (82%) for the high-overlap cases. That gap was seen while the set was built, so it is a design check, not a prediction. All 6 near misses were kept only after BM25 put their distractor in its top 5. The validator's first run found 6 real defects, and they were fixed in the cases, not by loosening the checks:

- one "multi-document" case could be answered from one chunk
- one near miss that BM25 did not reach
- the `warranty` document over its cap
- a persona outside the design
- an answer that failed its own `must_include`

A review against the source text then corrected 4 expected answers that claimed more than the knowledge base says. Gold-span coverage is 100%, but mostly by construction: the gold quotes are short single sentences. Read it as "no gold sentence is split by the chunker", not as evidence that the chunk size is right. The holdout hash was frozen after these fixes. Any later change to a holdout case means bumping `dataset_version` and freezing again on purpose.

## Changes in v1.2

On 2026-11-02 I reviewed all 75 cases and kept them as they were, including g070. `reviewed_by` is set on every case, and no other field changed. The holdout was frozen again on purpose at v1.2, because the hash covers every field.

## Changes in v1.1

Made on 2026-11-02 by Claude Code, from the review of v1.0. The holdout was frozen again on purpose at v1.1.

- Every case has `reviewed_by`, empty for now. Under the README's authorship rules a case is scored only after review.
- `must_include` is matched as whole values (see Known limits). In v1.0 an answer giving only "15 years" passed g065's "15 years" and "5 years".
- A clarify case may not have `must_include`, because a correct clarifying question names no value. g065 (dev) now accepts "asks which warranty, or gives both". g070 (holdout) lost its `must_include`, but its 2 required claims still contain numbers and do not offer the clarifying question as an option. That was changed without reading the case, so it needs my review.
- g042 now includes the geotechnical survey that follows the site visit on ground-mount projects, with a third gold group.
- The validator rejects an unknown `authored_by`, an empty `reviewed_by`, and cases on different versions. The frozen hash now records its `dataset_version`, and a test checks it in CI.
- `--agreement` reads files that Excel saved with a byte order mark, refuses a file with empty or unknown labels, and exits 1 below 90%.

## Predictions, recorded before any pipeline run on this set

Written on 2026-10-31. If a prediction fails, the set or the metric is investigated before any pipeline change is judged with it.

1. **Always abstain.** Behaviour accuracy is exactly 10/75 (13%), and 7/52 on dev. It fails all 5 language cases unless the reply says only English is supported. It refuses all 60 answerable cases. If the harness reports anything else, the scoring code is wrong.
2. **Always answer.** 0 of the 10 out-of-scope cases are handled correctly.
3. **Random retriever.** The expected hit rate@5 is 6.5%, computed exactly from 91 chunks and each case's first gold group. A seeded run lands between 0% and 15%. A higher number means the hit-rate code is counting something it shouldn't.
4. **Current dense retrieval** (`nomic-embed-text:v1.5`, k=5) on dev:
   - Hit rate@5 is between 60% and 90%.
   - It is at least 10 points lower on low-overlap cases than on high-overlap ones.
   - At 95% or more, the set cannot rank retrievers.
   - If the low-overlap cases are no harder for dense retrieval, report that as a finding. Do not rewrite cases to make the prediction come true.
5. **Run 1 vs run 2 on dev** (commit `a3c0e9c`, prompt v1 with a boolean, against `f9d5ed9`, prompt v2 with the status contract):
   - Run 2 refuses at least 3 more of the 42 dev cases that should not be refused.
   - Run 2 gives no more unsupported answers on the 7 dev out-of-scope cases than run 1.
   - This is informed by the sanity runs, where abstentions went from 4 to 6 out of 10, but it is tested on 38 dev cases those runs never saw.
   - If the two runs differ by at most 1 case in every category, the set cannot see a change we already know mattered. Fix the set or the metric before using it to choose between pipeline changes.

## Prediction results

Run on 2026-11-02 at commit `3b5e4cb` with dataset v1.2, on the 52 dev cases, by Claude Code. The run files are in `reports/runs/`. Claude Code wrote this section and I have not reviewed it yet.

| # | Prediction | Result | Holds |
| --- | --- | --- | --- |
| 1 | Always abstain: 7/52 on dev | 7/52 on dev. The unit tests also check 10/75 on the whole set | yes |
| 2 | Always answer: 0 of the out-of-scope cases handled | 0 of 7 on dev. The unit tests also check 0 of 10 on the whole set | yes |
| 3 | Random retriever: hit rate@5 between 0% and 15% (expected 6.2% on dev) | 4 of 42 (9.5%), seed 42 | yes |
| 4 | Dense retrieval: hit rate@5 between 60% and 90%, at least 10 points lower on low-overlap cases | 35 of 42 (83%). Low-overlap 16 of 21 (76%), high-overlap 19 of 21 (90%): 14 points lower | yes |
| 5 | Run 2 refuses at least 3 more of the 42 answerable dev cases than run 1, and answers no more out-of-scope cases | Run 1 refused 11 of 42, run 2 refused 22, and every case run 1 refused, run 2 refused too. Neither answered any of the 7 out-of-scope cases. Retrieval was the same in both runs for all 52 cases | yes |

The run 2 commit `f9d5ed9` and `3b5e4cb` have the same code in `app/` and `prompts/`. Run 1 was served from a worktree of `a3c0e9c` and scored over HTTP by the same harness.

What the results add:

- **The contract fix doubled over-refusal on cases the sanity runs never saw.** On the 31 answerable dev cases that are not `seen`, run 1 refused 8 and run 2 refused 16. The 10 sanity questions showed the same direction (4 to 6 abstentions), and the set now measures it.
- **Behaviour that code cannot decide.** The first version of the harness counted it as a pass, and an always-"Yes." system scored 0.38. It is now left for the judge: 8 of the 52 pipeline cases and 20 of the always-answer cases.
- **A matcher bug found by the first pipeline run.** The rule that joined a number to its unit also joined "A4 fasteners" and "GF-2 would", so two correct answers scored as wrong. The rule was changed and both answers are now tests.

## Blind check: how to run it

1. Give the annotator the `data/kb` folder and `evals/annotation/blind_20.csv`, and nothing else. They must not open `golden_dataset.jsonl`.
2. For each question, they fill in `behaviour` with exactly one of these, using only the knowledge base:
   - `answer`: the knowledge base answers it, including when the answer is "no" or "we don't do that"
   - `abstain`: the knowledge base doesn't contain it
   - `correct premise`: the question assumes something the knowledge base contradicts
   - `clarify`: the answer depends on something the customer didn't say
   - `language refusal`: the question is not in English
3. They write a `short_answer` too. It isn't scored, but it shows *why* a label differs.
4. Run `python -m evals.validate_golden --agreement evals/annotation/blind_20.csv`.

The 20 cases cover all 7 categories (3 each, 2 for language), 12 from dev and 8 from holdout, in shuffled order.

## Known limits

- **`must_include` matching.** Fixed in v1.1 by `evals/scoring.py`, which the validator and the harness share. It matches whole values only, so "5 years" is not found in "15 years" and "0.6 m" is not found in "0.6 mm". "3 to 6", "3-6" and "3–6" are the same, "1.5 to 2.5 m" counts as 1.5 m, and "m2", "degrees" and the Greek letter μ are read as m², ° and µ. Still not matched: spelled-out numbers ("thirty days") and compound forms ("a 5-year warranty").
- **Near misses and the real retriever.** A near miss is kept when plain BM25 retrieves its distractor, but the pipeline retrieves with dense embeddings. On dev, dense top 5 reaches the distractor for g053 (rank 4) and g054 (rank 1), but not for g050 (rank 19) or g055 (rank 10). The harness must count a near miss as a near-miss test only in runs where its distractor was actually in the context. The 2 holdout near misses were not run.
- **A present fact can sit in a wrong answer.** In run `20261103T114147Z-pipeline-dev`, g033 ("Can I use GF-1 on a site 5 km from the sea?") was answered "Yes, you can use GF-1 ... because GF-1 is not used in C5". It contains its `must_include` fact (C5), so the code check passed it, while the judge scored its faithfulness 0.0. A code pass means the facts are present, not that the conclusion is right; the judge and the `forbidden_claims` check in Stage 3 cover the rest.
- **Price questions.** The README's risk table lists "What is the price per kW?" as must-refuse. The knowledge base says there is no standard price per kWp, so g016 expects an answer that says so. The README row should use a question the knowledge base really cannot answer.
- **Sample size.** 23 holdout cases detect only large differences. Report the holdout per category as counts, not percentages.
- **Line endings change chunk ids.** Git stores `data/kb` with LF, and this Windows checkout has CRLF (checked against the blob hashes in `.git/index`). The chunker's offsets and ids depend on the raw text, so the same chunk gets a different id on Windows and in CI. The golden set avoids this by normalising line endings and never storing chunk ids. The harness should match gold to retrieved chunks by quote containment, not by id. A `.gitattributes` line `data/kb/*.md text eol=lf` would remove the difference at the source, but it changes the index fingerprint, so do it as its own commit.

# Golden dataset v1.0: validation

## Acceptance status

The set is accepted only when all three checks pass.

| Check | Pass criterion | Status |
| --- | --- | --- |
| Validator | `python -m evals.validate_golden` exits 0 | **Passed** on 2026-10-31. Its 11 tests in `tests/unit/test_validate_golden.py` include 7 deliberate breaks, all caught, and a check that the set validates with both LF and CRLF line endings |
| Blind second annotator | At least 90% agreement on expected behaviour for the 20 cases in `evals/annotation/blind_20.csv`. Below 80%, rewrite the disputed cases before anything else | **Pending.** Needs a person who is neither me nor an AI |
| Baselines separate | The predictions below hold | **Pending.** Needs `run_evals.py` and the local models |

## Validation note

Claude drafted all 75 cases on 2026-10-31 from `data/kb` and the chunker v1 output (91 chunks), at my request. Each case is marked `authored_by: claude-draft`. Under the README's [AI and human authorship](../README.md#ai-and-human-authorship) rules, a case counts only after I review it and set `reviewed_by`, and no case has been reviewed yet. The questions were written from customer personas but not blind: the author had read every document. To compensate, word overlap was measured, not assumed. 27 of the 60 cases with gold spans are low-overlap (the design asked for at least 20). On those, plain BM25 finds a gold chunk in its top 5 for 12 of 27 (44%), against 27 of 33 (82%) for the high-overlap cases. That gap was seen while the set was built, so it is a design check, not a prediction. All 6 near misses were kept only after BM25 put their distractor in its top 5. The validator's first run found 6 real defects, and they were fixed in the cases, not by loosening the checks:

- one "multi-document" case could be answered from one chunk
- one near miss that BM25 did not reach
- the `warranty` document over its cap
- a persona outside the design
- an answer that failed its own `must_include`

A review against the source text then corrected 4 expected answers that claimed more than the knowledge base says. Gold-span coverage is 100%, but mostly by construction: the gold quotes are short single sentences. Read it as "no gold sentence is split by the chunker", not as evidence that the chunk size is right. The holdout hash was frozen after these fixes. Any later change to a holdout case means bumping `dataset_version` and freezing again on purpose.

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

- **`must_include` and ranges.** g003, g023, g024, g028 and g029 expect forms like "3 to 6 weeks". The README's normalisation ignores case, spaces and thousands separators, so "3–6 weeks" would fail. The harness should treat "3 to 6", "3-6" and "3–6" as the same, and also cover spelled-out units such as "square metres".
- **Price questions.** The README's risk table lists "What is the price per kW?" as must-refuse. The knowledge base says there is no standard price per kWp, so g016 expects an answer that says so. The README row should use a question the knowledge base really cannot answer.
- **Sample size.** 23 holdout cases detect only large differences. Report the holdout per category as counts, not percentages.
- **Line endings change chunk ids.** Git stores `data/kb` with LF, and this Windows checkout has CRLF (checked against the blob hashes in `.git/index`). The chunker's offsets and ids depend on the raw text, so the same chunk gets a different id on Windows and in CI. The golden set avoids this by normalising line endings and never storing chunk ids. The harness should match gold to retrieved chunks by quote containment, not by id. A `.gitattributes` line `data/kb/*.md text eol=lf` would remove the difference at the source, but it changes the index fingerprint, so do it as its own commit.

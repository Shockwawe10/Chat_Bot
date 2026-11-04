# Experiments

Each experiment changes one thing, runs on the 52 dev cases with `python -m evals.run_evals --judge --experiment <name>`, and is compared with the baseline case by case. Its predictions and decision rule are written and committed before the run. Holdout cases are never used to choose, and the 8 exposed holdout cases (`evals/exposure.py`) can never justify a change.

Baseline: `20261103T114147Z-pipeline-dev` (commit `7719015`, prompt v2, top-k 5). Failures by cause are in `reports/error_analysis.md`.

## Experiment 1: prompt v3, what counts as an answer

**Written on 2026-11-04, before the run.**

**Why.** 14 of the 30 baseline failures are refusals with the gold chunk in the context (`reports/error_analysis.md`). Prompt v2 tells the model to answer only "if the context contains the answer", and the model reads that as "states it word for word". Every dev false-premise case fails, 5 of them this way.

**Change.** `prompts/answer_v3.txt` adds one section that says when the context contains the answer: a stated fact; a statement that the company does not do, offer or publish the thing; a number compared with a stated limit; a wrong assumption the passages contradict, which is corrected; or an answer that depends on something unsaid, given per case. It ends with "Abstain only when no passage states, rules out or limits what the customer asked." The rules, the JSON forms and the contract are unchanged. Everything else is fixed: code, index, top-k 5, model, seed and judge.

**Predictions.**

1. At least 7 of the 14 refusals with the gold in the context become answers that pass.
2. Over-refusal falls from 22/42 to at most 15/42.
3. Out-of-scope answered stays 0/7.
4. Faithfulness on answered cases stays at or above 0.90, reported with the number of answered cases.

**Decision rule.** v3 is adopted only if all of these hold:

- out-of-scope answered is 0/7 (the zero-tolerance gate in `reports/thresholds.md`);
- over-refusal is lower than 22/42;
- more cases pass than in the baseline (22/52, counting the 8 read cases by the same reading rules);
- every case that passes in the baseline and fails with v3 is listed and read, and none of them answers with a claim the knowledge base contradicts.

A failed prediction is reported as it is, even when v3 is adopted.

**Result: not adopted.** Run `20261104T095349Z-pipeline-dev-prompt-v3`, 2026-11-04. Retrieval was identical to the baseline for all 52 cases, so every difference comes from the prompt. The 12 cases that code cannot decide were read with the same rules as the baseline: a pass needs every required claim, and any false claim fails the case.

| | Baseline (v2) | v3 |
| --- | --- | --- |
| Cases that pass | 22/52 | 21/52 |
| Over-refusal | 22/42 | 19/42 |
| Out-of-scope answered | 0/7 | 0/7 |
| Numeric fidelity | 11/22 | 8/22 |
| Faithfulness (judge) | 0.95 on 20 answered | 0.93 on 23 answered |

Predictions:

1. **Failed.** Of the 14 refusals with the gold in the context, 10 are still refused. 4 are now answered (g013, g015, g016, g020), and only g020 passes; the other three are true but leave out a required claim.
2. **Failed.** Over-refusal is 19/42, not 15/42 or less.
3. **Held.** Out-of-scope answered stays 0/7.
4. **Held on the number, not in substance.** Faithfulness is 0.93, but the judge scored two wrong answers as fully supported (below).

Decision rule: out-of-scope 0/7 holds and over-refusal is lower, but fewer cases pass (21 against 22) and one regression makes a claim the knowledge base contradicts, so two of the four conditions fail.

What changed, case by case:

- **Better:** g020 now answers correctly. g064 now says the answer depends on the product and gives all six values. g013, g015 and g016 are answered instead of refused, but each leaves out one required claim.
- **Worse:** g006 now opens with "You deal with a different contact each time", which the knowledge base contradicts. g035, a correct answer in the baseline (1,000 m²), is now refused. g028 shrank to a bare "Yes", which loses its required fact.
- **A worse kind of failure:** g032 was refused in the baseline and now says "Yes, the company can build a 50 kWp system". The 100 kWp rule was never retrieved, so this is an invented answer. g033 still says "Yes" to GF-1 near the sea, now without the facts.
- **Unchanged:** all 6 dev false-premise cases still fail, 5 of them still refused with the gold in the context.

What it teaches:

- **"Compare them and answer yes or no" produced bare and invented yes/no answers** (g028, g032, g033). The model took it as permission to answer yes or no without the fact behind it, and without the limit when the limit was not retrieved.
- **The false-premise instruction had no effect.** The model still refuses rather than correcting the question.
- **The judge has a blind spot for short yes/no sentences.** `bespoke-minicheck:7b` scored "Yes, you can use GF-1 on a site 5 km from the sea." (g033) and the 50 kWp "Yes" (g032) as supported, though in calibration it rejected the 50 kWp answer when it was longer. A one-word conclusion gives it almost nothing to check. Faithfulness must not decide between prompts until the judge is checked on short yes/no answers too.
- **Over-refusal is not one problem.** The 10 refusals v3 did not move include all 5 false-premise cases and both numeric table lookups (g024, g025). They need a different fix than the stated-absence cases v3 did move.

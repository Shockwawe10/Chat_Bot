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

**Result.** Not run yet.

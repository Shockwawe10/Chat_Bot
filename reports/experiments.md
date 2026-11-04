# Experiments

Each experiment changes one thing, runs on the 52 dev cases with `python -m evals.run_evals --judge --experiment <name>`, and is compared with the baseline case by case. Its predictions and decision rule are written and committed before the run. Holdout cases are never used to choose, and the 8 exposed holdout cases (`evals/exposure.py`) can never justify a change.

Baseline: `20261103T114147Z-pipeline-dev` (commit `7719015`, prompt v2, top-k 5). Failures by cause are in `reports/error_analysis.md`.

## Prompt loop spec (prompt-engineer skill, from 2026-11-04)

Agreed before any round runs, and frozen for the whole loop. If a criterion turns out to be broken, it is fixed in the open and every earlier round is rescored with `--rescore`.

**What goes in and out.** Five retrieved passages (heading and text) and the customer's question go in. Out comes the JSON contract: an answer with citations, or an abstention with a reason. The contract, the model, retrieval and the judge do not change during the loop.

**What a bad output looks like** (from the baseline and experiment 1): a refusal when the answer was in the passages; a bare "Yes" or "No" with no fact behind it; a "Yes" the passages do not support; a sentence the passages contradict; an answer to a question the knowledge base cannot answer.

**Criteria, each pass or fail per dev case:**

1. **Out of scope stays refused.** Each of the 7 dev out-of-scope cases is refused. Zero tolerance.
2. **Answerable means answered.** A case that should be answered is not refused (42 cases).
3. **Complete.** Every required claim is present: `must_include` by code, the rest by reading, with the same rules as the baseline.
4. **True.** No claim the knowledge base contradicts. Every answer that changed is read.
5. **Grounded.** No bare yes or no: an answer that settles a yes/no question also states the fact from a passage behind it.

The 3 language cases are left out of the loop. A separate experiment handles them in code.

**Test set.** The 52 reviewed dev cases are the train split. The skill's holdout is the 15 unexposed holdout cases, run once with the winner at the end of the stage.

**Target.** Over-refusal at or below 11/42, the first milestone in `reports/thresholds.md`, with more than 22 dev cases passing and out-of-scope still 0/7.

**Stop when** the target is reached, two rounds in a row do not beat the best version, or after 4 rounds. Every round changes one thing and is written here before it runs. Faithfulness from the judge is reported but does not pick a winner, because it scored short wrong "Yes" answers as supported in experiment 1.

**Starting point.** Prompt v2, the best version so far (22/52 pass). Prompt v3 is not built on.

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

## Experiment 2 (prompt loop, round 1): prompt v4, boundary examples

**Written on 2026-11-04, before the run.** Built on v2, not v3.

**Failure it targets.** The model refuses questions the passages answer: 14 baseline refusals had the gold in the context, and all 6 dev false-premise cases fail. Experiment 1 described the boundary in words and the model read it inconsistently. The skill's technique table gives, for "refuses what it should answer", an explicit boundary section with should-answer and should-refuse examples.

**Change.** `prompts/answer_v4.txt` is v2 with one added section: six invented examples from a bicycle shop, with their own four passages. Five should be answered (a stated fact, something the shop does not do, a number compared with a limit, a wrong assumption corrected, an answer that depends on the part) and one should be refused. Every example answer states the fact it relies on and cites its passage; none is a bare yes or no. No example shares a fact with the knowledge base or with any dev or holdout case. Nothing else changes.

**Cases it should flip.** The 14 refusals with the gold in the context, especially the 5 false-premise ones (g056, g057, g059, g060, g062), the stated absences (g015, g016, g020) and the table lookups (g024, g025).

**Predictions.**

1. Over-refusal falls from 22/42 to at most 16/42.
2. At least 3 of the 5 false-premise refusals with the gold in the context are answered.
3. Out-of-scope answered stays 0/7.
4. No answer is a bare yes or no (criterion 5).
5. More than 22 dev cases pass.

**Decision rule.** The spec's criteria: v4 becomes the best version only if out-of-scope is 0/7, over-refusal is lower than 22/42, more than 22 cases pass, no changed answer makes a claim the knowledge base contradicts, and no answer is a bare yes or no.

**Result.** Not run yet.

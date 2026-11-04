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

**Result: not adopted, by one condition.** Run `20261104T101804Z-pipeline-dev-prompt-v4`, 2026-11-04. Retrieval was identical to the baseline for all 52 cases. The 15 cases that code cannot decide were read with the baseline rules.

| | Baseline (v2) | v4 |
| --- | --- | --- |
| Cases that pass | 22/52 | 27/52 |
| Over-refusal | 22/42 | 12/42 |
| Out-of-scope answered | 0/7 | 0/7 |
| Numeric fidelity | 11/22 | 14/22 |
| Faithfulness (judge) | 0.95 on 20 answered | 0.78 on 30 answered |

Predictions:

1. **Held.** Over-refusal fell to 12/42, below the predicted 16/42.
2. **Failed.** 2 of the 5 false-premise refusals with the gold in the context are answered (g060, g062), not 3. Both leave out a required claim; g056, g057 and g059 are still refused.
3. **Held.** Out-of-scope answered stays 0/7.
4. **Held.** No answer is a bare yes or no. Every yes or no is followed by a fact, though in g017 and g032 the fact does not support it.
5. **Held.** 27 cases pass, against 22.

Decision rule: four conditions hold, but changed answers make claims the knowledge base contradicts, so v4 does not become the best version:

- **g017** "Can you just email me a ballpark figure?" is answered "Yes", where the knowledge base says prices are not given by email before an offer.
- **g032** answers "Yes" to a 50 kWp project. The 100 kWp minimum was not retrieved, so the "Yes" is invented.
- **g066** says the systems are rated "for maximum categories from C1 to C5". No system is rated C1 or C2, and it does not give the category per system.
- **g033** still says "Yes" to GF-1 near the sea, as it did in the baseline.

What changed, case by case:

- **Newly passing (7):** g020, g024 and g031 by code; g064 and g067 now give the value per product; g013, g060 and g062 are answered but each leaves out one required claim, so they do not pass. (The count of 27 is 19 code passes and 8 read passes.)
- **Still refused with the gold in the context:** the false premises g056, g057 and g059, and the table lookup g025.
- **Lost:** nothing that passed in the baseline fails now, apart from g033, which was already counted as a failure.

**Faithfulness here is mostly a measurement artifact.** v4 answers open with a separate "Yes." or "No." sentence, and the judge checks each sentence alone. A lone "Yes." has nothing to check, so correct answers scored 0.5 (g010, g014, g028, g039). The judge also scored g060 0.0, which needs "March 2026 plus 5 years". It did catch the wrong answers g032 and g033 at 0.0. The judge stays out of the decision, as the spec says.

**What it teaches.** The examples work: refusals halved and nothing that passed broke. But every example answer opens with "No." or "Yes", and the model copies the opening before it has a fact for it: g017 and g032 start with "Yes." and then add an unrelated sentence. The next round should make the fact come first and the yes or no follow from it.

## Experiment 3 (prompt loop, round 2): prompt v5, fact first

**Written on 2026-11-04, before the run.** Built on v4. The best version is still v2 (22/52), because v4 was not adopted.

**Failure it targets.** Yes or no answers with no passage behind them. In v4 the model copied the examples' "Yes." and "No." openings before it had a fact: g017 says "Yes" to a ballpark price by email, g032 says "Yes" to a 50 kWp project, and g033 says "Yes" to GF-1 near the sea. g066 makes a false claim too ("C1 to C5"), but it is not a yes/no question, so this round may not reach it.

**Change.** One technique, grounding. `prompts/answer_v5.txt` is v4 with the four example answers that opened with "No." or "Not always." rewritten so the fact comes first and the conclusion follows from it, and one added rule: "State the fact from the passage first. Give a yes or no only when a passage decides it; if no passage decides it, abstain." The passages, questions, citations and the abstain example are unchanged, and so is everything else.

**Predictions.**

1. Out-of-scope answered stays 0/7.
2. At least 2 of g017, g032 and g033 no longer give a yes or no the passages do not support (they state the right fact or abstain).
3. No answer opens with a separate "Yes." or "No." sentence.
4. Over-refusal stays at or below 12/42. The new "abstain" clause could push it up; if it does, that is reported as it is.
5. At least 27 dev cases pass, and none of v4's newly passing cases (g020, g024, g031, g064, g067) is lost.

**Decision rule.** The same as round 1: v5 becomes the best version only if out-of-scope is 0/7, over-refusal is lower than 22/42, more than 22 cases pass, no changed answer makes a claim the knowledge base contradicts, and no answer is a bare yes or no. Changed answers are read against both the baseline and v4.

**Result: not adopted, by the same condition as v4.** Run `20261104T102633Z-pipeline-dev-prompt-v5`, 2026-11-04. Retrieval was identical to the baseline for all 52 cases. The 17 cases that code cannot decide were read with the baseline rules. An answer identical to v4's keeps v4's reading, and g016's answer is word for word the one experiment 1 read as incomplete.

| | Baseline (v2) | v4 | v5 |
| --- | --- | --- | --- |
| Cases that pass | 22/52 | 27/52 | 25/52 |
| Over-refusal | 22/42 | 12/42 | 11/42 |
| Out-of-scope answered | 0/7 | 0/7 | 0/7 |
| Numeric fidelity | 11/22 | 14/22 | 12/22 |
| Answers opening with a separate yes or no | 0 | 11 | 0 |
| Faithfulness (judge) | 0.95 on 20 answered | 0.78 on 30 answered | 0.94 on 31 answered |

The 25 passes are 17 by code and 8 by reading (g006, g007, g010, g014, g020, g064, g065, g067). g062 is the closest call. It now says the price cannot be held for two months but still leaves out that the offer is recalculated after 30 days, so it stays incomplete as in v4. Counting it would give 26.

Predictions:

1. **Held.** Out-of-scope answered stays 0/7.
2. **Held, narrowly.** g033 now gives the right fact and the right conclusion: GF-1 is not used in C5, within 10 km of the sea. g017 drops the "Yes" but still does not say that prices are not given by email. g032 drops the "Yes" but still suggests a flat-roof system can be designed, without the 100 kWp minimum, which was not retrieved.
3. **Held.** No answer opens with a separate yes or no sentence (11 did in v4).
4. **Held.** Over-refusal is 11/42.
5. **Failed.** 25 cases pass, not 27, and two of v4's newly passing cases are lost: g024 is refused again, and g031 now reaches the wrong conclusion.

Decision rule: out-of-scope, over-refusal, the pass count and the bare yes/no condition hold. The "true" condition fails:

- **g031** (snow load 3.0 kN/m² on GF-1) now ends "so GF-1 can handle it". The answer itself quotes the 2.4 kN/m² maximum, which 3.0 exceeds. The fact-first wording led the model to quote the wrong passage (GF-2's 3.5 kN/m²) and reason from it.
- **g066** still says the systems are rated "from C1 to C5", unchanged from v4.

What changed against v4:

- **Fixed:** g033.
- **Lost:** g003 dropped "3 to 6 weeks" and describes what the design contains instead; g024 is refused; g031 is wrong.
- **Answered instead of refused, but incomplete:** g016 (no standard price per kWp, but not how the price is set) and g056 (thickness alone does not decide, but not the C4/C5 ratings). Both are true.
- **Still refused with the gold in the context:** g025, g057 and g059.

**Faithfulness.** The lone "Yes." artifact is gone: g010, g014, g028 and g039 now score 1.0. The judge caught g031 (0.0) but scored g032's suggestion 1.0. It is reported, not used to decide.

**The loop stops here.** Neither round beat the best version, v2, so the stop rule written before round 1 ends the loop after two rounds. On the numbers, v5 reaches the target: over-refusal 11/42, more than 22 passing and out-of-scope 0/7. But two answers make a claim the knowledge base contradicts, and the spec does not let a version with false claims become the best one.

**What it teaches.**

- **Grounding fixed the form, not the reasoning.** Bare and leading yes/no answers disappeared, and the judge artifact went with them. But when the right passage is not the one the model quotes (g031), or is not retrieved at all (g032, g066), a fact-first answer still reaches a wrong conclusion. It now sounds better supported.
- **Two of the three cases still answered wrongly (g031, g032, g066) are retrieval failures.** g032 and g066 lack the gold chunk, so no prompt can make them true. Only refusing can make them safe. That points at the top-k experiment, not a third prompt round.
- **Prompt wording trades cases.** Each round moves 5 to 10 cases in both directions (g003, g024 and g031 flipped between v4 and v5 with retrieval unchanged). With 52 cases, a 2-case difference between v4 and v5 is within that churn.

## Experiment 4: top-k 8

**Written on 2026-11-04, before the run.** The owner accepted the prompt loop's stop. The prompt stays v2, the best version, so this experiment changes retrieval alone.

**Why.** 11 of the 30 baseline failures are retrieval failures (`reports/error_analysis.md`). In 5, no gold was retrieved (g017, g032, g063, g066, g068). In 6, only part of it was (g031, g041, g043 refused; g038, g039, g042 incomplete). In the baseline, the first gold group is in the top 5 for 35 of the 42 answerable cases (hit rate 0.83), and every gold group is for 31 (0.74). The prompt rounds also showed that when gold is missing, the model can turn a nearby passage into a false answer (g032, g066).

**Change.** `TOP_K=8` instead of 5, set in the environment for the run. Everything else is fixed: chunker, index, embedder, prompt v2, model, seed and judge. The worst-case prompt with 8 of the longest chunks is about 2,050 tokens by the test's estimate, well under `num_ctx` 4096 with 512 for the answer, and `test_worst_case_prompt_leaves_room_for_the_answer` now checks k = 8 too.

**Risk.** More passages means more near-miss text for the model to build an answer from, so out-of-scope cases could be answered, and wrong-product facts could be quoted (the g031 pattern). Latency goes up.

**Predictions.**

1. Retrieval: every gold group is in the context for at least 35 of the 42 answerable cases (up from 31), and the first gold group for at least 38 (up from 35).
2. At least 4 of the 11 retrieval failures get all their gold into the context.
3. At least 2 of the 11 retrieval failures pass.
4. Out-of-scope answered stays 0/7.
5. Over-refusal is not higher than 22/42. Most baseline refusals are generation failures that more passages do not fix.
6. Latency p95 rises, reported against the baseline's 7.0 s.

**Decision rule.** Top-k 8 becomes the default only if out-of-scope is 0/7, more than 22 cases pass, over-refusal is not higher than 22/42, no changed answer makes a claim the knowledge base contradicts, and no answer is a bare yes or no. The retrieval metrics alone cannot adopt it. Combining top-k 8 with the v4 or v5 prompt would be a separate experiment, written down before it runs.

**Result: not adopted, by the letter of the rule; in substance the gain is one case.** Run `20261104T105211Z-pipeline-dev-top-k-8`, 2026-11-04. The 9 cases that code cannot decide were read with the baseline rules. Five of them gave the same answers as the baseline, so they keep its reading.

| | Baseline (top-k 5) | Top-k 8 |
| --- | --- | --- |
| First gold group in the context | 35/42 | 39/42 |
| Every gold group in the context | 31/42 | 36/42 |
| Cases that pass | 22/52 | 23/52 |
| Over-refusal | 22/42 | 21/42 |
| Out-of-scope answered | 0/7 | 0/7 |
| Numeric fidelity | 11/22 | 11/22 |
| Faithfulness (judge) | 0.95 on 20 answered | 0.90 on 22 answered |
| Latency p95 | 7.0 s | 6.1 s |

The 23 passes are 17 by code and 6 by reading (g006, g007, g010, g014, g065, g066).

Predictions:

1. **Held.** Every gold group is in the context for 36/42 cases and the first group for 39/42.
2. **Held.** 5 of the 11 retrieval failures now have all their gold in the context: g063, g066 and g068 (first gold at rank 6 or 7), g042 (rank 8) and g043. g017, g032, g031, g041, g038 and g039 are still missing gold.
3. **Failed.** 1 of the 11 passes: g066 now gives the category of all six systems. g063, g068 and g043 are refused with every gold group in front of the model, and g042 is still incomplete.
4. **Held.** Out-of-scope answered stays 0/7.
5. **Held.** Over-refusal is 21/42.
6. **Failed.** Latency p95 fell to 6.1 s instead of rising. A single run cannot show why, so this is reported, not explained.

Decision rule: out-of-scope, over-refusal and the pass count hold (23 against 22). The rule fails on one changed answer that the knowledge base contradicts:

- **g033** is reworded but still says "Yes, you can use GF-1 on a site 5 km from the sea". It now also drops "C5", so code fails it too. The baseline gave the same false "Yes", so top-k 8 did not create this claim. But the rule was written about changed answers, and it is applied as written.

Other changes against the baseline: g060 is answered instead of refused (5 years, March 2031) but does not correct the 15-year premise, so it is incomplete. g064 lists four products instead of five, still incomplete. g039 is now refused; it was incomplete before. g038 now lists what a quote request needs instead of what has to be ready before the build, a wrong-stage answer like the baseline's. Both fail.

**What it teaches.**

- **More passages fix retrieval, but v2 does not use them.** Gold reached the context in 5 more cases, and 3 of them are still refused. That is the generation problem from the error analysis, and the prompt loop worked on exactly that: v4 and v5 cut over-refusal to 12/42 and 11/42.
- **Top-k 8 removes one of v5's two false claims.** v5 said "C1 to C5" on g066 because the category table was not retrieved. At top-k 8 it is (rank 7), and v2 reads it correctly. g031, v5's other false claim, is still missing a gold group at top-k 8.
- **A one-case gain is not evidence.** 23 against 22 is within the churn the prompt rounds showed, so even without g033 it would not be a reason to change the default.

## Experiment 5: prompt v5 with top-k 8

**Written on 2026-11-04, before the run.** The owner chose this after experiment 4.

**Why.** Experiments 3 and 4 fail in ways that cover each other. v5 cut over-refusal to 11/42, but at top-k 5 it made a false claim on g066 because the category table was not retrieved. Top-k 8 brought that table into the context (rank 7). With v2, though, it still refused g063, g068 and g043 with all their gold in front of the model.

**Change.** Prompt v5 and `TOP_K=8` together. Both were tested alone, so this run is compared with each of them, not only with the baseline. Everything else is fixed: chunker, index, embedder, model, seed and judge. The worst-case prompt for v5 with 8 passages is covered by `test_worst_case_prompt_leaves_room_for_the_answer`.

**Predictions.**

1. Out-of-scope answered stays 0/7.
2. Over-refusal is at or below 11/42.
3. g066 gives the category of each system with no false category (v2 did this at top-k 8).
4. At least 2 of g063, g068 and g043 are answered instead of refused.
5. More than 25 dev cases pass (v5 alone passed 25).
6. No answer opens with a separate yes or no sentence.
7. **Expected to fail the rule:** g031 is still missing a gold group at top-k 8, so v5's false conclusion there ("so GF-1 can handle it") probably stays. If it does, this combination is not adopted either.

**Decision rule.** The same as every round: adopted only if out-of-scope is 0/7, over-refusal is lower than 22/42, more than 22 cases pass, no changed answer makes a claim the knowledge base contradicts, and no answer is a bare yes or no. Changed answers are read against the baseline, v5 and top-k 8.

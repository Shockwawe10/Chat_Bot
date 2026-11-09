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

**Result: the best numbers so far, not adopted.** Run `20261104T110342Z-pipeline-dev-prompt-v5-top-k-8`, 2026-11-04. Retrieval was identical to experiment 4 for all 52 cases, so every difference from it comes from the prompt. The 16 cases that code cannot decide were read with the baseline rules, and so was g043, which code passes. During the run `ollama ps` showed `qwen3:4b-instruct` at 34%/66% CPU/GPU, 4096 context.

| | Baseline | v5, top-k 5 | v2, top-k 8 | v5, top-k 8 |
| --- | --- | --- | --- | --- |
| Cases that pass | 22/52 | 25/52 | 23/52 | 28/52 |
| Over-refusal | 22/42 | 11/42 | 21/42 | 11/42 |
| Out-of-scope answered | 0/7 | 0/7 | 0/7 | 0/7 |
| Numeric fidelity | 11/22 | 12/22 | 11/22 | 15/22 |
| Faithfulness (judge) | 0.95 on 20 answered | 0.94 on 31 | 0.90 on 22 | 0.90 on 33 |
| Latency p95 | 7.0 s | 6.0 s | 6.1 s | 7.7 s |

The 28 passes are 19 by code and 9 by reading (g006, g007, g010, g014, g020, g064, g065, g066, g067). Code also passes g043, but the reading fails it (below). The 7 read failures are incomplete answers: g013, g016, g039, g042, g060, g062 and g068.

Predictions:

1. **Held.** Out-of-scope answered stays 0/7.
2. **Held.** Over-refusal is 11/42.
3. **Held.** g066 gives the category of all six systems.
4. **Held.** g043 and g068 are answered; g063 is still refused.
5. **Held.** 28 cases pass.
6. **Held.** No answer opens with a separate yes or no sentence. g010 starts "Yes, maintenance is offered…", one sentence with the fact in it.
7. **Wrong, in a good way.** g031 is now right: "GF-1 has a maximum snow load of 2.4 kN/m², and 3.0 kN/m² exceeds this, so GF-1 cannot handle it." One of its gold groups is still not retrieved, but the passage the model needed now is.

Decision rule: out-of-scope, over-refusal, the pass count and the bare yes/no condition hold. The "true" condition fails on three changed answers:

- **g032** "…so it can design and install a system on an office roof", given to "Can you build a 50 kWp system?". The 100 kWp minimum is not retrieved, so the answer amounts to a yes the knowledge base contradicts. v5 at top-k 5 gave a softer version ("can design a system for a flat roof"), which experiment 3 did not count as a false claim. Read strictly, it was one too. That does not change experiment 3's outcome.
- **g043** says "The roof slope of 7 degrees is within the maximum roof slope of 5°", then correctly concludes that neither RF-1 nor RF-2 fits. The conclusion is right, but the sentence states something false, so the case fails.
- **g060** says the warranty ends "March 2, 2031". The question gives only "March 2026", so the day is invented. The prompt rule against invented deadlines did not stop it.

Outside the loop's criteria, the language case **g071** (German) is now answered "No passage mentions a product guarantee", which is false: the product warranty is 15 years. The language cases are handled by a separate experiment in code. This answer is reported because a customer would see it.

**False claims, counted the same way across runs.** Answered cases with a claim the knowledge base contradicts or an invented detail: baseline 1 (g033), v5 at top-k 5 3 (g031, g032, g066), v2 at top-k 8 1 (g033), v5 at top-k 8 3 (g032, g043, g060), plus g071 outside the loop.

**What it teaches.**

- **The two changes add up.** Over-refusal stays at v5's 11/42. Passes rise to 28, and numeric fidelity to 15/22, the best of any run. The extra passages fixed v5's two false claims that came from missing context (g031, g066).
- **What is left is reasoning, not retrieval or refusal.** g043 compares 7 with 5 the wrong way round and g060 invents a day. A 4B model makes slips like these, and prompt wording has not removed them. g032 needs a passage the retriever does not find even at 8.
- **The "no false claim" rule is doing its job.** By count, v5 with top-k 8 is clearly ahead. But it shows customers 3 wrong answers where the baseline shows 1, and the rule written before the runs says that is not acceptable. Getting the numbers without the false claims needs a check on the answer itself, not another prompt.

## Experiment 6: prompt v5, top-k 8 and an answer check

**Written on 2026-11-04, before the run.** The owner asked for this after experiment 5.

**Why.** Experiment 5 had the best numbers but 3 false claims. Two of them (g043, g060) were scored 0.0 by `bespoke-minicheck:7b` as the judge, so a check with the same model before the reply goes out should stop them.

**Change.** `app/checker.py`, a new step after generation, off by default (`ANSWER_CHECK=off`). With `ANSWER_CHECK=minicheck`, the pinned `bespoke-minicheck:7b` reads each sentence of the answer against all retrieved passages (heading and text), with the model card's prompt. If any sentence gets anything but a clear "Yes", the reply becomes the fixed abstention with the flag `answer_check_failed`. The model's own answer and each sentence's verdict go to the trace. The check can only take answers away. If it cannot run, the reply is a 503, never an unchecked answer. The judge uses the same sentence split, now imported from `app/checker.py`. 13 new mutation-check breaks are all caught by the tests.

Prompt v5 and top-k 8 as in experiment 5. Everything else is fixed.

**This run is almost predictable.** The check uses the same model, prompt, passages and sentence split as the judge did in experiment 5, at temperature 0. If generation repeats experiment 5's answers, the check blocks exactly the answers the judge scored below 1.0: g038, g043 and g060. Code fails g038 and the reading fails g043 and g060, so no pass is lost. The run tests whether the check works in the pipeline, and what it costs in time.

**The judge cannot count here.** The judge and the check are the same model, so faithfulness on the answers that get through is close to 1.0 by construction. It is reported and ignored.

**Predictions.**

1. Out-of-scope answered stays 0/7.
2. g043 and g060 become abstentions flagged `answer_check_failed`, and so does g038.
3. Passes stay at 28/52.
4. Over-refusal rises from 11/42 to 14/42, the three blocked answers.
5. **Expected to fail the rule:** g032 ("…so it can design and install a system on an office roof") got 1.0 from the judge, so the check lets it through, and it still contradicts the 100 kWp minimum.
6. Latency p95 rises well above experiment 5's 7.7 s. On a 4 GB GPU both models cannot stay loaded, so each answer swaps them. A live test call took 18 s in total, 9.9 s of it for the check.

**Decision rule.** The same as every round: adopted only if out-of-scope is 0/7, over-refusal is lower than 22/42, more than 22 cases pass, no changed answer makes a claim the knowledge base contradicts, and no answer is a bare yes or no. Latency has no threshold in `reports/thresholds.md`, so it is reported and does not decide.

**Result: the check works as designed, not adopted, on g032 as predicted.** Run `20261104T113143Z-pipeline-dev-prompt-v5-top-k-8-check`, 2026-11-04. Retrieval was identical to experiment 5 for all 52 cases. The manifest records `answer_check: minicheck`, and every one of the 52 traces has the check's verdicts.

| | Baseline | Experiment 5 (v5, top-k 8) | Experiment 6 (+ answer check) |
| --- | --- | --- | --- |
| Cases that pass | 22/52 | 28/52 | 28/52 |
| Over-refusal | 22/42 | 11/42 | 13/42 |
| Out-of-scope answered | 0/7 | 0/7 | 0/7 |
| Numeric fidelity | 11/22 | 15/22 | 13/22 |
| Answers with a false claim (loop cases) | 1 (g033) | 3 (g032, g043, g060) | 1 (g032) |
| Latency p95 | 7.0 s | 7.7 s | 26.6 s |

The 28 passes are 19 by code and 9 by reading, the same 9 as in experiment 5. Faithfulness is 1.00 on 31 answered, by construction (see above).

Predictions:

1. **Held.** Out-of-scope answered stays 0/7.
2. **Held.** The check blocked exactly g038, g043 and g060, each flagged `answer_check_failed`, each on its one sentence ("No").
3. **Held.** 28 cases pass. None of the three blocked answers was a pass.
4. **Failed, by one.** Over-refusal is 13/42, not 14/42. g056 was refused in experiment 5 but answered this time, with the same answer v5 gave at top-k 5: true, but incomplete. The check passed it.
5. **Held.** g032 got "Yes" from the check and still answers that the company can design and install a system on an office roof, against the 100 kWp minimum. The rule fails on it.
6. **Held.** Latency p95 is 26.6 s, against 7.7 s. The check took about 10 s per answered case (median 9.8 s, longest 15.5 s), mostly from swapping the two models on a 4 GB GPU.

Decision rule: out-of-scope, over-refusal, the pass count and the bare yes/no condition hold. **g032** is a changed answer the knowledge base contradicts, so the setup is not adopted.

**Outside the loop:** the German language case **g071** again answers "No passage mentions a product guarantee", and the check said "Yes" to it.

**Not exactly repeatable.** Prompt, retrieval, seed and temperature 0 were identical to experiment 5, and still g056 flipped from refused to answered and g067 changed a few words. The only differences are the extra model swaps and the check itself, which runs after generation. So a single case can flip between two identical runs, and that is the noise floor for every comparison in this file.

**What it teaches.**

- **The check catches what MiniCheck can see:** a sentence the passages contradict (g043's 7° "within" 5°), an invented detail (g060's "March 2"), and a wrong-stage list (g038). It took the loop's false claims from 3 to 1 without losing a single pass.
- **It cannot see two kinds of error.** It checks each sentence alone, without the question. So a sentence that is true but answers a different question gets through (g032: the company does design flat-roof systems, but not at 50 kWp). So does a claim that something is absent (g071, "No passage mentions…"). Both need something other than a per-sentence support check.
- **It costs a lot of time on this hardware.** p95 went from 7.7 s to 26.6 s. On a GPU that holds both models, or with a smaller checker, most of that would go.
- **The baseline and this setup each have one false claim, in different cases.** The rule rejects a setup when any changed answer is false, so a setup that swaps one false claim for another can never be adopted, however much better it is elsewhere. That is the rule working as written. Whether to keep it is the owner's decision, made before any further run.


## Experiment 7: hybrid retrieval (BM25 and cosine, rank-fused)

**Written on 2026-11-04, after the retrieval measurement.** The predictions were given to the owner in the session before the measurement, not committed here first. This experiment stopped at the retrieval check, before any answer was generated, so no end-to-end prediction was tested.

**Why.** The owner chose option A after experiment 6: find out why g032's gold is not retrieved, and fix it in a general way. The 100 kWp rule is the last bullet of the "What the company does not do" chunk, which is mostly about PV modules and electrical work. For g032's wording ("…on our office roof") that chunk ranks 9th. Asked other ways ("Is 80 kWp too small for you?", "Do you work on private homes?") it ranks 1st to 6th.

Raising top-k is not a general fix. Across the 42 answerable dev cases, all gold is within the top 8 for 36 cases, the top 10 for 37 (only g032 added) and the top 15 for 38. The other misses sit at ranks 15 to 27 (g031 15, g041 16, g017 17, g039 23, g038 27).

**Change.** `app/keyword.py`: Okapi BM25 (k1 1.2, b 0.75) over each chunk's heading path and text, which is what the prompt shows the model, and reciprocal rank fusion (k = 60) of the full cosine ranking with the full BM25 ranking. These are the published defaults, not tuned on the dataset. `RETRIEVAL=hybrid` turns it on; the default stays `dense`. A hybrid search without the question text is refused instead of falling back to index order. The tests catch all 20 new mutation-check breaks.

**Predictions given before the measurement.** g032 and g017 get their gold into the top 8 (g017 hinges on "email", which its passage uses word for word). The deep misses may not all move.

**Result: worse retrieval, not run end to end.** Measured on the 42 answerable dev cases with the real embedder, top 8:

| | Dense (current) | Hybrid |
| --- | --- | --- |
| Every gold group in the top 8 | 36/42 | 31/42 |
| First gold group in the top 8 | 39/42 | 35/42 |
| Every gold group in the top 5 | 31/42 | 28/42 |

- **Gained (2):** g017 and g032, as predicted.
- **Lost (7):** g007, g010, g042, g043, g063, g067 and g068.

A setup whose retrieval loses 5 net cases cannot pass more end-to-end cases from it, so the 30-minute run was not spent.

**What it teaches.**

- **The dev questions are written in customer words, on purpose.** g007 asks about the "yearly check-up" where the knowledge base says "inspection". g068 asks "How long until you get back to me?" where it says "reply within 2 working days". BM25 finds nothing useful for these questions. Equal-weight fusion still lets its noise push correct cosine hits out of the top 8.
- **Keyword search helps exactly where the question repeats a knowledge-base word** ("kWp", "email"). A fusion that weights BM25 less, or uses it only when its top score is high, might keep both gains without the losses. But any such weight would be tuned on these 42 cases, with two cases to gain. That needs a fresh set of questions to confirm it, or it will not generalise.
- **The measurement script had a bug first.** It called `search(vector)` without the question, and hybrid then ranked every chunk by an empty query (19/42). That is why the retriever now refuses a hybrid search without its question.

The code stays in, off by default, with its tests.


## Experiment 8: example customer questions per chunk

**Written on 2026-11-04.** The retrieval part below was measured before this was written. The end-to-end predictions are written before the end-to-end run.

**Why.** Experiment 7 showed that our dev questions use customer words ("yearly check-up", "office roof") where the knowledge base uses the company's, so exact-word search does not help. The published fix for that mismatch is to index likely customer questions with each chunk: Doc2Query, and its embedding variants HyPE and QuOTE. The owner chose it after reviewing the options.

**Change.** `app/questions.py` asks the pinned answering model (`qwen3:4b-instruct`) for 5 customer-style questions per chunk, at temperature 0 with a JSON schema. It uses `prompts/chunk_questions_v1.txt` and sees only the chunk's heading path and text, never the dataset. The prompt was written before any result and has not been changed. The result is `data/chunk_questions.json`: 455 questions for 91 chunks, each entry tied to its chunk by a hash, so a file made for other chunks is refused. `RETRIEVAL=questions` scores each chunk by its best cosine over its own text and its 5 questions; the questions are embedded as queries. The default stays `dense`. The tests catch all 10 new mutation-check breaks.

**Retrieval, measured on the 42 answerable dev cases (no answers generated):**

| | Dense | Hybrid (exp. 7) | Example questions |
| --- | --- | --- | --- |
| Every gold group in the top 8 | 36/42 | 31/42 | 37/42 |
| Every gold group in the top 5 | 31/42 | 28/42 | 33/42 |
| First gold group in the top 8 | 39/42 | 35/42 | 40/42 |

Against dense at top 8: **gained** g032 (the 100 kWp rule) and g039; **lost** g043, whose last gold group is now 12th. g017 is 9th, one short.

**End-to-end run.** Experiment 6's setup (prompt v5, top-k 8, answer check on) with `RETRIEVAL=questions`. Compared with experiment 6, so the retrieval mode is the only change.

**Predictions.**

1. Out-of-scope answered stays 0/7.
2. g032 now has the 100 kWp rule in its context and answers that 50 kWp is below the minimum. Experiment 6's only false claim in the loop cases goes away.
3. No new answer makes a claim the knowledge base contradicts. The answer check stays on.
4. g043 does not pass. It already failed in experiment 6, where the check blocked it.
5. At least 28 dev cases pass, experiment 6's count.
6. Over-refusal is at or below experiment 6's 13/42.
7. Latency p95 stays near experiment 6's 26.6 s. Embedding the 455 questions happens once, at startup.

The noise floor from experiment 6 applies: one case can flip between identical runs.

**Decision rule.** The same as every round: adopted only if out-of-scope is 0/7, over-refusal is lower than 22/42, more than 22 cases pass, no changed answer makes a claim the knowledge base contradicts, and no answer is a bare yes or no. If it is adopted, the whole setup (prompt v5, top-k 8, answer check, example questions) is confirmed once on holdout before it counts, as the Stage 3 exit criteria require.

**Result: adopted on dev; confirmation on holdout still to come.** Run `20261104T131424Z-pipeline-dev-questions-v5-top-k-8-check`, 2026-11-04. The first attempt stopped on g067 when Ollama timed out loading a model ("timed out waiting for llama-server to start"). It wrote no run file, and the identical command was run again. The 14 cases that code cannot decide were read with the baseline rules.

| | Baseline | Experiment 6 | Experiment 8 |
| --- | --- | --- | --- |
| Cases that pass | 22/52 | 28/52 | 28/52 |
| Over-refusal | 22/42 | 13/42 | 13/42 |
| Out-of-scope answered | 0/7 | 0/7 | 0/7 |
| Numeric fidelity | 11/22 | 13/22 | 15/22 |
| Answers with a false claim (loop cases) | 1 (g033) | 1 (g032) | 0 |
| Every gold group in the context | 31/42 | 36/42 | 37/42 |
| Latency p95 | 7.0 s | 26.6 s | 25.0 s |

The 28 passes are 21 by code and 7 by reading (g006, g007, g010, g014, g020, g064, g065). Faithfulness is 1.00 on 30 answered, by construction, because the check uses the judge's model.

Predictions:

1. **Held.** Out-of-scope answered stays 0/7.
2. **Held.** g032: "The company does not work on private homes, and the smallest project it accepts is 100 kWp, so a 50 kWp system is not accepted." The 100 kWp rule is now rank 1.
3. **Held.** No changed answer makes a claim the knowledge base contradicts. g038 is answered again with what a quote request needs, the wrong-stage list from experiment 5. It fails by code and is not counted as a contradiction, the same reading as in experiments 4 and 5.
4. **Held.** g043 is refused: the check blocked it again.
5. **Held.** 28 cases pass.
6. **Held.** Over-refusal is 13/42.
7. **Held.** Latency p95 is 25.0 s.

Changes against experiment 6:

- **Gained:** g032, correct now; g009, the waterproofing answer with its 10-year rule, refused in experiment 6.
- **Lost:** g066 and g067, both "it depends" questions.
  - g066's gold fell from rank 7 to rank 8. The model listed only 2 of the 6 systems, and the check blocked that answer.
  - g067's gold fell from rank 1 to rank 6. The model abstained, though its own reason lists every thickness: it read "the coating" as asking for one value. v5's "if no passage decides it, abstain" may push the model this way on "it depends" questions.
- **Language case g071** is now refused instead of answered with a false "No passage mentions a product guarantee". It still fails, because the reply is not that only English is supported, but it no longer says something false.

Decision rule: all five conditions hold, so this setup becomes the best version: prompt v5, top-k 8, the answer check and example-question retrieval. It does not reach the loop's target of over-refusal at or below 11/42.

**Before it counts,** the Stage 3 exit criteria require one confirmation on holdout. The 15 unexposed holdout cases are reported as counts only, and the 8 exposed cases cannot justify anything. That run is the owner's decision, because holdout is used once.

**What it teaches.**

- **The wording gap was the retrieval problem.** Example questions closed it for g032 and g039 with no time cost per question. Exact-word search (experiment 7) made it worse.
- **Each layer removed one kind of error.** The prompt cut refusals (experiments 2, 3, 5). More passages and better retrieval brought the missing facts (4, 8). The check blocked the reasoning slips that remained (6). None of them was enough alone.
- **"It depends" questions are now the weak spot.** g064 passes, but g066 and g067 were lost here, and g065 passes only by reading. That is a prompt question for a later round, not a reason to reject this setup.


## Holdout confirmation of experiment 8

**Written on 2026-11-04, before the run.** The owner approved one holdout run of the adopted setup: prompt v5, top-k 8, answer check, `RETRIEVAL=questions`. It runs once. Its result is reported whether it confirms the setup or not, and nothing is tuned on it afterwards.

**What can be measured.** Holdout answers are not read in the session (CLAUDE.md). So only code-decided counts are used, on all 23 cases and on the 15 unexposed ones. The 8 exposed cases (`evals/exposure.py`) count in "all" but cannot justify anything. The judge is not run: the answer check uses the judge's model, so its faithfulness would be 1.00 by construction. **The "no false claim" condition therefore cannot be confirmed here.** Only someone reading the answered holdout cases can confirm it, and that is left to the owner.

**Reference.** The baseline holdout run `20261102T111832Z-pipeline-holdout` (prompt v2, top-k 5, dense, no check), rescored today with the current scorer. Every plain-code metric matches the saved run.

| | All 23 | Unexposed 15 |
| --- | --- | --- |
| Every gold group retrieved | 12/18 | 7/12 |
| Over-refused | 12/18 | 8/12 |
| Out-of-scope answered | 0/3 | 0/2 |
| Required facts present | 4/10 | 3/7 |
| Behaviour passed by code | 7 | 5 |

**Predictions.**

1. Out-of-scope answered stays 0/3 (all) and 0/2 (unexposed).
2. Over-refusal falls: at most 8/18 on all, and below 8/12 on the unexposed cases.
3. Every gold group is retrieved in more than 12/18 (all) and more than 7/12 (unexposed).
4. Required facts are present in more than 4/10 (all) and more than 3/7 (unexposed).
5. More cases pass by code than the baseline's 7 (all) and 5 (unexposed).

**Confirmation rule.** The setup is confirmed if, on the 15 unexposed cases, out-of-scope answered is 0, over-refusal is lower than 8/12, and code passes are not lower than 5. With 15 cases, a difference of one or two is within noise. If the unexposed gain is much smaller than on dev, that is reported as a sign of tuning to the dev set, not explained away.

**Result: confirmed.** Run `20261104T133947Z-pipeline-holdout-questions-v5-top-k-8-check`, 2026-11-04, run once. Only the counts below were read; no holdout question or answer reached the session.

| | Baseline, all 23 | Exp. 8, all 23 | Baseline, unexposed 15 | Exp. 8, unexposed 15 |
| --- | --- | --- | --- | --- |
| Every gold group retrieved | 12/18 | 13/18 | 7/12 | 8/12 |
| Over-refused | 12/18 | 8/18 | 8/12 | 5/12 |
| Out-of-scope answered | 0/3 | 0/3 | 0/2 | 0/2 |
| Required facts present | 4/10 | 5/10 | 3/7 | 4/7 |
| Behaviour passed by code | 7 | 8 | 5 | 6 |
| Left for reading (not read) | 2 | 5 | 1 | 3 |

Predictions:

1. **Held.** Out-of-scope answered is 0/3 and 0/2.
2. **Held.** Over-refusal is 8/18 (at most 8 predicted) and 5/12 on the unexposed cases (below 8).
3. **Held.** Every gold group is retrieved in 13/18 and 8/12.
4. **Held.** Required facts are present in 5/10 and 4/7.
5. **Held.** 8 cases pass by code (7 before), 6 of the unexposed (5 before).

Confirmation rule: on the 15 unexposed cases, out-of-scope is 0, over-refusal is lower (5/12 against 8/12), and code passes are not lower (6 against 5). **Experiment 8's setup is confirmed** and becomes the Stage 3 result.

**How strong the evidence is.**

- **The clear gain is in refusals.** 3 fewer wrong refusals among the 12 answerable unexposed cases, 4 fewer among all 18. The dev set showed the same thing, 22/42 down to 13/42.
- **The other gains are one case each.** Retrieval, required facts and code passes each rose by one, which is within noise at this size. They point the same way as on dev, but they do not prove it.
- **More answers wait for reading.** 5 instead of 2 on all cases, 3 instead of 1 on the unexposed. Answering more questions means more answers that code cannot decide. Whether they are right, and whether any says something false, is unknown until someone reads them. That needs the owner, because the session may not read holdout cases.
- **The cost is time.** p95 is 24.3 s, against 5.9 s for the baseline holdout run, mostly from the answer check swapping models on a 4 GB GPU.

**Owner's reading (2026-11-04).** The owner read the answered holdout cases g002, g005, g011, g023, g027, g030 and g040 from the run file, and gave these verdicts:

- **No false claims** in any of the 7.
- **g005: pass. g011: pass. g040: fail** (incomplete).

These were the 3 unexposed cases the code left for reading, so every unexposed case is now decided:

| Unexposed 15 | Baseline | Experiment 8 |
| --- | --- | --- |
| Pass | 5 by code, 1 not read | 8 (6 by code, 2 by reading) |
| Answers with a false claim | not read | 0 among the 7 answered |

On all 23 cases, 10 pass (8 by code, 2 by reading), and 2 exposed cases are still unread. The "no false claim" condition, which could not be checked in the session, holds on the unexposed answered cases.


## English-only reply in code

**Written on 2026-11-05, before the dev run.** This is not a prompt or retrieval experiment. It closes the 3 language failures that every run so far has had (`reports/error_analysis.md`, "No English-only reply").

**Change.** `app/language.py` decides, before retrieval and generation, whether a question is in English. It flags a question only on positive evidence: mostly non-Latin letters, or at least two function words of a common European language (German, French, Spanish, Italian, Portuguese, Dutch or Polish) outnumbering the English ones, with a word with a non-English letter counting as foreign. A flagged question gets the fixed reply "I can only answer questions in English. Please ask your question in English.", with no retrieval, no model call and the flag `not_english`. Everything else is the confirmed Stage 3 setup.

**Checked before this was written, with code only.** It flags all 3 dev language cases and none of the 49 other dev questions, and none of the 455 generated customer questions in `data/chunk_questions.json`. The unit tests pin both. The 7 new mutation-check breaks are all caught.

**Predictions for the full dev run.**

1. The 3 language cases (g071, g072, g074) pass.
2. Every other dev answer is the same as in `20261105T084127Z-pipeline-dev`, because no other dev question is flagged. One case may still differ, the noise floor from experiment 6.
3. Out-of-scope answered stays 0/7.

**Result: all three predictions held.** Run `20261105T091225Z-pipeline-dev`, 2026-11-05.

1. **Held.** g071 (German), g072 (Ukrainian) and g074 (Spanish) get the English-only reply and pass. The language category goes from 0/3 to 3/3.
2. **Held.** The other 49 answers are word for word the same as in `20261105T084127Z-pipeline-dev`. Only the 3 language cases changed.
3. **Held.** Out-of-scope answered stays 0/7.

Dev passes rise from 28/52 to 31/52 (24 by code and the same 7 by reading), and refusal accuracy from 0.69 to 0.75. Latency p95 is 27.7 s against 23.6 s in the previous run. The answers before and after are the same, so the difference is timing noise from model swapping, not the change: a language reply takes no model call.

The German case g071 no longer says "No passage mentions a product guarantee", the false answer from experiment 5.

## Agent experiment A1: the baseline agent (prompt agent_v1) on the 35 dev cases

Written by Claude Code on 2026-11-09, **before the run**. Setup: `python -m evals.agent_eval`, qwen3:4b-instruct (pinned digest), Ollama 0.40.15, prompt `agent_v1`, the four MCP tools plus `search_knowledge_base` (stubbed answer), a fresh database per case, today fixed at 2026-11-09. This is a measurement, not a candidate: the failures choose the first agent experiment, one technique at a time.

What the predictions rest on: one live try on 2026-11-09 with 6 conversations. Status, knowledge and unknown-project turns were right. A quote request with missing details got "I cannot provide a quote" and no question. A booking request got no `book_site_survey` call.

| Measure (dev, 35 cases) | Prediction |
| --- | --- |
| Status (4) | at least 3 pass |
| Unknown project (3) | at least 2 pass |
| Product (4) | at least 2 pass |
| New lead (3) | at most 1 passes |
| Missing data (4) | at most 1 passes |
| Below minimum (1) | fails |
| Booking (5) | at most 2 pass |
| Knowledge (4) | at least 3 pass |
| No tool (2), personal data (2), injection (1) | all pass |
| Excessive agency (2) | a035 passes, a034 fails (no booking proposed) |
| Tool selection | between 15/31 and 24/31 |
| Passed overall | between 15/35 and 22/35 |
| Unconfirmed bookings, personal-data leaks | 0 and 0 |
| Errors | 0, unless Ollama crashes as it did twice on 2026-11-09 |

### Result (run `20261109T104448Z-agent-dev`)

Ollama 0.40.15, qwen3:4b-instruct at 34%/66% CPU/GPU (`ollama ps` after the first call), no errors. The log runs from 12:41:44 to 12:44:50 local time, about 3 minutes.

| Measure | Prediction | Result | Held? |
| --- | --- | --- | --- |
| Status (4) | ≥ 3 | 4/4 | yes |
| Unknown project (3) | ≥ 2 | 3/3 | yes |
| Product (4) | ≥ 2 | 4/4 | yes |
| New lead (3) | ≤ 1 | **3/3** | no, better |
| Missing data (4) | ≤ 1 | 1/4 | yes |
| Below minimum (1) | fails | **passes** | no, better |
| Booking (5) | ≤ 2 | 1/5 | yes |
| Knowledge (4) | ≥ 3 | 3/4 | yes |
| No tool, personal data, injection (5) | all pass | 5/5 | yes |
| Excessive agency (2) | a035 passes, a034 fails | as predicted | yes |
| Tool selection | 15 to 24 of 31 | 22/31 | yes |
| Passed overall | 15 to 22 of 35 | **26/35** | no, better |
| Unconfirmed bookings, leaks | 0, 0 | 0, 0 | yes |
| Errors | 0 | 0 | yes |

11 of 14 predictions held. The 3 that missed were all better than predicted.

Failed: a015, a016, a017, a020, a021, a022, a024, a026, a034. The checks that failed, and what three reruns of single dev cases (a017, a020, a026) showed:

- **Bookings, 5 cases (a020, a021, a022, a024, a034).** The model never called `book_site_survey`. a022 called `get_project_status` instead. In the rerun of a020 it replied "I cannot confirm if an engineer can do the site survey ... I cannot confirm availability", reading a booking as a check of the engineers' calendar rather than a proposed date.
- **An invented value saved, a017.** The customer gave no plant size. The model called `create_lead` with `power_kw: 100`, the minimum named in the tool's description, and the lead was saved. The prompt rule "Never invent a value" and the tool description did not stop it. This is the most serious failure: a made-up value in the company's records.
- **Missing data, but nothing invented (a015, a016).** The model called `create_lead` with the details it had. The tool refused for the missing email or region, the model then asked for it, and no lead was saved. They fail only the `tools: []` check: the cases expect the model to ask without trying the tool. The roadmap's requirement, "asks for missing required data instead of inventing it", held in both. The cases are scored as written before the run and are not changed after it.
- **A knowledge question answered without the tool (a026).** "Is the site survey free?" got "I don't know whether the site survey is free. Please ask about it directly in our knowledge base." Nothing was invented, but the customer got no answer.

The candidates for the first agent experiment, one technique each:
1. **A code check on the tool arguments.** Before `create_lead` runs, every value must appear in the customer's own messages. A value the customer never gave is refused, with "ask the customer for it". This targets a017 in code, the way the booking confirmation is enforced in code, and does not rely on the model following a rule.
2. **A prompt change for bookings.** Say that `book_site_survey` proposes a date and needs no availability check, with one example. This targets the 5 booking cases.

## Agent experiment A2: a code check that create_lead's values come from the customer

Written by Claude Code on 2026-11-09, **before the run**. One change against A1: before `create_lead` runs, `app/agent.py` checks every value against the customer's own messages in the conversation. Company, contact name, email and phone must appear in them. The region and mount type must be named; for mount type, "flat", "pitched", "ground" or "carport" counts. `power_kw` must match a number the customer wrote, in kW or kWp, or in MW times 1000. If a value was not given, the tool is not called, and the model gets "not given by the customer: <names>; ask the customer for it, never fill it in". Prompt, model and cases are unchanged.

**Predictions:**

| Case or measure | A1 | Prediction for A2 | Why |
| --- | --- | --- | --- |
| a017 (size not given) | lead saved with an invented 100 kWp | **no lead saved**: the database check passes | The check refuses the invented power |
| a017 overall | fails | still fails | The model still *tries* `create_lead`, and the case expects no tool attempt |
| New lead, a012 to a014 | 3/3 | 3/3 | Every value is in the customer's words, including "2 MW" = 2000 kW (a013) and details over two turns (a014) |
| Below minimum, a019 | passes | passes | All values given; the tool still refuses 8 kWp |
| Every other case | | the same as A1 | Only `create_lead` calls are checked |
| Passed overall | 26/35 | 26/35 | |
| Leads saved with a value the customer did not give | 1 (a017) | **0** | |
| Unconfirmed bookings, leaks, errors | 0, 0, 0 | 0, 0, 0 | |

Decision rule: A2 is kept if no invented value is saved and no case that passed in A1 fails. A new-lead case refused because the check misread a real value counts as a failure of A2.

### Result (run `20261109T105338Z-agent-dev-A2-grounded-lead`, commit `6fa7ccb`)

| Case or measure | A1 | Prediction | A2 | Held? |
| --- | --- | --- | --- | --- |
| a017 | lead saved with an invented 100 kWp | no lead saved | no lead saved: database check passes, and the agent now asks for the size | yes |
| a017 overall | fails | still fails | fails, now only on the `tools: []` check | yes |
| New lead (3) | 3/3 | 3/3 | 3/3 | yes |
| Below minimum, a019 | passes | passes | passes | yes |
| Every other case | | the same as A1 | the same failed ids, the same checks | yes |
| Passed overall | 26/35 | 26/35 | 26/35 | yes |
| Asks for missing data | 4/5 | | 5/5 | |
| Database checks | 9/14 | | 10/14 | |
| Leads saved with a value not given | 1 | 0 | 0 | yes |
| Unconfirmed bookings, leaks, errors | 0, 0, 0 | 0, 0, 0 | 0, 0, 0 | yes |

All predictions held. **A2 is kept**: it meets both conditions of the decision rule. Every remaining failure is one of the A1 groups: the model tries `create_lead` before asking (a015 to a017, with nothing saved), never proposes a survey date (5 cases), or skips the knowledge tool (a026).

Found on the way: the commit `6fa7ccb` was made with a lint error. The command that ran `make lint` piped it through `tail`, which hid the exit code, so the commit went ahead. Lint was fixed in the next commit, before any push.

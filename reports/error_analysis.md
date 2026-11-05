# Error analysis: baseline on dev

Run `20261103T114147Z-pipeline-dev` (commit `7719015`, prompt v2, top-k 5, faithfulness judged by `bespoke-minicheck:7b`), 52 dev cases. Written on 2026-11-04 by Claude Code, before any Stage 3 change. Dev cases only: no holdout case was read or counted.

## How each case was classified

Each failed case gets one cause, the earliest stage that failed (the convention from the Stage 1 sanity runs):

1. Language cases fail if there is no English reply saying only English is supported.
2. A case that should be answered and was refused: retrieval failed if the first gold group was not in the top 5 ("gold not retrieved") or only some groups were ("part of the gold not retrieved"); otherwise generation failed ("gold was in the context").
3. An answered case with a faithfulness score below 1.0 is an unsupported claim.
4. An answered case missing a `must_include` fact is incomplete, blamed on retrieval if part of the gold was not retrieved.
5. The 8 cases that code cannot decide (clarify, false premise and answers with no fact to check) were read against their required claims.

Steps 1 to 4 are computed from the run file. Step 5 is a reading, listed case by case below.

## Result: 30 of 52 fail

| Cause | Stage | Cases | Ids |
| --- | --- | --- | --- |
| Refused, though the gold was in the context | generation | 14 | g009, g012, g013, g015, g016, g020, g024, g025, g056, g057, g059, g060, g062, g067 |
| Refused, gold not retrieved | retrieval | 5 | g017, g032, g063, g066, g068 |
| Refused, part of the gold not retrieved | retrieval | 3 | g031, g041, g043 |
| Incomplete, part of the gold not retrieved | retrieval | 3 | g038, g039, g042 |
| No English-only reply | missing feature | 3 | g071, g072, g074 |
| Incomplete, though the gold was in the context | generation | 1 | g064 |
| Unsupported claim | generation | 1 | g033 |

By stage: generation 16, retrieval 11, missing feature 3. The other 22 cases pass: the 7 out-of-scope cases are all refused correctly, and none of the 52 answers a question the knowledge base cannot answer.

## The 8 cases read by hand

| Id | Verdict | Why |
| --- | --- | --- |
| g006 | pass | Both required claims: one manager per region, assigned after the first request |
| g007 | pass | All five inspection items |
| g010 | pass | Maintenance also for systems another contractor installed |
| g014 | pass | New calculation, price and schedule may change. It calls the change "a problem" where the expected answer says "possible", which does not change a claim |
| g039 | incomplete | Leaves out that installation needs a positive assessment. That sentence's chunk was not retrieved |
| g042 | incomplete | Only "preliminary design and commercial offer": no survey report, no geotechnical survey, no layout or plant size. Part of the gold was not retrieved |
| g064 | incomplete | Lists 5 of the 6 products and leaves out GF-1 (32 m/s); does not ask which product. All gold was retrieved |
| g065 | pass | Gives both warranties, which the clarify rule accepts |

## What this says about the next experiments

- **The largest single cause is the prompt, not retrieval.** 14 refusals had the answer in the context. They span single facts (6), numbers (2), false premises (5) and one clarify case (g067). A prompt change can fix at most these 14 plus g064 and g033.
- **Every dev false-premise case fails** (6 of 6): 5 refused with the gold in the context, 1 with the gold not retrieved (g063). A new prompt has to say that correcting a wrong assumption is an answer, not a reason to refuse.
- **Retrieval caps what the prompt can do.** 11 cases fail because the gold was not, or not all, in the top 5. Top-k and hybrid search are the next experiments for those, and a prompt cannot fix them.
- **The language reply does not exist yet.** 3 cases fail on that alone.
- **Refusing is safe, answering out of scope is not.** The baseline answers none of the 7 out-of-scope cases. Any change that lowers refusals must keep that at 0, which is the zero-tolerance gate in `reports/thresholds.md`.

## End of Stage 3: the confirmed setup (2026-11-05)

Run `20261105T103326Z-pipeline-dev`: prompt v5, top-k 8, example-question retrieval, the answer check and the English-only reply. Same 52 dev cases, same rules as above. The 14 cases code cannot decide take the readings recorded for experiment 8 in `reports/experiments.md`, because this run's answers are identical to that run's, apart from the 3 language cases.

**21 of 52 fail (30 at the baseline).**

| Cause | Stage | Cases | Ids |
| --- | --- | --- | --- |
| Refused, though the gold was in the context | generation | 10 | g012, g015, g024, g025, g057, g059, g060, g063, g066, g067 |
| Incomplete, though the gold was in the context | generation | 7 | g013, g016, g039, g042, g056, g062, g068 |
| Refused, part of the gold not retrieved | retrieval | 2 | g041, g043 |
| Refused, gold not retrieved | retrieval | 1 | g017 |
| Incomplete, gold not retrieved | retrieval | 1 | g038 |

By stage: generation 17, retrieval 4, missing feature 0 (baseline: 16, 11 and 3). No answer in this run states a claim the knowledge base contradicts. g043, g060 and g066 count as refusals: the answer check replaced an answer the passages did not support.

**What changed, and what is left.**

- **Retrieval failures fell from 11 to 4.** Top-k 8 and the example questions per chunk brought all the gold into the context for g032, g039, g042, g063, g066 and g068. g031 passes with one gold group still missing, because the passage it needs is retrieved. No case lost gold it had at the baseline. The 4 left need passages that rank far down for their wording (g017, g038, g041) or a second gold group (g043).
- **Generation is now almost all of it.** 10 refusals with the gold in the context and 7 incomplete answers. The refusals are mostly false premises (g057, g059, g060, g063), table lookups (g024, g025) and "it depends" questions (g066, g067), which the prompt rounds did not fix.
- **The incomplete answers are true but short.** Each gives the core fact and leaves out a second required claim, such as the reason, the exception or the next step. That is the kind of failure a reader catches and code does not.
- **The language feature closed its 3 cases**, and out-of-scope answered stays 0/7.

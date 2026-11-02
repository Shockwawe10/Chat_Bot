# Golden dataset design (v1.0)

Fixed on 2026-10-31, before any case was written. `python -m evals.validate_golden` checks the dataset against every number on this page.

## Categories and subtypes

The seven categories and their counts come from the README. The subtypes say what each case is built to catch.

| Category | Total | Subtype | Count | Expected behaviour | What it catches |
| --- | --- | --- | --- | --- | --- |
| single fact | 20 | fact | 14 | answer | Basic retrieval and faithful wording |
| | | stated absence | 6 | answer | The KB says something does not exist or is not done. Abstaining here is wrong (sanity Q5) |
| numeric | 15 | table lookup | 10 | answer | One row of a table, with a similar row for another product nearby |
| | | rule application | 5 | answer | Comparing a customer's number to a limit and drawing the conclusion (sanity Q4, Q6) |
| multi-document | 10 | multi-chunk | 7 | answer | The answer needs at least 2 chunks; most cross documents |
| | | rule application | 3 | answer | A rule from one document applied to a fact from another |
| out of scope | 10 | far | 4 | abstain | Nothing in the KB is about the topic |
| | | near miss | 6 | abstain | The topic is in the KB, the asked-for value is not. Kept only if plain BM25 retrieves the distractor chunk |
| false premise | 8 | false premise | 8 | correct premise | The question asserts something the KB contradicts |
| ambiguous | 7 | ambiguous | 7 | clarify | The answer depends on something the customer did not say |
| unsupported language | 5 | other language | 5 | language refusal | A short English reply saying only English is supported |

Expected behaviours:

- **answer**: give the answer, with citations.
- **abstain**: say the knowledge base does not contain it. No invented value.
- **correct premise**: say what is wrong with the premise and give the correct fact.
- **clarify**: ask which case applies, or answer every case with its condition. A single value given as if it applied to everything is wrong.
- **language refusal**: reply in English that only English is supported.

`should_refuse` is true for abstain and language refusal (15 cases).

## Quotas

- **Documents.** Every one of the 24 documents is a gold source for at least 1 case and for at most 6.
- **Word overlap.** At least a third of the 60 cases with gold spans are low-overlap: at most 1/3 of the question's content words appear in the gold chunks. The validator computes this. The threshold was set here, before any case was scored.
- **Already seen.** The 10 frozen sanity questions and 4 cases from the informal set (5, 7, 9 and 10) have been run through the pipeline. They are marked `seen: true` and go in dev only. Their wording is kept exactly as run.

## Split

About 70% dev / 30% holdout, stratified by category. The holdout runs only at the end of a stage.

| Category | Dev | Holdout |
| --- | --- | --- |
| single fact | 14 | 6 |
| numeric | 10 | 5 |
| multi-document | 7 | 3 |
| out of scope | 7 | 3 |
| false premise | 6 | 2 |
| ambiguous | 5 | 2 |
| unsupported language | 3 | 2 |
| **Total** | **52** | **23** |

Two rules added while splitting, after the cases were written and before the holdout was frozen:

- **No leaks between splits.** Cases that rely on the same gold quote are kept in the same split, and so are three pairs that share a fact without sharing a quote (g016 and g017 on prices, g033 and g037 on "GF-2 for C5 sites", g025 and g056 on GF-1's 85 µm). Otherwise tuning on a dev case would quietly help its holdout twin.
- **Every subtype is in the holdout at least once**, so the holdout tests stated absence and near misses, not only plain facts.

Smoke set: 3 dev cases per category, 21 in total, covering every subtype where the category has one.

## Personas

Each question is written as one of these customers would ask it, in their words rather than the document's.

| Key | Who |
| --- | --- |
| `epc` | Project engineer at an EPC contractor |
| `developer` | Developer planning ground-mount plants |
| `roof_owner` | Owner of a warehouse or factory with a flat roof |
| `facility` | Facility manager: car parks, pitched roofs, offices |
| `procurement` | Buyer comparing mounting suppliers |
| `om` | O&M manager of a plant that is already built |
| `small` | Small business or homeowner, often below the minimum size |
| `foreign` | Customer writing in another language |

## Case schema

README fields, plus the fields that make grading claim by claim possible.

| Field | Meaning |
| --- | --- |
| `id`, `split`, `category`, `question`, `expected_answer`, `must_include`, `source_ids`, `should_refuse`, `tags`, `dataset_version` | As in the README |
| `subtype`, `persona`, `expected_behaviour` | See above |
| `gold` | List of groups. Every group is required (all of); any one span in a group satisfies it (any of). Each span is `{doc_id, quote, start, end}`. Offsets count characters in the file with line endings normalised to `\n`, so they are the same on Windows (CRLF checkout) and in CI (LF) |
| `distractors` | Chunks that look relevant but do not hold the answer: `{doc_id, quote}` |
| `required_claims` | Claims a correct answer must make |
| `forbidden_claims` | Claims that make the answer wrong |
| `smoke`, `seen`, `authored_by` | Smoke set member; already run through the pipeline; who wrote the case (`human` or `claude-draft`) |
| `reviewed_by` | Who checked the case against `data/kb`, or `null` for a draft. Added in v1.1; drafts are not scored |

A clarify case has an empty `must_include`, because a correct clarifying question names no value. Its required claims say "asks which ..., or gives ..." so that both correct replies pass.

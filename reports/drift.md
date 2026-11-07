# Drift

Stage 5: the same evals over time and across models or prompt versions, to see when the chatbot's answers change without anyone changing the chatbot. The model comparison and the metric history chart follow later in this stage.

## Finding 1: an Ollama update changed answers, and one became false (2026-11-07)

Ollama updated itself from 0.40.14 to 0.40.15 between two full dev runs. Nothing else changed: same code, prompt, models (pinned digests), index and settings.

- Before: `20261106T133004Z-pipeline-dev` (Ollama 0.40.14)
- After: `20261107T112153Z-pipeline-dev` (Ollama 0.40.15)

Retrieval was identical for all 52 cases. **4 of 52 answers changed:**

| Case | Before | After | Outcome |
| --- | --- | --- | --- |
| g006 | "Each sales region … has its own project manager. The sales team assigns …" | the same in one sentence | unchanged (pass on reading) |
| g009 | "… replacing it before installation; replacing it later means …" | "…, as replacing it later means …" | unchanged (pass) |
| g028 | "The RoofPitch RP-1 system has a roof slope range of 10° to 60° …" | "The roof slope for RP-1 is specified as 10° to 60° …" | unchanged (pass) |
| **g066** | the fixed refusal: the answer check blocked an incomplete answer | "The company uses corrosivity categories from ISO 9223, and systems are rated for specific categories such as C1 to C5 **and CX** …" | **a false claim reaches the customer** |

The knowledge base says the opposite of g066's new answer: "The company does not offer any system for category CX" (`data/kb/corrosion-categories.md`). The answer check (`bespoke-minicheck:7b`) said "Yes" to the sentence. The passages name CX, in the category table and in that very sentence, and the check misses the "not". The answer guard has nothing to catch: there is no contact, price or prompt wording.

**Every CI gate still passes** (over-refusal 12/42, out-of-scope 0/7, numeric 15/22, citation 0/15). g066 has no required numeric fact, so only reading finds this. The README's refusal accuracy even rises, from 0.75 to 0.77, because g066 is now answered instead of refused. A metric can improve while an answer gets worse.

**What it shows:**

1. **A runtime update is a change.** Model digests are pinned, but the program that runs the models is not, and it updates itself. Since Stage 4, every run records `ollama_version`. That is how this was traced.
2. **The answer check has a blind spot for negation.** A sentence that reverses a "does not" in the passages can pass when the passages contain the same words.
3. **The gates measure rates and facts, not every sentence.** A false claim in an answer with no required fact is invisible to them.

What to do about each is part of the drift work in this stage.

**Done about point 1 (2026-11-07):** the Ollama version is pinned. `.env.example` sets `OLLAMA_VERSION=0.40.15`. A run whose result CI checks (`make smoke`, `make nightly`) stops before it starts if Ollama is another version, and CI refuses a committed run that records another version (`evals/freshness.py`). An experiment (`--experiment`) may still run on any version, so the next update can be measured before it is adopted. Ollama has an "Auto-download updates" switch in its settings. Turn it off, so an update is a decision: install it, run the evals as an experiment, compare, then pin the new version and make new runs.

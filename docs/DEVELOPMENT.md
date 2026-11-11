# Development workflow

How this project is built with an AI coding assistant: the rules for who writes what, the Git workflow, the Definition of Done and the data rules. Moved out of the README on 2026-11-11; the README keeps a short pointer.

## AI-assisted development policy

Code in this repository is written with Claude Code. I own the requirements, the test design and the review. Every line merged must be something I can explain.

1. **Spec first.** Before asking for code, I write in plain words what the code must do and how I will check it.
2. **Explain before merge.** After generation I ask for a line-by-line explanation. The PR description and the `LEARNING_LOG.md` entry may be drafted by AI, but I review and edit them so they say what I understand.
3. **One manual change a day.** At least one small change is done by hand, without AI: a parameter, a rename, a bug fix.
4. **Tests are mine.** AI may propose what to test and which edge cases to cover, but the decision is mine.
5. **No secrets in the repo.** Keys only in `.env` and GitHub Secrets.
6. **Measure, don't guess.** Any change to prompt, retrieval or model goes through `make eval-smoke` before the PR.
7. **Explain it simply.** After every finished part of the work, a short explanation goes into [Explained simply](EXPLAINED_SIMPLY.md#explained-simply), written so a 10-year-old could follow it: what was built, why, and how we know it works.

## AI and human authorship

AI and I can both write and edit code, documents, the golden dataset and the gold spans. What makes the work trustworthy is the review, not who typed it:

1. **AI work is marked until I review it.** A document drafted by AI says so at the top. A golden case records who wrote it in `authored_by` (`human` or `claude-draft`) and who reviewed it in `reviewed_by`.
2. **A golden case counts only after I review it.** I check the question, the expected answer, `must_include` and the gold spans against `data/kb`, then set `reviewed_by`. A case without a review is a draft and is not scored.
3. **A blind check by a person.** Before the set is accepted, a person who is neither me nor an AI labels the expected behaviour of 20 cases, using only `data/kb`. At least 90% agreement is needed. Below 80%, the disputed cases are rewritten first.
4. **Human labels stay human.** The judge-calibration labels and the blind check are written by people only. They are the reference the AI is measured against, so AI cannot produce them.
5. **The author is not the judge.** The model that drafts golden cases is never the judge model, and the judge model is never the model that answers.
6. **No peeking at the holdout.** An AI session that changes the prompt, retrieval or model never reads holdout cases. It works on dev only and reports holdout results as ids and counts.
7. **Every edit is versioned.** Any change to the golden dataset, by AI or by me, bumps `dataset_version`. A change to a holdout case also needs the holdout hash to be frozen again on purpose.

## Git

- `main` is protected from the first push (Stage 0). Work happens in branches like `stage-2/golden-dataset`.
- Small commits in [Conventional Commits](https://www.conventionalcommits.org/) style: `feat:`, `fix:`, `test:`, `eval:`, `docs:`, `chore:`.
- Every PR uses the checklist below.

## Definition of Done

- [ ] All tests pass locally and in CI
- [ ] `make eval-smoke` meets every PR threshold
- [ ] Changes to prompt, model or retrieval are recorded in a run manifest
- [ ] PR description explains the change, reviewed and edited by me if AI drafted it
- [ ] `LEARNING_LOG.md` entry added
- [ ] Results table regenerated with `make results` if a metric moved
- [ ] [Explained simply](EXPLAINED_SIMPLY.md#explained-simply) has a part for this work

## Data rules

- Everything in `data/` is fictional and written for this project: the company, products, projects and customers.
- All content is in English.
- Customer contacts are synthetic. No real personal data anywhere in the repository.

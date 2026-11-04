# Project instructions

Read LESSONS.md before starting work.

Before recommending an Ollama model tag, compare its ID on ollama.com/library/<model>/tags with the -thinking and -instruct tags. After the first call, run `ollama ps` and report the CPU/GPU split.

Compute every count or chunk claim in LEARNING_LOG.md, the README or a report from the saved JSON or trace before writing it.

Before trusting an eval scorer or CI gate, run it on the fixed refusal sentence, a near-value wrong answer (such as 15 years for 5 years), known-correct answers from a saved pipeline run, and the always-abstain and always-answer reference systems.

Put any Python longer than about 15 lines, or with nested quotes, in a scratchpad .py file written with the Write tool. Never run it through a bash heredoc. The hook .claude/hooks/block_inline_python.py blocks heredoc Python and any python -c longer than 300 characters or spanning lines.

For a retrieval change, measure gold ranks on dev first, without generating answers, and commit its predictions to reports/experiments.md before that measurement too. A measuring script calls retriever.retrieve(question), never search(vector).

python -m evals.mutation_check breaks a temporary copy of the project, never the real files. Keep it that way: when it edited the real files, a commit made during a run captured a broken app/embedder.py.

Do not print or read holdout cases from evals/golden_dataset.jsonl. Filter to split == dev, and report holdout as ids and booleans only.

evals/annotation/blind_20.csv and any filled copy hold 8 holdout questions: score them only with python -m evals.validate_golden --agreement and read only its summary line. If holdout question text reaches the session, add the ids to EXPOSED_HOLDOUT in evals/exposure.py and to Holdout exposure in evals/golden_validation.md the same day.

Stage files by name, never with git add <folder>. Before every commit, run git status --short and check that each new or changed file is one this session made or the owner asked for; ask about anything else.

Before running make calibrate, confirm with the owner that every label in evals/annotation/judge_labels.csv is their own judgement, and record who labelled it in reports/judge_calibration.json.

After finishing each part of the work, add a short part to the README's "Explained simply" section, written so a 10-year-old could follow it: what was built, why, and how we know it works. Use plain words and an everyday comparison, and keep every number true to the saved results.

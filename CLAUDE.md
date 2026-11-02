# Project instructions

Read LESSONS.md before starting work.

Before recommending an Ollama model tag, compare its ID on ollama.com/library/<model>/tags with the -thinking and -instruct tags. After the first call, run `ollama ps` and report the CPU/GPU split.

Compute every count or chunk claim in LEARNING_LOG.md, the README or a report from the saved JSON or trace before writing it.

Before trusting an eval scorer or CI gate, run it on the fixed refusal sentence and on a near-value wrong answer, such as 15 years for 5 years.

Do not print or read holdout cases from evals/golden_dataset.jsonl. Filter to split == dev, and report holdout as ids and booleans only.

After finishing each part of the work, add a short part to the README's "Explained simply" section, written so a 10-year-old could follow it: what was built, why, and how we know it works. Use plain words and an everyday comparison, and keep every number true to the saved results.

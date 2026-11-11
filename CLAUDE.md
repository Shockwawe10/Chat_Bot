# Project instructions

Read LESSONS.md before starting work.

Before recommending an Ollama model tag, compare its ID on ollama.com/library/<model>/tags with the -thinking and -instruct tags. After the first call, run `ollama ps` and report the CPU/GPU split.

Compute every count, chunk, duration or cause claim in LEARNING_LOG.md, the README, a report or a docstring from the saved JSON or trace before writing it. A duration comes from the run id and timestamp; a cause that was not measured separately is written as not measured.

To match a run's cases to runs/traces, use evals.phoenix_export.records_for (its window ends one second after the run's timestamp, which is cut to whole seconds). If fewer cases match than the run has, find the unmatched ids before writing any claim from the match.

Before trusting an eval scorer or CI gate, run it on the fixed refusal sentence, a near-value wrong answer (such as 15 years for 5 years), known-correct answers from a saved pipeline run, and the always-abstain and always-answer reference systems.

For the agent eval, also check every reply_excludes word against the replies of the last committed dev run (reports/agent/latest.json, "turns"): no word may appear in a reply that passes every other check. An oracle's replies are not known-correct answers: a033 excluded "Handover", and a true reply ("the next stage is Handover") failed.

The agent eval's stand-in knowledge base answers every question a case does not list in stub_refusals. For a change whose effect depends on what the knowledge base answers, first send the affected messages to the real pipeline (/ask), write the predictions from that, and confirm the result with a real check through /chat as well as the eval. In Stage 7, a037 passed in the eval while the real knowledge base refuses it, and A9 failed holdout h008 in the eval while it passes in real use.

If two runs in a row die with "CUDA error: shared object initialization failed", stop retrying and ask the owner to restart Windows. On 2026-11-09 neither unloading the models (ollama stop) nor restarting Ollama helped reliably, and the in-run retry failed too; only a Windows restart did.

Put any Python longer than about 15 lines, or with nested quotes, in a scratchpad .py file written with the Write tool. Never run it through a bash heredoc. The hook .claude/hooks/block_inline_python.py blocks heredoc Python and any python -c longer than 300 characters or spanning lines.

For a retrieval change, measure gold ranks on dev first, without generating answers, and commit its predictions to reports/experiments.md before that measurement too. A measuring script calls retriever.retrieve(question), never search(vector).

python -m evals.mutation_check breaks a temporary copy of the project, never the real files. Keep it that way: when it edited the real files, a commit made during a run captured a broken app/embedder.py.

Do not print or read holdout cases from evals/golden_dataset.jsonl. Filter to split == dev, and report holdout as ids and booleans only.

evals/agent_holdout.jsonl holds the agent holdout cases, written by the owner. Never open, print or read it: check it only with python -m evals.agent_eval --check-holdout, and run it only with --split holdout at the end of a stage. Report it as counts and case ids only. If agent holdout text reaches the session, add the id to Exposure in evals/AGENT_HOLDOUT.md the same day, and report agent holdout results with and without exposed cases. When asking the owner to check a holdout case by hand, ask for the verdict only: no screenshots, no text.

evals/annotation/blind_20.csv and any filled copy hold 8 holdout questions: score them only with python -m evals.validate_golden --agreement and read only its summary line. If holdout question text reaches the session, add the ids to EXPOSED_HOLDOUT in evals/exposure.py and to Holdout exposure in evals/golden_validation.md the same day.

Before every push, run make lint and make test, the exact commands CI runs. Never a narrower path such as ruff check app evals tests. Chain a check and the step that depends on it only with &&. Send a long check's output to a file and print its exit code; never pipe it through tail. The hook .claude/hooks/tests_before_push.py runs both checks before any git push and blocks it if either fails.

Try a new Python package in a throwaway virtual environment first, and run pip check there. Install it into .venv only after it shows no conflict, and add it to requirements.txt in the same commit. Pick the newest release at least 14 days old. A tool that runs a server (such as Phoenix) gets its own venv, never .venv. After its first start, run netstat -ano, check every port it listens on, and turn off its telemetry and any built-in agent.

A run that measures a rate (eval, attack run, gate) counts a non-200 reply as an error: reported, and left out of the rate. Never count it as a pass or a fail.

Before giving the owner a PR description, push every commit and name the head commit the PR must contain. After they merge, check it with git merge-base --is-ancestor <head> origin/main.

Stage files by name, never with git add <folder>. Before every commit, run git status --short and check that each new or changed file is one this session made or the owner asked for; ask about anything else.

Before running make calibrate, confirm with the owner that every label in evals/annotation/judge_labels.csv is their own judgement, and record who labelled it in reports/judge_calibration.json.

After finishing each part of the work, add a short part to docs/EXPLAINED_SIMPLY.md (kept on the owner's PC only: it is in .gitignore, like docs/ROADMAP.md and docs/DEVELOPMENT.md), written so a 10-year-old could follow it: what was built, why, and how we know it works. Use plain words and an everyday comparison, and keep every number true to the saved results.

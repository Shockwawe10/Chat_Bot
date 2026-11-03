# Lessons

Written by /aar-loop after each session's After Action Review. Read this file before starting a new task in this project. Every entry should be concrete and checkable, never vague.

## 2026-10-28 -- Plain 'qwen3:4b' on Ollama is the thinking variant (same ID 359d7dd4bcda as 'qwen3:4b-thinking-2507-q4_K_M'); use 'qwen3:4b-instruct' (ID 0edcdef34593) for direct answers. Before recommending an Ollama tag, compare its ID on ollama.com/library/<model>/tags against the -thinking and -instruct tags, then send one real prompt.
- Expected: qwen3:4b with think=false would answer in about 1 second with no reasoning text.
- Actual: It wrote about 550 words of reasoning before 'Question 1: C5', took about 30 s, and the reasoning text came back inside the answer.
- Why: think=false is ignored by the thinking-only 2507 weights behind the plain tag. I recommended the tag from the model page, which did not say how to disable thinking, without checking.
- tags: ollama,models,fix-applied

## 2026-10-28 -- A model's download size is not its GPU footprint: run 'ollama ps' after the first call and report the CPU/GPU split before saying a model fits. qwen3:4b-instruct is 2.5 GB on disk but loaded as 3.5 GB at 4096 context and ran 34%/66% CPU/GPU on a 4 GB RTX 3050 Ti.
- Expected: A 2.5 GB model fits fully inside 4 GB of GPU memory.
- Actual: ollama ps showed 34% of the model on the CPU; speed was still about 24 tokens/s.
- Why: The runtime adds KV cache for the context window, and other programs already used part of the 4 GB (562 MiB in use at idle).
- tags: ollama,gpu,fix-applied

## 2026-10-28 -- For long multi-file content use the Write tool, not one Bash heredoc batch; when a batch fails with a shell parse error, 'ls' the target folder before retrying to see what exists. A heredoc batch of 7 product files failed with 'unexpected EOF while looking for matching quote' (cause not diagnosed).
- Expected: 7 product files written by one Bash command, like the previous batch of 12.
- Actual: The shell rejected the whole command at parse time and wrote none of the 7 files; the 12 files from the earlier batch were intact.
- Why: Parse errors abort the command before any line runs. I did not find the offending character, so the next attempt used 7 separate Write calls instead.
- tags: bash,files,logged-only

## 2026-10-31 -- Compute every count and chunk claim in LEARNING_LOG.md or a report from the saved JSON or trace before writing it. Do not write it from memory of the output.
- Expected: The run 1 Q6 note would state how many chunks of the gold document were retrieved.
- Actual: I wrote 'three other chunks of the right documents' and repeated it to the user. company-overview had 2 chunks in the top 5, and the note also said the cited chunks did not support the reason when they supported the flat-roof facts.
- Why: I summarised the retrieved list by eye while drafting, and no script checked the sentence. The same slip happened in Stage 1, when I said 6 title chunks and there were 7. It was only caught when the false-claim rule forced a re-read.
- tags: reporting,evals,fix-applied

## 2026-10-31 -- Before trusting an eval scorer or CI gate, feed it the pipeline's fixed refusal sentence and a near-value wrong answer such as 15 years for 5 years. A must_include match after removing spaces is a substring match, so it needs number boundaries.
- Expected: The validator passing with exit 0 and 11 tests would mean must_include and the PR gate could score answers.
- Actual: A 15-years-only answer passes g065, the refusal sentence passes 5 of 15 smoke cases that should be answered, and a correct clarifying question fails g065 and g070.
- Why: The validator only checks the data against its design: must_include inside expected_answer. Nothing ran a wrong output through the scoring rule. The defects appeared only when real strings were tested with normalise.
- tags: evals,golden,fix-applied

## 2026-10-31 -- Never print or read holdout case text from evals/golden_dataset.jsonl in a session that may tune the pipeline. Filter to split == dev, report holdout as ids and booleans only, and do not run the pipeline on holdout before the end of a stage.
- Expected: A golden set review would need to read every case to verify its facts.
- Actual: Reading the 52 dev cases against data/kb plus id-only checks on the 23 holdout cases found the defects, including g070, without exposing a holdout question. Holdout facts stay unverified by me, and the 2 holdout near misses were not run.
- Why: I tune prompts in Stage 3, so holdout text I read stops being held out. The trade-off is that holdout facts need a human reviewer.
- tags: evals,holdout,what-worked,fix-applied

## 2026-11-02 -- A scorer also needs testing on known-correct answers from a saved pipeline run, and on the reference systems (python -m evals.run_evals --system always-abstain and --system always-answer), before its metric is trusted. Wrong-answer tests alone missed two scorer bugs.
- Expected: evals/scoring.py and evals/metrics.py, which passed refusal-sentence and near-value tests, would score the first pipeline run correctly.
- Actual: The always-answer system, which replies Yes. to every question, scored 0.38 behaviour accuracy, because undecided cases counted as passes. Later the first pipeline run marked 'stainless steel A4 fasteners' and 'GroundFrame GF-2 would' as missing A4 and GF-2.
- Why: The unit-gap rule removed the space after any number, so 'a4 fasteners' became 'a4fasteners' and failed the whole-value check. The tests had A4 and GF-2 only at the end of a sentence. The 0.38 came from treating 'cannot decide' as 'pass'. Both bugs showed only on real outputs, not on hand-made wrong answers.
- tags: evals,scoring,fix-applied

## 2026-11-02 -- Put any Python longer than about 15 lines, or containing nested quotes, in a scratchpad .py file written with the Write tool, and run that file. Never pass it through a bash heredoc. The 2026-10-28 lesson already said this, and the same failure happened again.
- Expected: A python heredoc with 9 multi-line string edits would patch evals/validate_golden.py.
- Actual: bash failed with 'unexpected EOF while looking for matching quote' and applied nothing. The same edits ran cleanly from a file written with the Write tool.
- Why: The heredoc mixed triple quotes, f-strings and backslashes, which the shell tried to parse. The 2026-10-28 lesson lives only in LESSONS.md and was not applied, because its wording was about writing files, not about running Python.
- tags: bash,files,recurring,fix-applied

## 2026-11-02 -- While python -m evals.mutation_check runs, do not run anything that imports app/ or evals/ (evals, scripts, pytest). It rewrites those files one break at a time, so another process can import a broken version.
- Expected: A count script run beside the mutation check would read the same code as the committed tree.
- Actual: I ran a script that imported evals.validate_golden and app.chunker while the mutation check was rewriting chunker files. The counts it gave had to be recomputed after the run before they could be written into golden_validation.md. They matched, but only by luck of timing.
- Why: mutation_check writes broken copies of app/ and evals/ files to disk and restores them after each test run, so any process that imports during that window can get a broken module.
- tags: evals,mutation,fix-applied

## 2026-11-02 -- evals/mutation_check.py must break a temporary copy of the project (shutil.copytree without .git, .venv, .chroma, .env, reports), never the real files. A rule asking people not to touch files during a run was not enough.
- Expected: The previous rule, run nothing that imports app/ or evals/ during a mutation run, would keep broken files out of the repository.
- Actual: Commit dafea09 (Stage 2 harness) was made while the check was running and captured app/embedder.py with truncate set to true, one of the deliberate breaks. Stopping the run later also left app/generator.py without its output schema.
- Why: The check wrote each break into the real file and restored it after the tests, so anything reading the working tree during that window, including git commit, saw broken code. Fixed in 11608dc and by running the breaks in a copy; the CLAUDE.md rule now says to keep it that way.
- tags: evals,mutation,git,fix-applied

## 2026-11-02 -- A background job dies when the Claude Code session ends, with no completion record. When resuming, read its output file and count finished items before saying anything about it; never assume it completed. Before starting a job longer than about 10 minutes, tell the owner how long it takes and that ending the session stops it.
- Expected: The full 215-break mutation run started in one session would finish and be reported in the next.
- Actual: The session ended and the task notification said 'stopped, no completion record'. The output file showed 78 of 215 breaks done, and the run had to be restarted from the beginning.
- Why: Background shells belong to the session process. The mutation check has no resume point, so a partial run is lost, and the notification alone does not say how far it got.
- tags: background,mutation,logged-only

## 2026-11-02 -- Before running make calibrate, confirm with the owner that every label in evals/annotation/judge_labels.csv is their own judgement, and record who labelled it in reports/judge_calibration.json. Labels pasted as a ready-made block are a sign they may have been drafted by a model.
- Expected: The owner would label the 30 answers themselves, as the README authorship rules require for calibration labels.
- Actual: The labels arrived as a pasted block headed 'Ready to paste', in the style of an AI reviewer. I wrote them in and flagged the question in one line, but the calibration run started before the owner confirmed, and nothing in the result would record who labelled.
- Why: evals/calibrate_judge.py reads only yes or no per row and stores no labeller, so a model-written label set would pass silently and the judge would be graded by a model.
- tags: evals,judge,calibration,fix-applied

## 2026-11-03 -- Stage files by name, never with git add <folder>. Before every commit, run git status --short and check that each new or changed file is one this session made or the owner asked for; anything else gets asked about, not committed.
- Expected: git add reports in commit bfdf625 would stage only the reference and baseline runs made in that session.
- Actual: It also committed reports/holdout/20261102T111832Z-pipeline-holdout.json, a holdout run this session never made or opened. It was found a day later, when the owner named it as the clean reference.
- Why: git add on a folder stages every file in it, and the commit was checked only by its diff stat, which did not list the folder's new files.
- tags: git,holdout,fix-applied

## 2026-11-03 -- evals/annotation/blind_20.csv and any filled copy of it hold 8 holdout questions. In a session that works on the pipeline, score such a sheet only with python -m evals.validate_golden --agreement and read only its summary line. If holdout question text reaches the session anyway, add the ids to EXPOSED_HOLDOUT in evals/exposure.py and a line to Holdout exposure in evals/golden_validation.md the same day.
- Expected: The holdout would stay unseen by the session that tunes the pipeline, as the 2026-10-31 lesson requires.
- Actual: The filled blind sheet was pasted into the chat twice, with questions and short answers for g019, g029, g034, g045, g051, g061, g070 and g075. The exposure was recorded, and holdout results are now reported on all 23 and on the 15 unexposed cases.
- Why: The 2026-10-31 rule names only evals/golden_dataset.jsonl. The blind sheet was not seen as a holdout source, so nobody warned before it was pasted.
- tags: evals,holdout,fix-applied

## 2026-11-03 -- For a narrow judging task, try a small model trained for exactly that task before general models, and judge it only by calibration on real labelled answers. Passing a few obvious hand-made cases says little: granite3-guardian:2b got 4 of 4 obvious cases right and then scored kappa -0.19 on the 30 labels.
- Expected: phi4-mini with Ragas, phi4-mini with claim-check, or granite3-guardian:2b would pass calibration (agreement 0.85, kappa 0.60).
- Actual: All three failed (kappa 0.25, 0.19, -0.19). bespoke-minicheck:7b, trained only to say whether a document supports one sentence, passed at agreement 0.97 and kappa 0.78.
- Why: General 3.8B models do not follow multi-step grounding instructions reliably, and granite was trained on response-level risks, not short claim checks. Obvious one-line cases do not exercise multi-passage contexts.
- tags: evals,judge,models,logged-only

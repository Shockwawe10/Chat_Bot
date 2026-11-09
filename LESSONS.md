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

## 2026-11-04 -- A rule plus a lesson did not stop inline Python: a PreToolUse hook (.claude/hooks/block_inline_python.py) now blocks any Bash command that runs Python from a heredoc or has a python -c longer than 300 characters or spanning lines; write such code to a scratchpad .py file with the Write tool.
- Expected: Python longer than about 15 lines or with nested quotes goes in a scratchpad .py file (CLAUDE.md rule, lesson of 2026-11-02).
- Actual: On 2026-11-04 a bash heredoc edited app/api.py, and a python -c with nested quotes wrote real newlines into a string in evals/mutation_check.py, breaking the file until it was fixed.
- Why: Each edit looked like a small one-off, and nothing stopped the command from running; a rule only works when it is remembered at that moment. Fix applied: the hook, pipe-tested on 11 cases and proven to block a live heredoc command.
- tags: scripts,hooks,fix-applied

## 2026-11-04 -- Commit predictions before any measurement that can decide an experiment, including cheap retrieval-only gold-rank measurements, not only before the long end-to-end run.
- Expected: Every experiment's predictions are committed to reports/experiments.md before it runs.
- Actual: Experiment 7's predictions were given in chat but measured before being written to the file, and experiment 8's retrieval numbers were measured before the write-up; that seconds-long measurement is what decided experiment 7.
- Why: Pre-registration was read as applying to the 30-minute end-to-end run only. Fix applied: CLAUDE.md now requires committed predictions before the retrieval measurement too.
- tags: experiments,pre-registration,fix-applied

## 2026-11-04 -- A parameter that changes results must not have a silent default: Retriever.search(vector, question="") let hybrid search rank with an empty query (19/42 instead of 31/42); hybrid search now raises ValueError without its question. Context from the same session: a long run with the answer check can die with 'timed out waiting for llama-server to start' when three models swap on the 4 GB GPU; rerun the identical command once before changing anything. Two identical runs flipped g056, so one-case differences are noise.
- Expected: The rank-probe script measured hybrid retrieval on the 42 dev cases.
- Actual: It called search(vector) without the question, hybrid fell back to index order, and the first reading was 19/42; a 30-minute eval run was lost to the Ollama load timeout and wrote no file.
- Why: search() took the question as an optional argument with an empty default, and the harness aborts on the first 503 without a partial file. Fix applied in code (commit 871fed0): hybrid search refuses an empty question, with a test and a mutation-check break.
- tags: retrieval,ollama,noise,fix-applied

## 2026-11-05 -- CI's make lint runs ruff check . over the whole repo, including .claude/; before every push run make lint and make test, never a narrower path such as ruff check app evals tests.
- Expected: Every pushed commit passes CI.
- Actual: The hook script .claude/hooks/block_inline_python.py was committed in 1c789af with a ruff error (re.S instead of re.DOTALL), so CI's lint most likely failed from then until 1e38f31; it was found only when ruff check . was run near the end of Stage 3.
- Why: By habit the session ran ruff check app evals tests, which skips the new .claude/ folder. Fix applied: CLAUDE.md now requires make lint and make test before every push.
- tags: ci,lint,fix-applied

## 2026-11-05 -- pip install into the project .venv resolves only the new package's needs and can silently downgrade a shared dependency: deepeval 4.3.1 pulled click down to 8.3.3, below huggingface-hub's click>=8.4.2. Try new packages in a throwaway virtual environment with pip check first.
- Expected: DeepEval could be added for the CI hallucination suite.
- Actual: Installing it into .venv broke huggingface-hub (used by Ragas through datasets and tokenizers); it was uninstalled, requirements.txt reinstalled, and pip check came back clean. The owner chose plain pytest instead.
- Why: DeepEval 4.3.x requires click<8.4.0 and huggingface-hub 2.4.0 requires click>=8.4.2, so they cannot share an environment; the earlier dry run listed click-8.3.3 but did not flag the conflict. Fix applied: CLAUDE.md rule on throwaway environments and pip check.
- tags: dependencies,pip,fix-applied

## 2026-11-05 -- Ollama can update itself during a session (0.40.12 to 0.40.14 on 2026-11-05) and crash a running eval with a CUDA error; every run manifest now records ollama_version from GET /api/version, so a runner change shows up in the results.
- Expected: A full dev run finishes, and its answers can be compared with earlier runs on the same models.
- Actual: One run died with 'llama-server process has terminated ... CUDA error: shared object initialization failed'; the rerun on 0.40.14 gave the same 52 answers as before, but no saved run said which Ollama version produced it.
- Why: The manifest pinned model digests but not the Ollama version. Fix applied: evals/run_evals.py records ollama_version, with a unit test.
- tags: ollama,reproducibility,fix-applied

## 2026-11-06 -- Before giving the owner a PR description, push every commit and name the head commit the PR must contain; after they merge, check it with git merge-base --is-ancestor <head> origin/main.
- Expected: The Stage 3 PR would carry every Stage 3 commit into main.
- Actual: The owner merged PR #5 at 82671db while the AAR fix commit bfc03a4 (CI lint rule, throwaway-venv rule, ollama_version) was still being made, so main lacked it; it was cherry-picked onto stage-4/security as 3152051.
- Why: The PR text was handed over while work on the branch continued, and nothing named the commit the PR had to include. Fix applied: CLAUDE.md rule.
- tags: git,pr,fix-applied

## 2026-11-06 -- A run that measures a rate counts a non-200 reply as an error, reported and left out of the rate, never as a pass or a fail. Likewise, every input that changes the indexed chunks (such as the Stage 4 document scan) must be in fingerprint_inputs.
- Expected: The first attack run would measure every attack; the after run would use a test index built with the scan.
- Actual: evals/attack_run.py counted 8 Ollama 503s as failed attacks, which looked like defended attacks; and the poisoned test index from the before run (97 chunks) was reused after the scan because the fingerprint ignored it, until verify() refused it (expected 92).
- Why: The runner mapped every reply to success or not, so an error fell into not; the fingerprint listed files and settings, not which chunks the scan left out. Fixes applied: retries and an errors list in attack_run, quarantined chunk ids in the fingerprint (d6dae19), and a CLAUDE.md rule on errors.
- tags: measurement,errors,index,fix-applied

## 2026-11-06 -- File tools must write only inside the project or the session scratchpad: .claude/settings.json now sets permissions.blockWritesOutsideWorkingDirectories. Size a tool's workload with the run's own settings before quoting a time: garak sends up to 256 prompts per probe in a run, not the 64 its probe classes show when loaded bare.
- Expected: Scratch files stay in the scratchpad, and the garak scan takes about 452 prompts.
- Actual: A stray Write call created C:\DA27~1\placeholder.txt at the root of C:, which the safety check would not let Claude remove, so the owner deleted it; the first garak scan was about 1,800 prompts and was stopped after 230.
- Why: Nothing stopped a file tool writing outside the working directories; the size check instantiated probes without garak's run config (soft_probe_prompt_cap 256). Fix applied for the writes: the setting, which takes effect from the next session or after /hooks.
- tags: files,tools,garak,fix-applied

## 2026-11-07 -- Durations and causes are claims too: compute a run's duration from its run id (start) and timestamp (end), and write a cause that was not measured separately as not measured. Smoke is about 5 minutes and make nightly about 30 on this machine (2026-11-07 runs).
- Expected: Run times and the cause of the latency rise in the docs would come from saved runs.
- Actual: I wrote smoke 'about 10 minutes' and nightly 'about 50 minutes' into the Makefile, README, thresholds.md and a test docstring; the runs said 5 and about 30. I also wrote that latency rose 'mostly' because of the answer check, which was never measured on its own. All corrected before the push.
- Why: The CLAUDE.md rule covered only count and chunk claims, so durations and causes went unchecked. Fix applied: the rule now covers count, chunk, duration and cause claims, in docstrings too.
- tags: claims,durations,fix-applied

## 2026-11-07 -- A run's timestamp is cut to whole seconds and trace times are not: match a run to runs/traces with evals.phoenix_export.records_for, whose window ends 1 s later, and find the unmatched ids before writing any claim when fewer cases match than the run has.
- Expected: A count of who refused phi4-mini's 39 cases, from the traces of that run.
- Actual: My lookup matched 48 traces for 52 cases; I wrote '38 of 39 refusals have a trace' into reports/drift.md and pushed it. The missing traces (g068, g071, g072, g074) were written in the run's last second. Corrected in drift.md the same day: all 39 have one.
- Why: The window ended at the run's timestamp, which is cut to whole seconds, and I accepted a partial match without asking which cases were missing. Fix applied: a CLAUDE.md rule, plus records_for and its test test_a_request_in_the_run_s_last_second_is_inside_the_window.
- tags: traces,claims,fix-applied

## 2026-11-07 -- A server-type tool gets its own venv, the newest release at least 14 days old, and a netstat -ano check after its first start. Phoenix 20.26.0 by default served its UI on 0.0.0.0, always binds gRPC 4317 to every interface, and had telemetry and a bash-capable AI agent on; set PHOENIX_HOST=127.0.0.1, PHOENIX_TELEMETRY_ENABLED=false, PHOENIX_DISABLE_AGENT_ASSISTANT=true, PHOENIX_AGENTS_DISABLE_BASH=true (make phoenix) and stop it when done.
- Expected: Phoenix would run locally and privately for viewing traces.
- Actual: Its first start listened on 0.0.0.0:6006 and [::]:4317 with telemetry and its AI agent on; I found this only from its startup log and netstat, then restarted it local-only with the agent off. The gRPC bind is hardcoded ([::]:{port} in phoenix/server/grpc_server.py), so it remains, documented in the README.
- Why: The package rule checked only dependency conflicts (pip check), not what a tool does when it runs, nor how new a release is (Phoenix 21.0.0 was 8 days old). Fix applied: the CLAUDE.md package rule now covers release age, a separate venv for servers, the netstat check, and telemetry and agents off.
- tags: dependencies,security,phoenix,fix-applied

## 2026-11-09 -- A rule did not stop commits past a failed lint: .claude/hooks/lint_before_commit.py blocks any Bash command that runs git commit while ruff check . fails. Never chain make lint into git commit with ';' or through '| tail'.
- Expected: Every commit passes make lint, as CLAUDE.md requires before every push.
- Actual: 6fa7ccb and 24bcc6e were committed with ruff errors (import order, an unused variable). 'make lint | tail -1 && git commit' let tail hide lint's exit code; 'make lint; git commit' ran the commit after the failure. Both were fixed before any push.
- Why: Nothing stopped a commit mechanically, and the lint check and the commit sat in one command. Fix applied: the hook, unit-tested (13 tests) and pipe-tested on a real lint error. Its registration in .claude/settings.json is the owner's edit, because blockWritesOutsideWorkingDirectories blocks Claude from writing settings files.
- tags: lint,git,hooks,fix-applied

## 2026-11-09 -- When two runs in a row die with 'CUDA error: shared object initialization failed' loading bespoke-minicheck, stop and ask the owner to restart Windows. Unloading models (ollama stop), restarting Ollama and an in-run retry after 10 s did not fix it on 2026-11-09.
- Expected: make smoke runs on the 4 GB GPU as it did for dozens of swaps on 2026-11-07.
- Actual: Five smoke runs on 2026-11-09 crashed when Ollama loaded minicheck after evicting qwen3: 2.8 GiB free for a 5.4 GiB model, 12/33 layers offloaded, then the CUDA error. One Ollama restart helped once; after a Windows restart the GPU idled at 259 MiB (about 700 MiB before) and every run passed.
- Why: Ollama 0.40.15 and the driver were unchanged since 2026-11-07, so the cause looks like the GPU driver state since the 2026-11-08 boot. That was not measured beyond the free-memory numbers. Fix applied: a CLAUDE.md rule; the in-run retry (evals/run_evals.py) stays for single crashes.
- tags: ollama,gpu,crash,fix-applied

## 2026-11-09 -- An oracle's replies are not known-correct answers: check every reply_excludes word against the real replies of the last committed agent dev run, which now keep their turns (never holdout).
- Expected: The agent scorer, proven on an oracle, reference systems and near-miss arguments, would score correct replies as passes.
- Actual: a033 excluded 'Handover' to catch the injected 'project is complete'; the true reply 'the next stage is Handover' failed. It changed experiment A3's pre-registered decision and needed the owner's ruling and two re-runs.
- Why: The CLAUDE.md scorer rule asks for known-correct answers from a saved run, but agent run files did not store replies, so only the oracle's own replies were ever checked. Fix applied: agent_eval keeps dev and attack turns, a CLAUDE.md rule, and a check of 27 cases' excluded words against the 2026-11-09 runs: 0 suspects.
- tags: evals,scoring,agent,fix-applied

## 2026-11-09 -- Two pytest files must not share a name across tests/ folders: tests/ai/test_agent.py beside tests/unit/test_agent.py stopped make test at collection (exit 2). Name CI suites after what they check, such as test_agent_runs.py.
- Expected: A new CI suite tests/ai/test_agent.py would run beside the unit tests.
- Actual: Each file passed alone; make test failed with 'ERROR tests/unit/test_agent.py ... 1 error during collection'. Renamed to tests/ai/test_agent_runs.py before any push.
- Why: The tests folders have no __init__.py, so pytest imports test modules by base name and two files with the same name collide. make test caught it, so no fix is needed beyond the rename.
- tags: pytest,tests,logged-only

## 2026-11-09 -- On a 4B model, prefer code checks to prompt sentences once the obvious prompt fix is in: A4's one booking sentence fixed a022 but broke unrelated a018, while code checks A2 and A5 broke nothing. And a dev score is not a holdout score: the agent passed 30/35 dev cases but 3/10 of the owner's holdout.
- Expected: Each prompt round would move only the cases it targets, and the dev pass rate would carry to unseen cases.
- Actual: A4 (prompt v3) fixed a022 and lost a018, which then asked for the corrosion class instead of the customer's name; it was not kept. The agent holdout (run 20261109T143452Z) passed 3/10 with tool choice 9/10; 5 of 7 failed cases failed 'reply includes'.
- Why: Small models are sensitive to any prompt change, and v2's booking rule was written from dev failures. The holdout gap's cause is unknown to the session, which may not read the cases; the owner can. Logged only: the decision rule (no pass may be lost) already caught A4.
- tags: agent,prompts,holdout,logged-only

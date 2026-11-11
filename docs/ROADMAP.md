# Roadmap

The plan the project was built by, stage by stage, with what each stage delivered and how it was checked. Moved out of the README on 2026-11-11; the README keeps a one-table summary.

About 8 weeks at 25–35 hours a week, in stages 0 to 8. Every stage ends with something visible in the repository, and with exit criteria that can be checked.

## Stage 0. Setup and demo domain (week 1)

**Goal:** a working environment and the knowledge base the chatbot will use.

- [ ] Python, venv, Git, Claude Code, Ollama with a small model, `.env`
- [ ] Initial commit, push to GitHub, protect `main`
- [x] `GLOSSARY.md`: mounting system types (ground, roof), corrosion protection classes, wind and snow load, project stages (site survey, design, supply, installation)
- [x] 20–30 knowledge base documents about the fictional company: services, cooperation stages, mounting systems, corrosion protection, what a customer must provide for a quote
- [x] Deliberate traps: two similar systems with different corrosion classes, exact numbers, a price question with no answer in the KB
- [x] First data tests in `tests/data`: every KB document has valid front matter

**Exit criteria:** `pytest` runs green in a clean venv; at least 20 KB documents with front matter; at least 15 glossary terms.

## Stage 1. Baseline RAG (weeks 1–2)

**Goal:** a simple chatbot that answers with sources. Its weak spots will be found by evals later.

- [x] Chunking, embeddings and a verified Chroma index
- [x] Top-k retrieval and generation
- [x] `POST /ask` returning answer, sources and timing
- [x] Unit tests for the chunker: property tests for its invariants and edge-case fixtures
- [x] API contract tests: status codes, schema, empty and very long input
- [x] One end-to-end integration test, with fakes for CI and with the real models locally
- [x] Minimal GitHub Actions workflow: lint and tests on every push, so each PR's commits are checked

**Exit criteria:** `make run` and `make test` work from a clean clone; tests run in CI; 10 manual sanity questions recorded in `LEARNING_LOG.md`.

## Stage 2. Golden dataset and eval harness (weeks 2–3)

**Goal:** one command that measures the chatbot's quality. The core of the project.

- [x] 75 cases in `golden_dataset.jsonl` with a stratified dev / holdout split and a 21-case smoke set
- [x] `run_evals.py`: runs the dataset, saves answers, contexts (as chunk ids, with the index fingerprint), metrics and the run manifest
- [x] `render_results.py` and `make results`: Results table generated from `reports/latest.json`
- [x] Retrieval metrics in my own code: hit rate@k, MRR
- [x] Answer metrics with Ragas: faithfulness, answer relevancy, context precision, context recall (shown only after the judge passes calibration)
- [x] Numeric fidelity check based on `must_include`, with normalisation
- [x] Judge calibration on 30 hand-labeled answers: agreement and Cohen's kappa (faithfulness: `bespoke-minicheck:7b` passed after 3 judges failed; to be confirmed on fresh labels)

**Exit criteria:** `make eval` produces a manifest, `reports/latest.json` and a row in `history.csv`; the baseline appears in [Results](../README.md#results) through `make results`; judge agreement and kappa are measured and reported.

## Stage 3. Hallucinations and experiments (weeks 3–4)

**Goal:** tests that catch invented answers, and proof that changes improve the chatbot.

- [x] Hallucination suite in CI (`tests/ai`, gates in `evals/gates.py`): out-of-scope refusals, unsupported language, false premises, numeric fidelity, citation check (the cited source really contains the claim). Plain pytest, not DeepEval: DeepEval 4.3 needs `click<8.4`, while Ragas's `huggingface-hub` needs `click>=8.4.2`. CI has no model for DeepEval's LLM metrics anyway, so the checks are code either way
- [x] Experiments on the dev set: top-k and prompt version, plus an answer check, hybrid search and example questions per chunk (8 experiments in `reports/experiments.md`). Chunk size was not run
- [x] Error analysis: read every failed case, group failures by cause (retrieval miss, invented fact, incomplete answer), count them. `reports/error_analysis.md`: 30 of 52 fail at the baseline, 21 at the end of the stage

**Exit criteria:** at least 3 experiments compared in `reports/experiments.md`; the winning setup confirmed once on holdout; hallucination suite runs in CI; error categories with counts.

**Status: done (2026-11-05).** 8 experiments compared; the winner (prompt v5, top-k 8, example questions per chunk, answer check) confirmed on holdout; English-only reply built; hallucination suite in `tests/ai`; failures 30 → 21 of 52 dev cases, with causes counted in `reports/error_analysis.md`.

## Stage 4. Security: prompt injection and jailbreak (weeks 4–5)

**Goal:** attack the chatbot, fix what breaks, show before and after.

- [x] Own tests mapped to OWASP Top 10 for LLM Applications 2025: LLM01 (direct injection, and indirect injection through a poisoned KB document), LLM07 (system prompt leakage), LLM08 (vector search weaknesses). 42 attacks in `evals/attacks.jsonl`, scored by code (`python -m evals.attack_run`)
- [x] promptfoo red teaming: 96 attacks from 6 plugins, written and graded by a local model (`make redteam`). The grader failed 6; read by hand, none is a real failure
- [x] garak scan of the model: the bare qwen3 prints an injected line in 118 of 192 prompt-injection attempts and repeats a planted instruction from a document in 22 of 64. Encodings 2 of 192, role-play jailbreaks 0 of 4
- [x] Defenses: input filtering, separation of instructions and data in the prompt, output checks. A scan of documents before indexing and an answer guard (`app/guards.py`). Instructions and data were already apart in the prompt
- [x] Re-run all attacks after the fixes: 3/59 attempts worked before (all indirect injection), 0/61 after. CI gates the committed run (`tests/ai/test_security.py`)

Personal data leakage (LLM02) needs the agent and its customer data, so it is tested in Stage 6.

**Exit criteria:** `reports/SECURITY_REPORT.md` with an OWASP → tests → before/after table; at least one fixed vulnerability guarded by a regression test.

**Status: done (2026-11-06).** 42 own attacks: 3 of 59 attempts worked before the defences (all indirect injection), 0 of 61 after, with the dev answers unchanged. promptfoo: 96 attacks, no real failure. garak on the bare model: prompt injection works 61% of the time, which shows the defences carry the app. Two weaknesses fixed and guarded by regression tests and a CI gate: indirect injection and the prompt leak.

## Stage 5. CI/CD, regression and drift (weeks 5–6)

**Goal:** quality is checked automatically on every change.

- [x] Extend the PR workflow with the smoke eval and its gates (per case against an accepted reference; every run stamped and checked for freshness)
- [x] Nightly or manual full dev eval and red teaming (`make nightly`: full dev eval and the attack set; promptfoo and garak by hand)
- [x] Manual end-of-stage workflow for the holdout eval (`make holdout` and the "Holdout" GitHub workflow)
- [x] Drift: same evals on two models or two prompt versions, metric history chart (Ollama pinned; qwen3 against phi4-mini in `reports/drift.md`; `reports/history.svg`)
- [x] Tracing with Arize Phoenix (`make phoenix`, `evals/phoenix_export.py`; a failed case in [Tracing with Arize Phoenix](../README.md#tracing-with-arize-phoenix))

**Exit criteria:** a **canary PR** with a deliberately broken prompt fails CI, and the failure is linked in the README ([#7](https://github.com/Shockwawe10/Chat_Bot/pull/7), see [Canary](../README.md#canary-a-broken-prompt-fails-ci)); `reports/drift.md` compares two models; a trace screenshot of one failed case.

**Status: done (2026-11-07).**
- **CI:** CI checks committed runs, since the models run on the local GPU. Every run is stamped and must match its commit. The smoke run is gated per case against an accepted reference.
- **Drift:** Ollama is pinned after an update silently made one answer false. phi4-mini kept every safety result but refused 39 of 42 answerable questions.
- **Tooling:** a metric history chart, Phoenix traces of failed cases, and a manual holdout workflow.
- **Canary:** the canary PR fails CI exactly as predicted, and exposed two test weaknesses (F5, F6), now fixed.
- **Final runs:** the dev answers are identical to the previous run in 52/52 cases, and 0/62 attacks worked. The holdout run (`20261107T151637Z-pipeline-holdout`, 23 cases) has 8 behaviour failures against 10 in the Stage 3 holdout run, 0/3 out-of-scope answered and no errors.

## Stage 6. MCP agent with tools (weeks 6–7)

**Goal:** an agent that also takes requests and works with company data. The tools imitate a CRM and a project tracking system.

- [x] Demo data: `products.csv`, `projects.csv`, `leads.csv`, `make seed` builds `data/app.db` with `products`, `projects`, `leads` and `site_surveys`
- [x] Synthetic customer contacts in `leads` (`.test` domains, 555-01xx numbers, `-Test` names), used as targets for leakage tests
- [x] MCP server tools (`mcp_server/server.py`, official MCP Python SDK 2.3.0 over stdio; the checks in `mcp_server/tools.py`):
  - `create_lead(company, region, power_kw, mount_type, contact_name, email, phone)`
  - `get_project_status(project_id)`
  - `find_product(mount_type, corrosion_class)`
  - `book_site_survey(project_id, date)`, which only proposes a date: the customer's next message confirms it, through code the model cannot call
- [x] `evals/agent_cases.jsonl` with at least 30 cases (35 dev, `python -m evals.agent_eval`): correct tool, correct arguments, asks for missing required data instead of inventing it, handles a non-existent project. About 10 holdout cases are written by the owner (`evals/AGENT_HOLDOUT.md`), never seen by the session that tunes the agent
- [x] Excessive agency and misinformation (LLM06, LLM09): no booking without confirmation, no price or deadline that is not in the KB (`evals/agent_attacks.jsonl`: 0/5 and 0/4 attacks worked)
- [x] Personal data leakage (LLM02): one customer's contact never appears in another customer's answer (0/5 attacks worked; a leak count on every agent case)
- [x] Indirect injection through a tool result: a malicious instruction in a demo project comment (P-1006; the model obeyed it 3/3 until notes that address the assistant were withheld, see `reports/SECURITY_REPORT.md`)
- [x] Database tests: a saved lead matches what the customer said (`test_a_saved_lead_matches_what_the_customer_said`)
- [x] Agent tests added to the PR workflow; full agent cases added to the nightly run (`tests/ai/test_agent_runs.py` on every push; `make nightly` runs both agent sets)

**Exit criteria:** tool selection accuracy measured on at least 30 agent cases; 0 unconfirmed bookings; 0 PII leaks; indirect injection test in the suite.

**Status: done (2026-11-09).**
- **Built:** demo company data with fake contacts (`make seed`); four MCP tools over stdio; the `/chat` agent. It reuses the checked RAG answer and confirms bookings in code. A reply guard stops other customers' details, prices and prompt quotes. Code checks refuse invented lead values and survey dates not on record.
- **Measured:** tool selection 27/31 on 35 dev cases, with 30/35 passing after five experiments (A1 to A5, `reports/experiments.md`).
- **Attacked:** 0 of 22 attacks worked, with 0 unconfirmed bookings and 0 leaks. The model obeyed P-1006's planted note until notes that address the assistant were withheld (`reports/SECURITY_REPORT.md`).
- **Gated:** every push checks the committed agent runs.
- **Holdout:** the owner's 10 agent cases: **3/10 passed** against 30/35 on dev. Tool choice held at 9/10 and the safety counts stayed at 0. Most failures are on "the reply includes the expected words", and the cause is not yet known.

## Stage 7. UI, Playwright and cloud (weeks 7–8)

**Goal:** a live demo and browser tests.

- [x] Streamlit UI on `/chat` (`ui/app.py`, `make ui`): question, answer, sources, and booking proposals with the confirmation step
- [x] Playwright tests (`tests/e2e`, `make e2e`, on every push): happy path, empty input, long answer, API error, sources displayed, plus the API being down, the booking confirmation and a new conversation, against a stand-in API. `python -m tests.e2e.breaks` shows each test catching its break
- [x] Dockerfile and a compose file (`make docker-up`): the API and the chat window on `127.0.0.1:8501`, using the desktop Ollama the evals ran on, which the API checks is the pinned version; fresh database and index on every start. With it, the 21 smoke answers came out word for word the same as the committed run (`reports/runs/20261110T114458Z-http-dev-smoke-docker-desktop-ollama.json`). Ollama in Docker on the GPU is optional (`docker-compose.ollama.yml`, `make docker-up-ollama`): 20 of 21 the same, g032 refused, cause not measured (`reports/runs/20261110T112859Z-http-dev-smoke-docker.json`). CI builds the image from a clean clone and imports and seeds it
- [ ] Optional public link from the owner's PC. **Postponed** (owner's decision, 2026-11-10). The plan changed from a tunnel to a Telegram bot, which polls Telegram and so opens no port; it is written and tested against a stand-in Telegram (per-chat and hourly limits, optional allowed users, the token never logged) and parked on the `later/telegram-bot` branch until a bot token is set up. The database reset on each start is already in the Docker demo

**Exit criteria:** E2E suite green in CI; Docker image builds from a clean clone; a README [demo section](../README.md#demo) with a screenshot and the command to run it. The live link is postponed (owner's decision, 2026-11-10): the Telegram bot that would give it is parked on the `later/telegram-bot` branch.

**Changed on 2026-11-10 (owner's decision): local Docker instead of AWS.** The demo would need a GPU server: about $0.53 per hour in the US while it runs, plus about $4.00 a month for its disk, or $391.63 a month if left on (third-party price trackers, November 2026). A cheap server with the Claude API instead would make the demo a different system from the one the evals measured. So the demo runs in Docker on the owner's PC, with an optional tunnel for a public link while it is on.

## Stage 8. Packaging (week 8)

**Goal:** a recruiter understands the project in 2 minutes; a technical interviewer finds the depth.

- [x] Final full run and holdout run; Results table regenerated with `make results`. The final runs are the Stage 7 end-of-stage runs (nightly at `b09571a`, holdout at `08f32ca`): Stage 8 changed nothing that shapes an answer, and those runs still pass CI's freshness check, so a second identical run (about 70 minutes) and a second look at the holdout were skipped (owner's decision, 2026-11-11). `make results` now also fills the agent rows from the committed agent runs
- [x] [Findings](../README.md#findings) section with the 5–7 most interesting defects: seven told as short stories, eleven in the table, one of them (F7's negation blind spot) still open
- [x] Demo GIF at the top of the README (`docs/demo.gif`, 17 s, 0.39 MB, remade with `python docs/make_demo_gif.py`)
- [ ] 3–5 minute demo video: a question, an eval run, a red CI after a bad change. **Waiting on the owner:** the shot list and narration are in `docs/demo_video_script.md`
- [ ] A short post about one finding. **Waiting on the owner:** the draft, about the Ollama update that put a false answer past every gate, is in `docs/posts/ollama-update-false-answer.md`
- [x] Learning log entries for Stages 3 to 7, drafted from the saved records and marked as not reviewed (the Definition of Done asks for one per piece of work)

**Exit criteria:** someone else (or a clean virtual machine) follows [Quick start](../README.md#quick-start) and gets a working chatbot and an eval report without my help.

**Status: done except the video and the post, which wait on the owner (2026-11-11).** The exit criterion was met with a stand-in for a clean machine: two fresh clones on the owner's PC. The old Quick start failed in 3 places; the rewritten one passed every step, including 21/21 smoke answers identical to the committed run (`reports/quickstart_test.md`). A truly different computer was not tried.

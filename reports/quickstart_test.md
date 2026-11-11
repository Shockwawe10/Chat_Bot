# Quick start test (Stage 8 exit criterion)

The Stage 8 exit criterion: someone else, or a clean machine, follows Quick start and gets a working chatbot and an eval report without help. This file records the stand-in for that: a fresh clone from GitHub in an empty folder, with a new venv, following the README word for word. Done by Claude Code on 2026-11-11 on the owner's PC (Windows 11, Git Bash, GNU Make, RTX 3050 Ti Laptop 4 GB, Ollama 0.40.15).

## What a fresh clone cannot show

It ran on the PC where the project was built, so some things were already there:

- **The models.** They were not pulled again. Instead, the registry was asked what `ollama pull` gives today for each tag: the manifest digest of `qwen3:4b-instruct`, `nomic-embed-text:v1.5` and `bespoke-minicheck:7b` was the one pinned in `.env.example` for all three.
- **pip's cache.** 193 of 196 packages came from it in the first test, so a new machine's install takes longer.
- **Playwright's browser.** `python -m playwright install chromium` took 3 s because Chromium was already installed for this user.
- **Python 3.11, Docker Desktop and Ollama** were already installed.

A machine without a GPU was not tried.

## Test 1: the old Quick start (commit `fcdc40e`)

| Step | Result |
| --- | --- |
| `python -m venv .venv` | the PC's default `python` is 3.8.2; the venv was made with `py -3.11`, as a note below the commands says |
| `pip install -r requirements.txt` | 247 s, `pip check` clean (193 packages cached, 3 downloaded) |
| `ollama pull ...` | **lists `phi4-mini:3.8b` (no longer used) and not `bespoke-minicheck:7b` (needed by the answer check and the judge)** |
| `pytest` | 1561 passed, 56 s |
| `make ingest` | 91 chunks, index `kb_e5c2f46128e9` (the same as the project's), 7 s |
| `make run`, then `POST /ask` | HTTP 200, 18.7 s; the RF-2 answer word for word as in the smoke run |
| `make run`, then `POST /chat` | **HTTP 500: `sqlite3.OperationalError: no such table: leads`**. `make seed` is listed later, under Stage 6; the failed call left an empty `data/app.db` behind |
| `make seed`, then `POST /chat` again | HTTP 200, 5.7 s; `get_project_status` called, P-1001's status |
| `make eval-smoke` | 303 s, 0 errors; **21/21 answers identical** to the committed smoke run `20261110T132149Z-pipeline-dev-smoke` |
| `make lint` | passed |
| `make docker-up` | 905 s, both containers healthy, the chat window answered two questions in a browser. 844 s of it was `pip install` inside the image (no Docker cache for the clone) |

## Test 2: the new Quick start (commit `c3c66bb`)

Quick start was rewritten from test 1 (three paths, the three models, `make seed` before `make run`, `py -3.11`, Git Bash activation, the Playwright install). A second fresh clone then followed only the new commands, from the develop and evaluate paths. `git clone` took the default branch, `main` (`fcdc40e`): the code is the same as `c3c66bb`, only the README differs.

| Step | Result |
| --- | --- |
| `git clone`, `py -3.11 -m venv .venv`, `pip install -r requirements.txt` | 4 s, 11 s, 240 s |
| `cp .env.example .env`, `make seed`, `make ingest` | 0 s, 1 s, 8 s |
| `make test` | 1561 passed, 54 s |
| `make run`, then `POST /chat` and `POST /ask` | HTTP 200 in 12.0 s and 18.8 s |
| `make eval-smoke` | 320 s, 0 errors; **21/21 answers identical** to the committed smoke run |
| `python -m playwright install chromium`, `make e2e` | 3 s, 9 passed |

Every step passed. The Docker path of the new Quick start uses the same `make docker-up` as test 1.

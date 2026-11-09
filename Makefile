# On Windows, run these from WSL or Git Bash with GNU Make installed.
ifeq ($(OS),Windows_NT)
PYTHON ?= .venv/Scripts/python
PHOENIX_BIN = .venv-phoenix/Scripts
else
PYTHON ?= .venv/bin/python
PHOENIX_BIN = .venv-phoenix/bin
endif

.PHONY: ingest seed run test test-real lint mutation eval eval-smoke smoke smoke-accept nightly results chart holdout phoenix agent-eval agent-attacks agent-accept judge-labels calibrate attacks redteam

# Build data/app.db from data/products.csv, leads.csv and projects.csv (drops leads the agent saved).
seed:
	$(PYTHON) -m mcp_server.seed

ingest:
	$(PYTHON) -m app.index build

run:
	$(PYTHON) -m uvicorn app.api:create_default_app --factory --port 8000

test:
	$(PYTHON) -m pytest

test-real:
	$(PYTHON) -m pytest -m real

lint:
	$(PYTHON) -m ruff check .

mutation:
	$(PYTHON) -m evals.mutation_check

eval:
	$(PYTHON) -m evals.run_evals

eval-smoke:
	$(PYTHON) -m evals.run_evals --smoke

# The run CI checks on every push: 21 smoke cases, about 5 minutes (reports/smoke/latest.json).
smoke:
	$(PYTHON) -m evals.run_evals --smoke

# Accept the latest smoke run as the per-case reference. Only on purpose, with the reason in the PR.
smoke-accept:
	$(PYTHON) -c "import shutil; shutil.copyfile('reports/smoke/latest.json', 'reports/smoke/reference.json')"

# The full dev eval and the attack set (about 30 minutes on 2026-11-07), then the agent dev cases and attacks
# (reports/latest.json, reports/security/latest.json, reports/agent/latest.json, reports/agent/attacks/latest.json).
nightly:
	$(PYTHON) -m evals.run_evals
	$(PYTHON) -m evals.attack_run --label nightly
	$(PYTHON) -m evals.agent_eval --label nightly
	$(PYTHON) -m evals.agent_eval --split attack --label nightly

results:
	$(PYTHON) -m evals.render_results

# End of a stage only, after make nightly on the same commit: the holdout run, then its check.
# Prints counts and case ids, never question text (evals/holdout.py).
holdout:
	$(PYTHON) -m evals.run_evals --split holdout --allow-holdout
	$(PYTHON) -m evals.holdout

# The agent eval on the dev cases (reports/agent/latest.json), checked by CI on every push
# (tests/ai/test_agent.py). Needs Ollama, not the index.
agent-eval:
	$(PYTHON) -m evals.agent_eval

# The 22 attacks on the agent (reports/agent/attacks/latest.json), checked by CI on every push.
agent-attacks:
	$(PYTHON) -m evals.agent_eval --split attack

# Accept the latest agent dev run as the per-case reference. Only on purpose, with the reason in the PR.
agent-accept:
	$(PYTHON) -c "import shutil; shutil.copyfile('reports/agent/latest.json', 'reports/agent/reference.json')"

# Redraw reports/history.svg from evals/history.csv (run_evals does it after every full dev run).
chart:
	$(PYTHON) -m evals.history_chart

# Phoenix tracing UI at http://127.0.0.1:6006, in its own venv (about 750 MB, made on first use).
# Then: python -m evals.phoenix_export reports/latest.json. Stop it with Ctrl+C when done: its
# gRPC receiver (port 4317) listens on every network interface, and Phoenix has no setting for that.
phoenix:
	$(PHOENIX_BIN)/python -c "import phoenix" 2>/dev/null || ( $(PYTHON) -m venv .venv-phoenix && $(PHOENIX_BIN)/python -m pip install arize-phoenix==20.26.0 && $(PHOENIX_BIN)/python -m pip check )
	PHOENIX_HOST=127.0.0.1 PHOENIX_WORKING_DIR=.phoenix PHOENIX_TELEMETRY_ENABLED=false \
	PHOENIX_DISABLE_AGENT_ASSISTANT=true PHOENIX_AGENTS_DISABLE_BASH=true $(PHOENIX_BIN)/phoenix serve

judge-labels:
	$(PYTHON) -m evals.calibrate_judge --make-labels

calibrate:
	$(PYTHON) -m evals.calibrate_judge --labelled-by "$(LABELLED_BY)"

attacks:
	$(PYTHON) -m evals.attack_run

# promptfoo red teaming with local models only; needs the API running (make run) and Node.js >= 22.22.
PROMPTFOO = PROMPTFOO_DISABLE_TELEMETRY=1 PROMPTFOO_DISABLE_REMOTE_GENERATION=true PROMPTFOO_DISABLE_SHARING=1 PROMPTFOO_DISABLE_UPDATE=1 npx -y promptfoo@0.124.1

redteam:
	$(PROMPTFOO) redteam generate -c promptfooconfig.yaml -o runs/redteam.yaml --force
	$(PROMPTFOO) redteam eval -c runs/redteam.yaml -o reports/security/promptfoo-latest.json --no-cache -j 1
	$(PYTHON) -m evals.promptfoo_clean reports/security/promptfoo-latest.json

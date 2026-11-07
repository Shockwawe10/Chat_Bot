# On Windows, run these from WSL or Git Bash with GNU Make installed.
ifeq ($(OS),Windows_NT)
PYTHON ?= .venv/Scripts/python
else
PYTHON ?= .venv/bin/python
endif

.PHONY: ingest run test test-real lint mutation eval eval-smoke smoke smoke-accept nightly results chart judge-labels calibrate attacks redteam

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

# The full dev eval and the attack set, about 30 minutes (reports/latest.json, reports/security/latest.json).
nightly:
	$(PYTHON) -m evals.run_evals
	$(PYTHON) -m evals.attack_run --label nightly

results:
	$(PYTHON) -m evals.render_results

# Redraw reports/history.svg from evals/history.csv (run_evals does it after every full dev run).
chart:
	$(PYTHON) -m evals.history_chart

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

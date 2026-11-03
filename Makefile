# On Windows, run these from WSL or Git Bash with GNU Make installed.
ifeq ($(OS),Windows_NT)
PYTHON ?= .venv/Scripts/python
else
PYTHON ?= .venv/bin/python
endif

.PHONY: ingest run test test-real lint mutation eval eval-smoke results judge-labels calibrate

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

results:
	$(PYTHON) -m evals.render_results

judge-labels:
	$(PYTHON) -m evals.calibrate_judge --make-labels

calibrate:
	$(PYTHON) -m evals.calibrate_judge --labelled-by "$(LABELLED_BY)"

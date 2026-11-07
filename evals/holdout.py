"""The end-of-stage holdout check: is the committed holdout run usable, and what did it show, as counts and ids.

Run it with make holdout (the run, then this check) or python -m evals.holdout (the check alone).
The manual GitHub workflow "Holdout" runs the check on the committed run: CI has no model, so
the run itself is made on the local GPU, like every other run (README, CI gates).

A holdout run confirms the setup once, at the end of a stage. It is only worth reading if it is:
- a full pipeline run of the holdout split, not an experiment or a smoke run;
- about this commit, on the pinned Ollama (evals/freshness.py);
- of the same setup as the committed dev run (reports/latest.json), so the two can be compared;
- of every reviewed holdout case in the current dataset version.

Output is counts and case ids only, never question or answer text (CLAUDE.md). Exposed holdout
cases are counted twice: with and without them (evals/exposure.py).
"""

import json
import sys

from app.settings import ROOT
from evals.exposure import EXPOSED_HOLDOUT, format_report
from evals.freshness import problems as freshness_problems
from evals.validate_golden import load_dataset

HOLDOUT_LATEST = ROOT / "reports" / "holdout" / "latest.json"
DEV_LATEST = ROOT / "reports" / "latest.json"


def holdout_ids(cases):
    """Ids of the reviewed holdout cases, and the dataset version. Ids only: no case text is read out."""
    ids = sorted(c["id"] for c in cases if c["split"] == "holdout" and c.get("reviewed_by"))
    return ids, cases[0]["dataset_version"]


def problems(report, dev, cases, root=ROOT, env_example=None):
    """Why a holdout run cannot confirm the committed setup, or an empty list."""
    found = []
    if report.get("split") != "holdout" or report.get("smoke") or report.get("experiment"):
        found.append("not a full holdout run (experiments and smoke runs never confirm a setup)")
    if report.get("system") != "pipeline":
        found.append(f"not the pipeline: {report.get('system')}")
    found += freshness_problems(report, root, env_example)
    if report.get("inputs_sha256") != dev.get("inputs_sha256") or report.get("settings") != dev.get("settings"):
        found.append("not the setup of reports/latest.json; run make nightly and make holdout on the same commit")
    ids, version = holdout_ids(cases)
    if report.get("dataset_version") != version:
        found.append(f"dataset {report.get('dataset_version')}, but the dataset is {version}")
    ran = sorted(c["id"] for c in report.get("cases", []))
    if ran != ids:
        found.append(f"ran {len(ran)} cases, the dataset has {len(ids)} reviewed holdout cases")
    if "exposure" not in report.get("metrics", {}):
        found.append("no exposure counts: the run is older than evals/exposure.py")
    return found


def failed_ids(report):
    """{what failed: [ids]}, with exposed cases marked *. Ids only."""

    def mark(case_id):
        return case_id + ("*" if case_id in EXPOSED_HOLDOUT else "")

    cases = report.get("cases", [])
    return {
        "behaviour failed": [mark(c["id"]) for c in cases if c.get("behaviour_ok") is False],
        "gold not retrieved": [mark(c["id"]) for c in cases if c.get("hit") is False],
        "required fact missing": [mark(c["id"]) for c in cases if c.get("missing_facts")],
        "non-200 reply (an error, not counted)": [mark(c["id"]) for c in cases if c.get("status") not in (None, 200)],
    }


def summary(report):
    lines = [
        f"holdout run {report['run_id']} at {report.get('git_sha', '')[:7]}, Ollama {report.get('ollama_version')}",
        *format_report(report["metrics"]["exposure"]),
    ]
    for what, ids in failed_ids(report).items():
        lines.append(f"  {what}: {len(ids)} {' '.join(ids)}".rstrip())
    lines.append("  * = exposed holdout case (evals/exposure.py)")
    return lines


def main(argv=None):
    if not HOLDOUT_LATEST.exists():
        print("no committed holdout run: make holdout at the end of a stage")
        return 1
    report = json.loads(HOLDOUT_LATEST.read_text(encoding="utf-8"))
    dev = json.loads(DEV_LATEST.read_text(encoding="utf-8"))
    found = problems(report, dev, load_dataset())
    for problem in found:
        print(f"PROBLEM: {problem}")
    if "exposure" in report.get("metrics", {}):
        print("\n".join(summary(report)))
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())

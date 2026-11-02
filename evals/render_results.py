"""Write the Results table in README.md from reports/latest.json and reports/baseline.json.

    python -m evals.render_results          # rewrite the table (make results)
    python -m evals.render_results --check  # exit 1 if README.md is out of date

Only the Baseline and Current cells of measured metrics change. A metric with no
value stays a dash, so nothing in the table is typed by hand.
"""

import argparse
import json
import re
import sys

from app.settings import ROOT

README = ROOT / "README.md"
REPORTS = ROOT / "reports"
START, END = "<!-- results:start -->", "<!-- results:end -->"
DASH = "—"


def ratio(key):
    def cell(report):
        value = report["metrics"].get(key)
        return DASH if value is None else f"{value:.2f}"

    return cell


def latency(report):
    value = report["metrics"].get("latency_p95_ms")
    if value is None:
        return DASH
    return f"{value / 1000:.1f} s, ${report['total_cost'] / max(report['cases_run'], 1):.2f}"


ROWS = {  # first cell of a README row: how to fill its value cells
    "Hit rate@5": ratio("hit_rate"),
    "MRR": ratio("mrr"),
    "Faithfulness": ratio("faithfulness"),
    "Answer relevancy": ratio("answer_relevancy"),
    "Context precision": ratio("context_precision"),
    "Context recall": ratio("context_recall"),
    "Refusal accuracy": ratio("refusal_accuracy"),
    "Numeric fidelity": ratio("numeric_fidelity"),
    "Latency p95, cost per query": latency,
}


def load(name, reports_dir=REPORTS):
    path = reports_dir / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def source_line(baseline, current):
    def describe(report):
        return f"`{report['run_id']}` at `{report['git_sha'][:7]}`, dataset {report['dataset_version']}"

    parts = []
    if baseline:
        parts.append(f"Baseline: {describe(baseline)}.")
    if current:
        parts.append(f"Current: {describe(current)}.")
    return " ".join(parts)


def render(text, baseline, current):
    if START not in text or END not in text:
        raise SystemExit("README.md has no results markers")
    head, rest = text.split(START, 1)
    block, tail = rest.split(END, 1)
    if current and current["top_k"] != 5:
        raise SystemExit(f"the table reports hit rate@5, but the run used top_k={current['top_k']}")

    lines = []
    for line in block.strip("\n").split("\n"):
        if line.startswith("Runs: "):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")] if line.startswith("|") else None
        if cells and cells[0] in ROWS:
            fill = ROWS[cells[0]]
            cells[1] = fill(baseline) if baseline else DASH
            cells[2] = fill(current) if current else DASH
            line = "| " + " | ".join(cells) + " |"
        lines.append(line)
    sources = source_line(baseline, current)
    if sources:
        lines += ["", "Runs: " + sources]
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return f"{head}{START}\n\n{body.strip()}\n\n{END}{tail}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if README.md is out of date")
    args = parser.parse_args(argv)
    text = README.read_bytes().decode("utf-8").replace("\r\n", "\n")
    new = render(text, load("baseline.json"), load("latest.json"))
    if args.check:
        if new != text:
            print("README.md results are out of date: run make results")
            return 1
        return 0
    README.write_bytes(new.encode("utf-8"))
    print("README.md results updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())

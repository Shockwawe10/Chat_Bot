"""Write the Results table in README.md from reports/latest.json and reports/baseline.json, the
attack rate from reports/security/latest.json, and the agent rows from reports/agent/latest.json
and reports/agent/attacks/latest.json.

    python -m evals.render_results          # rewrite the table (make results)
    python -m evals.render_results --check  # exit 1 if README.md is out of date

Only the Baseline and Current cells of measured metrics change. A metric with no
value stays a dash, so nothing in the table is typed by hand. Judged metrics also stay
a dash until reports/judge_calibration.json shows the same judge model passed, and when
the run's answer check used the judge's own model, which makes the score 1.00 by construction.
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


def trusted(report, calibration, key):
    """A judged score is shown only if the same model and method passed calibration for that metric.

    Calibration checks faithfulness only, so the other judged metrics stay a dash.
    """
    return bool(
        report.get("judge_passes")
        and calibration
        and calibration.get("passed")
        and calibration.get("metric", "faithfulness") == key
        and calibration.get("judge_model") == report.get("judge_model")
        and calibration.get("method") == report.get("judge_method")
    )


def independent(report):
    """False when the answer check blocked every answer the judge would call unsupported."""
    check = report.get("answer_check") or "off"
    return check == "off" or report.get("answer_check_model") != report.get("judge_model")


def ratio(key, judged=False):
    def cell(report, calibration):
        if judged and key == "faithfulness" and not independent(report):
            return f"{DASH} (judge = answer check)"
        value = report["metrics"].get(key)
        if value is None or (judged and not trusted(report, calibration, key)):
            return DASH
        spread = report["metrics"].get(f"{key}_spread")
        return f"{value:.2f}" if spread is None else f"{value:.2f} (spread {spread:.2f})"

    return cell


def hit_rate(report, calibration):
    value = ratio("hit_rate")(report, calibration)
    return value if value == DASH else f"{value} (k={report['top_k']})"


def latency(report, calibration):
    value = report["metrics"].get("latency_p95_ms")
    if value is None:
        return DASH
    return f"{value / 1000:.1f} s, ${report['total_cost'] / max(report['cases_run'], 1):.2f}"


def agreement(report, calibration):
    """Shown whether or not calibration passed: a failed check is a result too."""
    if not calibration or calibration.get("judge_model") != report.get("judge_model"):
        return DASH
    kappa = calibration["kappa"]
    who = f" (labels by {calibration['labelled_by']})" if calibration.get("labelled_by") else ""
    return f"{calibration['agreement']:.2f} / {'undefined' if kappa is None else f'{kappa:.2f}'}{who}"


ROWS = {  # first cell of a README row: how to fill its value cells
    "Hit rate@k": hit_rate,
    "MRR": ratio("mrr"),
    "Faithfulness": ratio("faithfulness", judged=True),
    "Answer relevancy": ratio("answer_relevancy", judged=True),
    "Context precision": ratio("context_precision", judged=True),
    "Context recall": ratio("context_recall", judged=True),
    "Refusal accuracy": ratio("refusal_accuracy"),
    "Numeric fidelity": ratio("numeric_fidelity"),
    "Judge agreement / Cohen's κ (vs reference labels)": agreement,
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


def attack_rate(security):
    """The share of attack attempts that worked, from a saved full attack run (evals/attack_run.py)."""
    if not security:
        return DASH
    hits = sum(item["successes"] for item in security["summary"].values())
    total = sum(item["attempts"] for item in security["summary"].values())
    return f"{hits / total:.2f} ({hits}/{total})" if total else DASH


def tool_selection(agent):
    """The agent's tool selection accuracy, from a saved agent dev run (evals/agent_eval.py)."""
    if not agent or not agent["metrics"].get("tool_selection"):
        return DASH
    right, total = agent["metrics"]["tool_selection"]
    return f"{right / total:.2f} ({right}/{total})" if total else DASH


def unconfirmed_and_leaks(agent, agent_attacks):
    """Unconfirmed bookings and personal-data leaks over the saved agent dev and attack runs, both needed."""
    if not agent or not agent_attacks:
        return DASH
    runs = (agent["metrics"], agent_attacks["metrics"])
    unconfirmed = sum(m["unconfirmed_bookings"] for m in runs)
    leaks = sum(m["pii_leaks"] for m in runs)
    return f"{unconfirmed} / {leaks} ({runs[0]['cases']} dev and {runs[1]['cases']} attack cases)"


AGENT_ROWS = {
    "Tool selection accuracy": lambda agent, attacks: tool_selection(agent),
    "Unconfirmed actions / PII leaks": unconfirmed_and_leaks,
}


def render(text, baseline, current, calibration=None, security=None, agent=None, agent_attacks=None):
    if START not in text or END not in text:
        raise SystemExit("README.md has no results markers")
    head, rest = text.split(START, 1)
    block, tail = rest.split(END, 1)

    lines = []
    for line in block.strip("\n").split("\n"):
        if line.startswith("Runs: "):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")] if line.startswith("|") else None
        if cells and cells[0] in ROWS:
            fill = ROWS[cells[0]]
            cells[1] = fill(baseline, calibration) if baseline else DASH
            cells[2] = fill(current, calibration) if current else DASH
            line = "| " + " | ".join(cells) + " |"
        elif cells and cells[0] == "Attack success rate":
            cells[2] = attack_rate(security)
            line = "| " + " | ".join(cells) + " |"
        elif cells and cells[0] in AGENT_ROWS:
            cells[2] = AGENT_ROWS[cells[0]](agent, agent_attacks)
            line = "| " + " | ".join(cells) + " |"
        lines.append(line)
    sources = source_line(baseline, current)
    if agent and agent_attacks:
        sources += f" Agent: `{agent['run_id']}` and `{agent_attacks['run_id']}`."
    if sources:
        lines += ["", "Runs: " + sources.strip()]
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return f"{head}{START}\n\n{body.strip()}\n\n{END}{tail}"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="exit 1 if README.md is out of date")
    args = parser.parse_args(argv)
    text = README.read_bytes().decode("utf-8").replace("\r\n", "\n")
    new = render(
        text, load("baseline.json"), load("latest.json"), load("judge_calibration.json"), load("security/latest.json"),
        load("agent/latest.json"), load("agent/attacks/latest.json"),
    )
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

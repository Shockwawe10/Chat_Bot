"""Hallucination and quality gates on a saved full dev run, checked in CI without any model.

    python -m evals.gates                      # check reports/latest.json
    python -m evals.gates reports/runs/<id>.json

CI has no Ollama, so it cannot run the pipeline. It checks the answers of the committed
run instead: a change that makes the chatbot worse fails CI as soon as its new run is
committed. tests/ai runs these gates on reports/latest.json.

Values come from the nightly column of reports/thresholds.md. The Stage 3 gates at the
end start at what the system does today, like every gate there (principle 2). Each gate
is a count with its denominator, and lists the cases that break it. Facts and the English
reply are scored again from each saved answer with the current scorer, so a run file's own
verdicts are never trusted.
"""

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from app.settings import ROOT
from evals.metrics import language_reply
from evals.scoring import missing_facts

LATEST = ROOT / "reports" / "latest.json"
DEV_CASES = 52
# reports/thresholds.md, nightly gates (dev, 52 cases)
HIT_RATE_MIN = 35  # of 42 cases with gold spans
MRR_MIN = 0.66
OVER_REFUSED_MAX = 22  # of 42 answerable cases
NUMERIC_MIN = 11  # of 22 cases with must_include facts
# Stage 3 gates, at today's values (reports/thresholds.md, "Added in Stage 3")
FALSE_PREMISE_REFUSED_MAX = 4  # of 6 dev false-premise cases
UNCITED_FACTS_MAX = 0  # answered cases whose required facts are not in any cited passage
# Facts the answer has to calculate, so no passage can contain them: the cited passages
# must hold what they are calculated from instead. The numeric gate still checks the
# calculated fact in the answer.
CALCULATED = {
    "g035": {"1,000 m²": ["200 m²"]},  # 200 m² per MWp of a ground-mount plant, times 5 MWp
    "g060": {"2031": ["5 years"]},  # a 5-year warranty from a handover in March 2026
}


@dataclass
class Gate:
    name: str
    passed: bool
    value: str
    limit: str
    cases: list = field(default_factory=list)

    def line(self):
        listed = f" ({', '.join(self.cases)})" if self.cases else ""
        return f"{'pass' if self.passed else 'FAIL'}  {self.name}: {self.value}, gate {self.limit}{listed}"


def answered(case):
    return case.get("status") == 200 and not case.get("refused")


def lost_facts(case, facts):
    """Required facts the answer does not state; all of them if it was not answered."""
    return missing_facts(case.get("answer", ""), facts) if answered(case) else list(facts)


def run_problems(report):
    """Why this run cannot be gated at all, or an empty list."""
    problems = []
    if report.get("split") != "dev" or report.get("smoke") or report.get("experiment"):
        problems.append("not a full dev run")
    if report.get("system") != "pipeline":
        problems.append(f"system is {report.get('system')}, not the pipeline")
    if len(report.get("cases", [])) != DEV_CASES:
        problems.append(f"{len(report.get('cases', []))} cases, not {DEV_CASES}")
    if any(answered(case) and "cited_texts" not in case for case in report.get("cases", [])):
        problems.append("the run does not record citations; rerun it with the current harness")
    return problems


def check(report, dataset):
    """Every gate on one saved run. `dataset` maps case id to its golden case."""
    cases = report["cases"]
    gates = []

    out_of_scope = [c for c in cases if c["expected_behaviour"] == "abstain"]
    answered_oos = [c["id"] for c in out_of_scope if not c.get("refused")]
    gates.append(Gate("out-of-scope answered", not answered_oos, f"{len(answered_oos)}/{len(out_of_scope)}", "0", answered_oos))

    language = [c for c in cases if c["expected_behaviour"] == "language refusal"]
    no_reply = [c["id"] for c in language if not (answered(c) and language_reply(c.get("answer", "")))]
    gates.append(
        Gate("English-only reply", not no_reply, f"{len(language) - len(no_reply)}/{len(language)}", "every case", no_reply)
    )

    gold = [c for c in cases if "hit" in c]
    hits = sum(c["hit"] for c in gold)
    misses = [c["id"] for c in gold if not c["hit"]]
    gates.append(Gate("hit rate", hits >= HIT_RATE_MIN, f"{hits}/{len(gold)}", f">= {HIT_RATE_MIN}", misses))

    mrr = sum(c["reciprocal_rank"] for c in gold) / len(gold) if gold else 0.0
    gates.append(Gate("MRR", mrr >= MRR_MIN, f"{mrr:.2f}", f">= {MRR_MIN}"))

    answerable = [c for c in cases if not c["should_refuse"]]
    refused = [c["id"] for c in answerable if c.get("refused")]
    gates.append(
        Gate("over-refusal", len(refused) <= OVER_REFUSED_MAX, f"{len(refused)}/{len(answerable)}", f"<= {OVER_REFUSED_MAX}", refused)
    )

    with_facts = [c for c in cases if dataset[c["id"]]["must_include"]]
    lost = [c["id"] for c in with_facts if lost_facts(c, dataset[c["id"]]["must_include"])]
    kept = len(with_facts) - len(lost)
    gates.append(Gate("numeric fidelity", kept >= NUMERIC_MIN, f"{kept}/{len(with_facts)}", f">= {NUMERIC_MIN}", lost))

    premise = [c for c in cases if c["category"] == "false premise"]
    premise_refused = [c["id"] for c in premise if c.get("refused")]
    gates.append(
        Gate(
            "false premise refused",
            len(premise_refused) <= FALSE_PREMISE_REFUSED_MAX,
            f"{len(premise_refused)}/{len(premise)}",
            f"<= {FALSE_PREMISE_REFUSED_MAX}",
            premise_refused,
        )
    )
    premise_wrong = [c["id"] for c in premise if answered(c) and lost_facts(c, dataset[c["id"]]["must_include"])]
    gates.append(
        Gate("false premise answered without its facts", not premise_wrong, f"{len(premise_wrong)}", "0", premise_wrong)
    )

    checked, uncited = 0, []
    for c in cases:
        facts = dataset[c["id"]]["must_include"]
        if not (answered(c) and facts and not lost_facts(c, facts)):
            continue
        checked += 1
        inputs = CALCULATED.get(c["id"], {})
        stated = [part for fact in facts for part in inputs.get(fact, [fact])]
        if missing_facts("\n".join(c.get("cited_texts", [])), stated):
            uncited.append(c["id"])
    gates.append(
        Gate(
            "facts not in any cited passage",
            len(uncited) <= UNCITED_FACTS_MAX,
            f"{len(uncited)}/{checked}",
            f"<= {UNCITED_FACTS_MAX}",
            uncited,
        )
    )
    return gates


def main(argv=None):
    from evals.validate_golden import load_dataset

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run", nargs="?", default=str(LATEST), help="saved run file (default: reports/latest.json)")
    args = parser.parse_args(argv)
    report = json.loads(Path(args.run).read_text(encoding="utf-8"))
    problems = run_problems(report)
    if problems:
        print(f"cannot gate {args.run}: {'; '.join(problems)}")
        return 2
    gates = check(report, {case["id"]: case for case in load_dataset()})
    print(f"gates on {report['run_id']}:")
    for gate in gates:
        print("  " + gate.line())
    return 0 if all(gate.passed for gate in gates) else 1


if __name__ == "__main__":
    sys.exit(main())

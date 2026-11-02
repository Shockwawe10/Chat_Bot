"""Judge calibration: agreement and Cohen's kappa between my labels and the judge.

Run from the repository root:

    python -m evals.calibrate_judge --make-labels   # write the blind label file, once
    python -m evals.calibrate_judge                 # score my labels against the judge

I fill `supported` with yes or no for each answer: yes only if every claim in it is
backed by the context shown. The file never contains a judge score. The judge says yes
when its faithfulness score is 1.0, so both sides answer the same question. It passes at
agreement >= 0.85 and kappa >= 0.60, and the result goes to reports/judge_calibration.json.
The README shows judged metrics only after a pass for the same judge model.
"""

import argparse
import asyncio
import csv
import glob
import json
import random
import sys
from datetime import UTC, datetime

from app.settings import ROOT, read_env
from evals.judge import RagasJudge
from evals.systems import ChunkStore

LABELS = ROOT / "evals" / "annotation" / "judge_labels.csv"
RESULT = ROOT / "reports" / "judge_calibration.json"
SIZE = 30
AGREEMENT, KAPPA = 0.85, 0.60
SUPPORTED_AT = 1.0 - 1e-9  # Ragas reports 0.9999999999 for "all supported"
SEPARATOR = "\n\n---\n\n"
FIELDS = ["item", "case_id", "run_id", "question", "answer", "context", "supported", "notes"]


def cohen_kappa(first, second):
    """Kappa for two lists of yes/no labels, or None when chance agreement is total."""
    n = len(first)
    observed = sum(a == b for a, b in zip(first, second)) / n
    p_first, p_second = sum(first) / n, sum(second) / n
    expected = p_first * p_second + (1 - p_first) * (1 - p_second)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def candidates(runs, store):
    """Distinct answered dev answers from saved runs, with the context they were given."""
    found = {}
    for report in runs:
        for item in report["cases"]:
            if item["split"] != "dev" or item.get("status") != 200 or item.get("refused") is not False:
                continue
            if item["expected_behaviour"] == "language refusal":
                continue
            key = (item["id"], item["answer"].strip())
            if key not in found:
                found[key] = {
                    "case_id": item["id"],
                    "run_id": report["run_id"],
                    "question": item["question"],
                    "answer": item["answer"].strip(),
                    "context": SEPARATOR.join(store.text(chunk_id).replace("\r\n", "\n") for chunk_id in item["retrieved"]),
                }
    return [found[key] for key in sorted(found)]


def make_labels(runs, store, path, size=SIZE, seed=42):
    if path.exists():
        raise SystemExit(f"{path.name} exists; labels are never overwritten")
    pool = candidates(runs, store)
    if len(pool) < size:
        raise SystemExit(f"only {len(pool)} answers to label, need {size}")
    chosen = random.Random(seed).sample(pool, size)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, FIELDS)
        writer.writeheader()
        for number, row in enumerate(chosen, start=1):
            writer.writerow({**row, "item": number, "supported": "", "notes": ""})
    return chosen


def read_labels(path):
    """Return (rows, problems). Every row needs supported = yes or no."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    problems = [
        f"item {row.get('item')}: supported must be yes or no, got {row.get('supported')!r}"
        for row in rows
        if (row.get("supported") or "").strip().lower() not in ("yes", "no")
    ]
    if not rows:
        problems.append("the file has no rows")
    return rows, problems


def summarise(rows, scores, judge_model):
    human = [row["supported"].strip().lower() == "yes" for row in rows]
    judge = [score is not None and score >= SUPPORTED_AT for score in scores]
    agreement = sum(a == b for a, b in zip(human, judge)) / len(rows)
    kappa = cohen_kappa(human, judge)
    return {
        "date": datetime.now(UTC).date().isoformat(),
        "judge_model": judge_model,
        "items": len(rows),
        "human_yes": sum(human),
        "judge_yes": sum(judge),
        "judge_errors": sum(score is None for score in scores),
        "agreement": agreement,
        "kappa": kappa,
        "passed": agreement >= AGREEMENT and kappa is not None and kappa >= KAPPA,
        "thresholds": {"agreement": AGREEMENT, "kappa": KAPPA},
        "pairs": [
            {"item": row["item"], "case_id": row["case_id"], "human": h, "judge_score": s}
            for row, h, s in zip(rows, human, scores)
        ],
    }


def judge_scores(judge, rows):
    async def run():
        scores = []
        for row in rows:
            try:
                scores.append(
                    await judge.ascore(
                        "faithfulness",
                        user_input=row["question"],
                        response=row["answer"],
                        retrieved_contexts=row["context"].split(SEPARATOR),
                    )
                )
            except Exception:  # noqa: BLE001 - counted as a judge error in the result
                scores.append(None)
        return scores

    return asyncio.run(run())


def latest_run(system):
    paths = sorted(glob.glob(str(ROOT / "reports" / "runs" / f"*-{system}-dev.json")))
    if not paths:
        raise SystemExit(f"no saved {system} dev run in reports/runs")
    return json.loads(open(paths[-1], encoding="utf-8").read())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--make-labels", action="store_true", help="write the blind label file")
    args = parser.parse_args(argv)
    if args.make_labels:
        runs = [latest_run("pipeline"), latest_run("http")]
        chosen = make_labels(runs, ChunkStore.from_index(), LABELS)
        print(f"wrote {len(chosen)} answers to {LABELS.relative_to(ROOT)}; fill in supported with yes or no")
        return 0
    rows, problems = read_labels(LABELS)
    for problem in problems:
        print(f"ERROR {problem}")
    if problems:
        return 1
    judge = RagasJudge.from_env(read_env())
    result = summarise(rows, judge_scores(judge, rows), judge.model)
    RESULT.parent.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    kappa = "undefined" if result["kappa"] is None else f"{result['kappa']:.2f}"
    print(f"agreement {result['agreement']:.2f}, kappa {kappa}: {'passed' if result['passed'] else 'not passed'}")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())

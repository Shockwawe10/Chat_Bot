"""Run reviewed golden cases through a system and record how it scored.

Run from the repository root:

    python -m evals.run_evals                         # full dev run of the pipeline (make eval)
    python -m evals.run_evals --smoke                 # the 21 smoke cases (make eval-smoke)
    python -m evals.run_evals --system always-abstain # also always-answer, random-retriever
    python -m evals.run_evals --system http --url http://127.0.0.1:8017 --commit a3c0e9c
    python -m evals.run_evals --split holdout --allow-holdout   # end of a stage only
    python -m evals.run_evals --judge --judge-passes 3          # add the Ragas metrics
    python -m evals.run_evals --rescore reports/runs/<run_id>.json        # rescore, call nothing
    python -m evals.run_evals --rescore reports/holdout/<run_id>.json --allow-holdout

A holdout run also reports counts on all cases and on the cases outside
evals/exposure.py's EXPOSED_HOLDOUT (see "Holdout exposure" in evals/golden_validation.md).

Only reviewed cases run; drafts are counted and skipped. Every run writes
reports/runs/<run_id>.json (holdout runs: reports/holdout/). A full dev run of the
pipeline also copies it to reports/latest.json and adds a row to evals/history.csv.
"""

import argparse
import csv
import json
import math
import shutil
import subprocess
import sys
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

from app.chunker import CHUNKER_VERSION, ChunkConfig
from app.generator import PromptTemplate
from app.settings import ROOT, read_env
from evals.chunk_report import KB_DIR
from evals.exposure import check_exposed, exposure_report, format_report
from evals.freshness import stamp
from evals.judge import JUDGED, aggregate_judged, judge_cases, make_judge
from evals.metrics import aggregate, score_case
from evals.systems import (
    AlwaysAbstain,
    AlwaysAnswer,
    ApiSystem,
    ChunkStore,
    RandomRetriever,
)
from evals.validate_golden import LOW_OVERLAP, check, load_corpus, load_dataset

REPORTS = ROOT / "reports"
HISTORY = ROOT / "evals" / "history.csv"
SYSTEMS = ("pipeline", "http", "always-abstain", "always-answer", "random-retriever")
HISTORY_FIELDS = [
    "run_id",
    "timestamp",
    "git_sha",
    "git_dirty",
    "dataset_version",
    "cases_run",
    "prompt_version",
    "llm_model",
    "embedding_model",
    "top_k",
    "chunk_size",
    "hit_rate",
    "mrr",
    "all_groups_recall",
    "behaviour_accuracy",
    "refusal_accuracy",
    "over_refusal_rate",
    "numeric_fidelity",
    *JUDGED,
    "judge_model",
    "judge_method",
    "judge_passes",
    "latency_p95_ms",
]


def select_cases(cases, split, smoke):
    """Return (cases to run, number of drafts skipped)."""
    chosen = [c for c in cases if c["split"] == split and (c["smoke"] or not smoke)]
    reviewed = [c for c in chosen if c["reviewed_by"] is not None]
    return reviewed, len(chosen) - len(reviewed)


def run(cases, system, store, overlap=None):
    scored = []
    for number, case in enumerate(cases, start=1):
        response = system.ask(case["question"])
        scored.append(score_case(case, response, store, system.has_retrieval, system.has_generation))
        print(f"\r{system.name}: {number}/{len(cases)}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    return scored, aggregate(scored, overlap, LOW_OVERLAP)


def git_state():
    def git(*args):
        result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True, check=False)
        return result.stdout.strip()

    changed = git("status", "--porcelain", "--untracked-files=no", "--", ".", ":!reports", ":!evals/history.csv")
    return git("rev-parse", "HEAD"), bool(changed)


def prompt_sha(version):
    try:
        return PromptTemplate.load(version).sha256
    except FileNotFoundError:
        return None


def ollama_version(env, client=None):
    """The Ollama server's version, or None. It can update itself between or during runs."""
    import httpx

    try:
        client = client or httpx.Client(base_url=env.get("OLLAMA_URL") or "http://localhost:11434", timeout=5)
        return client.get("/api/version").raise_for_status().json().get("version")
    except (httpx.HTTPError, ValueError):
        return None


def build_manifest(run_id, system, args, env, cases_run, drafts, dataset_version, metrics, store):
    sha, dirty = git_state()
    served = getattr(system, "versions", None) or {}
    cfg = ChunkConfig.from_env(env)
    prompt = served.get("prompt") or env.get("PROMPT_VERSION") or "v2"
    return {
        "run_id": run_id,
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "system": system.name,
        "label": args.label,
        "experiment": args.experiment,
        "split": args.split,
        "smoke": args.smoke,
        "git_sha": args.commit or sha,
        "git_dirty": None if args.commit else dirty,
        "dataset_version": dataset_version,
        "cases_run": cases_run,
        "drafts_skipped": drafts,
        "prompt_version": prompt,
        "prompt_sha256": prompt_sha(prompt),
        **stamp(env),
        "llm_provider": env.get("LLM_PROVIDER"),
        "llm_model": env.get("LLM_MODEL"),
        "llm_digest": served.get("llm_digest") or env.get("LLM_DIGEST"),
        "ollama_version": ollama_version(env),
        "judge_provider": env.get("JUDGE_PROVIDER"),
        "judge_model": env.get("JUDGE_MODEL"),
        "embedding_model": env.get("EMBEDDING_MODEL"),
        "embedding_digest": env.get("EMBEDDING_DIGEST"),
        "temperature": env.get("TEMPERATURE"),
        "seed": env.get("LLM_SEED"),
        "chunker_version": CHUNKER_VERSION,
        "chunk_size": cfg.target,
        "chunk_max": cfg.max,
        "chunk_min": cfg.min,
        "top_k": int(env.get("TOP_K") or 5),
        "retrieval": env.get("RETRIEVAL") or "dense",
        "answer_check": env.get("ANSWER_CHECK") or "off",
        "answer_check_model": env.get("ANSWER_CHECK_MODEL") if env.get("ANSWER_CHECK") not in (None, "", "off") else None,
        "index_fingerprint": served.get("index_fingerprint") or (store.fingerprint if store else None),
        "judge_passes": args.judge_passes if args.judge else 0,
        "judge_method": metrics.pop("judge_method", None),
        "total_cost": 0.0,
        "latency_p95_ms": metrics["latency_p95_ms"],
        "metrics": metrics,
    }


def history_row(report):
    row = {**report, **report["metrics"]}
    return {field: row.get(field) for field in HISTORY_FIELDS}


def append_history(report, history_path, runs_dir):
    """Add one row. If the columns changed since the file was started, rebuild the earlier
    rows from their run files first: appending under an old header puts values in the
    wrong columns, which is how the judge fields once landed past the end of the header.
    """
    header, run_ids = None, []
    if history_path.exists():
        with open(history_path, encoding="utf-8", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader, None)
            run_ids = [row[0] for row in reader if row]
    if header == HISTORY_FIELDS:
        with open(history_path, "a", encoding="utf-8", newline="") as handle:
            csv.DictWriter(handle, HISTORY_FIELDS).writerow(history_row(report))
        return
    earlier = []
    for run_id in run_ids:
        run_file = runs_dir / f"{run_id}.json"
        if not run_file.exists():
            raise SystemExit(f"{history_path.name} has columns from an older version and no run file for {run_id}")
        earlier.append(history_row(json.loads(run_file.read_text(encoding="utf-8"))))
    with open(history_path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, HISTORY_FIELDS)
        writer.writeheader()
        writer.writerows([*earlier, history_row(report)])


def write_outputs(report, scored, reports_dir, history_path, record_baseline=False):
    """Write the run file, and for a full dev pipeline run also latest.json and the history row."""
    folder = reports_dir / ("holdout" if report["split"] == "holdout" else "runs")
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{report['run_id']}.json"
    path.write_text(json.dumps({**report, "cases": scored}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    # An experiment is compared in reports/experiments.md; it does not replace the adopted setup.
    full_dev = (
        report["system"] == "pipeline" and report["split"] == "dev" and not report["smoke"] and not report.get("experiment")
    )
    if full_dev:
        shutil.copyfile(path, reports_dir / "latest.json")
        append_history(report, history_path, folder)
    if record_baseline:
        if not full_dev:
            raise SystemExit("only a full dev run of the pipeline can be the recorded baseline")
        shutil.copyfile(path, reports_dir / "baseline.json")
    return path


def make_system(args, env, stack):
    if args.system == "always-abstain":
        return AlwaysAbstain(), None
    if args.system == "always-answer":
        return AlwaysAnswer(), None
    store = ChunkStore.from_index()
    top_k = int(env.get("TOP_K") or 5)
    if args.system == "random-retriever":
        return RandomRetriever(store, top_k, args.seed), store
    if args.system == "http":
        import httpx

        client = stack.enter_context(httpx.Client(base_url=args.url, timeout=180))
        return ApiSystem(client, "http"), store
    from fastapi.testclient import TestClient

    from app.api import create_default_app

    client = stack.enter_context(TestClient(create_default_app()))
    return ApiSystem(client, "pipeline"), store


def summary(report):
    m = report["metrics"]

    def show(value):
        return "—" if value is None else f"{value:.2f}" if isinstance(value, float) else str(value)

    lines = [f"run {report['run_id']}: {report['cases_run']} cases ({report['drafts_skipped']} drafts skipped)"]
    for key in (
        "hit_rate",
        "hit_rate_low_overlap",
        "hit_rate_high_overlap",
        "mrr",
        "all_groups_recall",
        "near_misses_with_distractor",
        "behaviour_accuracy",
        "behaviour_decided",
        "behaviour_for_judge",
        "refusal_accuracy",
        "over_refusal_rate",
        "numeric_fidelity",
        "out_of_scope_answered",
        "errors",
        *JUDGED,
        "judge_errors",
        "latency_p95_ms",
    ):
        if key in m:
            lines.append(f"  {key}: {show(m[key])}")
    for category, (passed, failed, judge) in m["behaviour_by_category"].items():
        lines.append(f"  behaviour, {category}: {passed} passed, {failed} failed, {judge} for the judge")
    if "exposure" in m:
        lines.extend(format_report(m["exposure"]))
    return "\n".join(lines)


# What each system can produce, so a saved run is rescored the way it was scored.
CAPABILITIES = {
    "pipeline": (True, True),
    "http": (True, True),
    **{cls.name: (cls.has_retrieval, cls.has_generation) for cls in (AlwaysAbstain, AlwaysAnswer, RandomRetriever)},
}


def rescore(report, cases, overlap, store):
    """Score a saved run again with the current scoring code and dataset, without asking any system.

    Returns (scored, metrics, changed). LLM-judged values are copied from the run, because
    rescoring never calls a model. `changed` maps every plain-code metric that differs from
    the saved one to (saved, rescored).
    """
    by_id = {case["id"]: case for case in cases}
    unknown = [saved["id"] for saved in report["cases"] if saved["id"] not in by_id]
    if unknown:
        raise SystemExit(f"the run has cases the dataset no longer has: {', '.join(unknown)}")
    has_retrieval, has_generation = CAPABILITIES[report["system"]]
    scored = []
    for saved in report["cases"]:
        response = {
            key: saved[key] for key in ("status", "latency_ms", "retrieved", "citations", "flags") if key in saved
        }
        if has_generation:
            response["answer"] = saved.get("answer", "")
            response["abstained"] = saved.get("refused", False)
        new = score_case(by_id[saved["id"]], response, store, has_retrieval, has_generation)
        new.update({key: saved[key] for key in ("judged", "judge_errors") if key in saved})
        scored.append(new)
    metrics = aggregate(scored, overlap, LOW_OVERLAP)
    plain = [key for key in metrics if key not in JUDGED]
    judged_prefixes = tuple(f"{name}_" for name in JUDGED)
    for key, value in report["metrics"].items():
        if key in JUDGED or key.startswith(judged_prefixes) or key == "judge_errors":
            metrics[key] = value
    if report["split"] == "holdout":
        metrics["exposure"] = exposure_report(scored)
    changed = {
        key: (report["metrics"][key], metrics[key])
        for key in plain
        if key in report["metrics"] and not same(report["metrics"][key], metrics[key])
    }
    return scored, metrics, changed


def same(a, b):
    """Equal, with floats compared to 1e-9: the same sum can differ in its last digit."""
    if isinstance(a, float) or isinstance(b, float):
        return a is not None and b is not None and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-12)
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same(a[key], b[key]) for key in a)
    if isinstance(a, (list, tuple)) and isinstance(b, (list, tuple)):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return a == b


def rescore_main(path, allow_holdout=False, store=None):
    """Rescore one saved run file and print it. Writes nothing. Returns 1 if a metric changed."""
    report = json.loads(path.read_text(encoding="utf-8"))
    if report["split"] == "holdout" and not allow_holdout:
        raise SystemExit("rescoring a holdout run shows holdout results: add --allow-holdout to mean it")
    cases = load_dataset()
    errors, stats = check(cases, load_corpus(KB_DIR, ChunkConfig()))
    if errors:
        raise SystemExit("the golden dataset does not validate: run python -m evals.validate_golden")
    if report["split"] == "holdout" and check_exposed(cases):
        raise SystemExit("; ".join(check_exposed(cases)))
    if CAPABILITIES[report["system"]][0]:
        store = store or ChunkStore.from_index()
        if report.get("index_fingerprint") and store.fingerprint != report["index_fingerprint"]:
            raise SystemExit(
                f"the run used index {report['index_fingerprint']}, the active index is {store.fingerprint}: "
                "chunk ids would not match. Rebuild the run's index before rescoring."
            )
    if report.get("dataset_version") != cases[0]["dataset_version"]:
        print(
            f"note: the run used dataset {report.get('dataset_version')}, rescored with "
            f"{cases[0]['dataset_version']}, so case changes show up as metric changes"
        )
    _, metrics, changed = rescore(report, cases, stats["overlap"], store)
    print(summary({**report, "metrics": metrics}))
    print(f"rescored {path.name} without calling any system; nothing written")
    if not changed:
        print("every plain-code metric matches the saved run")
        return 0
    for key, (saved, now) in changed.items():
        print(f"CHANGED {key}: saved {saved}, rescored {now}")
    return 1


def main(argv=None, store=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--system", choices=SYSTEMS, default="pipeline")
    parser.add_argument("--url", help="base URL for --system http")
    parser.add_argument("--commit", help="commit the http server runs, recorded in the manifest")
    parser.add_argument("--label", default="", help="a note stored in the manifest")
    parser.add_argument(
        "--experiment", default="", help="name an experiment run: saved and labelled, but latest.json and history stay"
    )
    parser.add_argument("--split", choices=("dev", "holdout"), default="dev")
    parser.add_argument("--allow-holdout", action="store_true", help="required for --split holdout")
    parser.add_argument("--smoke", action="store_true", help="only the smoke cases")
    parser.add_argument("--seed", type=int, default=42, help="for --system random-retriever")
    parser.add_argument("--record-baseline", action="store_true", help="also copy the run to reports/baseline.json")
    parser.add_argument("--judge", action="store_true", help="add the LLM-judged Ragas metrics")
    parser.add_argument("--judge-passes", type=int, default=1, help="judge every case this many times")
    parser.add_argument("--rescore", metavar="RUN_JSON", help="score a saved run file again; calls no system")
    args = parser.parse_args(argv)
    if args.rescore:
        path = Path(args.rescore)
        return rescore_main(path if path.is_absolute() else ROOT / path, args.allow_holdout, store)
    if args.split == "holdout" and not args.allow_holdout:
        parser.error("the holdout runs only at the end of a stage: add --allow-holdout to mean it")
    if args.system == "http" and not args.url:
        parser.error("--system http needs --url")

    cases = load_dataset()
    errors, stats = check(cases, load_corpus(KB_DIR, ChunkConfig()))
    if errors:
        raise SystemExit("the golden dataset does not validate: run python -m evals.validate_golden")
    if args.split == "holdout" and check_exposed(cases):
        raise SystemExit("; ".join(check_exposed(cases)))
    selected, drafts = select_cases(cases, args.split, args.smoke)
    if not selected:
        raise SystemExit("no reviewed cases to run")

    env = read_env()
    run_id = f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{args.system}-{args.split}{'-smoke' if args.smoke else ''}"
    if args.experiment:
        run_id += f"-{args.experiment}"
    with ExitStack() as stack:
        system, store = make_system(args, env, stack)
        scored, metrics = run(selected, system, store, stats["overlap"])
        if args.judge:
            judge = make_judge(env)
            metrics["judge_method"] = judge.method
            judge_cases(judge, {c["id"]: c for c in selected}, scored, store, args.judge_passes)
            metrics.update(aggregate_judged(scored, args.judge_passes))
        if args.split == "holdout":
            metrics["exposure"] = exposure_report(scored)
        report = build_manifest(
            run_id, system, args, env, len(selected), drafts, cases[0]["dataset_version"], metrics, store
        )
    path = write_outputs(report, scored, REPORTS, HISTORY, args.record_baseline)
    print(summary(report))
    print(f"written: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

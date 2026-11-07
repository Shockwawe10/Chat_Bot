"""Send the traces of a saved dev run to Arize Phoenix, with each failed case marked.

    make phoenix                                               # start Phoenix at http://127.0.0.1:6006
    python -m evals.phoenix_export reports/latest.json         # in another terminal
    python -m evals.phoenix_export reports/latest.json --failed-only

Every /ask request already writes one JSON line to runs/traces/ (app/api.py): the question,
the retrieved passages, the model's raw output, the answer check's verdict per sentence, the
output guard and the timings. This module turns the lines of one run into OpenTelemetry spans
with OpenInference attributes, which Phoenix shows as a tree per question:

    ask (CHAIN)  ->  embed (EMBEDDING), retrieve (RETRIEVER), generate (LLM), answer check (GUARDRAIL)

The app is not changed, so committed runs stay fresh (evals/freshness.py). The OpenTelemetry SDK
and its gRPC exporter come with chromadb (pinned in requirements.txt). Phoenix itself runs from
its own virtual environment (make phoenix), local only, with its telemetry and AI agent off.

Each root span carries the run's verdict for its case (eval.* attributes, the tag "failed",
and an error status), so Phoenix can filter to the failed cases. Dev runs only: a holdout run
is refused, so holdout questions never reach the Phoenix UI (CLAUDE.md).
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from app.settings import ROOT

TRACE_DIR = ROOT / "runs" / "traces"
ENDPOINT = os.environ.get("PHOENIX_GRPC_ENDPOINT", "http://127.0.0.1:4317")
MS = 1_000_000  # nanoseconds per millisecond


def run_window(report):
    """(start, end) of a run: its run id holds the start time, its timestamp the end.

    Both are cut to whole seconds and trace times are not, so the window ends one second later:
    the requests of the run's last second would fall outside it otherwise.
    """
    end = datetime.fromisoformat(report["timestamp"]) + timedelta(seconds=1)
    start = datetime.strptime(report["run_id"][:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=end.tzinfo)
    return start, end


def records_for(report, trace_dir=TRACE_DIR):
    """[(case, trace record)] for the run's cases, matched by question inside the run's time window."""
    if report.get("split") != "dev":
        raise SystemExit("dev runs only: holdout questions never go to Phoenix")
    start, end = run_window(report)
    open_cases = {}
    for case in report["cases"]:
        open_cases.setdefault(case["question"], []).append(case)
    pairs = []
    days = sorted({start.date(), end.date()})
    for day in days:
        path = trace_dir / f"{day}.jsonl"
        if not path.exists():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if not start <= datetime.fromisoformat(record["time"]) <= end:
                continue
            waiting = open_cases.get(record.get("question"))
            if waiting:
                pairs.append((waiting.pop(0), record))
    return pairs


def failed(case):
    """The run's verdict, as the eval harness scored it."""
    return case.get("behaviour_ok") is False or case.get("hit") is False or bool(case.get("missing_facts"))


def model_answer(record):
    """The answer the model wrote, before the answer check could replace it with the refusal sentence."""
    raw = record.get("raw_outputs") or []
    try:
        return json.loads(raw[-1]).get("answer") or ""
    except (IndexError, ValueError, AttributeError):
        return (record.get("parsed") or {}).get("answer", "")


def span(name, kind, start, end, attributes, parent=None, error=None):
    return {"name": name, "kind": kind, "start": start, "end": end, "attributes": attributes, "parent": parent, "error": error}


def spans_for(case, record, report):
    """The spans of one request, as plain dicts: [root, children...]. Times in nanoseconds."""
    timings = record.get("timings_ms") or {}
    end = int(datetime.fromisoformat(record["time"]).timestamp() * 1e9)
    total = timings.get("total", 0.0)
    start = end - int(total * MS)
    parsed = record.get("parsed") or {}
    is_failed = failed(case)
    root = span(
        "ask",
        "CHAIN",
        start,
        end,
        {
            "input.value": record.get("question", ""),
            "output.value": parsed.get("answer", ""),
            "tag.tags": ["failed"] if is_failed else ["passed"],
            "metadata": json.dumps(
                {"run_id": report["run_id"], "prompt_version": record.get("prompt_version"), "flags": record.get("flags", [])}
            ),
            "eval.case_id": case["id"],
            "eval.expected_behaviour": case.get("expected_behaviour", ""),
            "eval.failed": is_failed,
            "eval.behaviour_ok": str(case.get("behaviour_ok")),
            "eval.hit": str(case.get("hit")),
            "eval.missing_facts": case.get("missing_facts") or [],
            "eval.refused": bool(case.get("refused")),
        },
        error=f"case {case['id']} failed its eval" if is_failed else None,
    )
    spans = [root]
    clock = start
    for name, kind, key in (("embed", "EMBEDDING", "embed"), ("retrieve", "RETRIEVER", "retrieve"), ("generate", "LLM", "generate")):
        if key not in timings:
            continue
        stop = clock + int(timings[key] * MS)
        attributes = {"input.value": record.get("question", "")}
        if kind == "EMBEDDING":
            attributes["embedding.model_name"] = report.get("embedding_model") or ""
        if kind == "RETRIEVER":
            for i, hit in enumerate(record.get("hits") or []):
                prefix = f"retrieval.documents.{i}.document"
                attributes[f"{prefix}.id"] = hit.get("chunk_id", "")
                attributes[f"{prefix}.content"] = hit.get("text", "")
                attributes[f"{prefix}.score"] = float(hit.get("score") or 0.0)
                attributes[f"{prefix}.metadata"] = json.dumps({"doc_id": hit.get("doc_id"), "rank": hit.get("rank")})
        if kind == "LLM":
            raw = record.get("raw_outputs") or []
            attributes.update(
                {
                    "llm.model_name": report.get("llm_model") or "",
                    "output.value": raw[-1] if raw else "",
                    "llm.output_messages.0.message.role": "assistant",
                    "llm.output_messages.0.message.content": raw[-1] if raw else "",
                    "llm.invocation_parameters": json.dumps({"temperature": report.get("temperature"), "seed": report.get("seed")}),
                }
            )
        spans.append(span(name, kind, clock, stop, attributes, parent=0))
        clock = stop
    check = record.get("answer_check")
    if isinstance(check, dict):
        stop = min(end, clock + int(float(check.get("ms") or 0.0) * MS))
        verdicts = check.get("verdicts") or []
        unsupported = [v["sentence"] for v in verdicts if not v.get("supported")]
        spans.append(
            span(
                "answer check",
                "GUARDRAIL",
                clock,
                stop,
                {
                    "input.value": model_answer(record),
                    "output.value": json.dumps(verdicts, ensure_ascii=False),
                    "metadata": json.dumps({"model": check.get("model"), "unsupported": unsupported}, ensure_ascii=False),
                },
                parent=0,
                error="a sentence is not supported by the passages" if unsupported else None,
            )
        )
    return spans


def send(all_spans, project, exporter=None):
    """Export lists of span dicts (one list per request) through OpenTelemetry. Returns the count sent."""
    from opentelemetry import trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.trace import Status, StatusCode

    if exporter is None:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )

        exporter = OTLPSpanExporter(endpoint=ENDPOINT, insecure=True)
    provider = TracerProvider(resource=Resource.create({"openinference.project.name": project, "service.name": "rag"}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("evals.phoenix_export")
    count = 0
    for request in all_spans:
        opened = []
        for item in request:
            parent = opened[item["parent"]] if item["parent"] is not None else None
            context = trace.set_span_in_context(parent) if parent is not None else None
            otel = tracer.start_span(
                item["name"],
                context=context,
                start_time=item["start"],
                attributes={"openinference.span.kind": item["kind"], **item["attributes"]},
            )
            if item["error"]:
                otel.set_status(Status(StatusCode.ERROR, item["error"]))
            opened.append(otel)
        for item, otel in reversed(list(zip(request, opened))):
            otel.end(end_time=item["end"])
            count += 1
    provider.force_flush()
    provider.shutdown()
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run", help="a saved dev run, such as reports/latest.json")
    parser.add_argument("--project", default="", help="Phoenix project name (default: rag-<run_id>)")
    parser.add_argument("--failed-only", action="store_true", help="send only the cases the run failed")
    args = parser.parse_args(argv)
    path = Path(args.run)
    report = json.loads((path if path.is_absolute() else ROOT / path).read_text(encoding="utf-8"))
    pairs = records_for(report)
    if args.failed_only:
        pairs = [(case, record) for case, record in pairs if failed(case)]
    project = args.project or f"rag-{report['run_id']}"
    sent = send([spans_for(case, record, report) for case, record in pairs], project)
    missing = len(report["cases"]) - len(records_for(report))
    print(f"{project}: {len(pairs)} requests, {sent} spans sent to {ENDPOINT}")
    print(f"  failed cases: {sum(failed(case) for case, _ in pairs)}; cases with no trace: {missing}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Blind annotation of evals/annotation/blind_20.csv by a local model, standing in for a person.

Run from the repository root, with Ollama running:

    python -m evals.blind_annotate                       # phi4-mini:3.8b
    python -m evals.blind_annotate --model <other-tag>
    python -m evals.validate_golden --agreement evals/annotation/blind_20_model.csv

The model sees only what a person would: the whole knowledge base and one question at
a time, with the same five behaviour definitions as evals/golden_validation.md. It never
sees evals/golden_dataset.jsonl. Its choices go to a separate file, so blind_20.csv stays
blank for a person, and every row says which model filled it in.

A model is a weaker stand-in than a person: report the result as "model annotator, not
human". The answering model (LLM_MODEL) is refused, because an annotator that shares the
chatbot's habits would agree with its mistakes.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

import httpx

from app.settings import read_env

ROOT = Path(__file__).resolve().parents[1]
KB_DIR = ROOT / "data" / "kb"
SHEET = ROOT / "evals" / "annotation" / "blind_20.csv"
OUT = ROOT / "evals" / "annotation" / "blind_20_model.csv"
DEFAULT_MODEL = "phi4-mini:3.8b"
DEFAULT_URL = "http://localhost:11434"
NUM_CTX = 12288  # the whole knowledge base is about 7,000 tokens

BEHAVIOURS = ("answer", "abstain", "correct premise", "clarify", "language refusal")
SCHEMA = {
    "type": "object",
    "properties": {
        "behaviour": {"type": "string", "enum": list(BEHAVIOURS)},
        "short_answer": {"type": "string"},
    },
    "required": ["behaviour", "short_answer"],
}
INSTRUCTIONS = """\
You are checking questions that customers send to the company described in the knowledge
base below. For the customer's question, decide what a correct reply must do, using only
the knowledge base. Choose exactly one behaviour:

- answer: the knowledge base answers it, including when the answer is "no" or "we don't do that"
- abstain: the knowledge base doesn't contain it
- correct premise: the question assumes something the knowledge base contradicts
- clarify: the answer depends on something the customer didn't say
- language refusal: the question is not in English

Then give the reply's key point in one short sentence, in English.
Reply with JSON: {"behaviour": "...", "short_answer": "..."}

<knowledge_base>
$kb
</knowledge_base>
"""


def knowledge_base(kb_dir=KB_DIR):
    """Every document in file-name order, each under its file name, with LF line endings."""
    parts = []
    for path in sorted(kb_dir.glob("*.md")):
        text = path.read_bytes().decode("utf-8").replace("\r\n", "\n").strip()
        parts.append(f"=== {path.name} ===\n{text}")
    if not parts:
        raise SystemExit(f"no documents in {kb_dir}")
    return "\n\n".join(parts)


def annotate(client, model, kb, question, num_ctx=NUM_CTX):
    """Return (behaviour, short_answer) for one question."""
    payload = {
        "model": model,
        "stream": False,
        "format": SCHEMA,
        "messages": [
            {"role": "system", "content": INSTRUCTIONS.replace("$kb", kb)},
            {"role": "user", "content": question},
        ],
        "options": {
            "temperature": 0,
            "seed": 42,
            "num_ctx": num_ctx,
            "num_predict": 200,
        },
    }
    response = client.post("/api/chat", json=payload)
    if response.status_code != 200:
        raise RuntimeError(f"Ollama returned {response.status_code}: {response.text}")
    body = response.json()
    used = body.get("prompt_eval_count")
    if used is not None and used >= num_ctx:
        raise RuntimeError(
            f"prompt used {used} of {num_ctx} context tokens: the knowledge base may be cut"
        )
    reply = json.loads(body["message"]["content"])
    behaviour = reply.get("behaviour")
    if behaviour not in BEHAVIOURS:
        raise ValueError(f"behaviour {behaviour!r} is not one of {BEHAVIOURS}")
    return behaviour, str(reply.get("short_answer", "")).strip()


def model_digest(client, model):
    """First 12 characters of the installed model's digest, or 'unknown'."""
    response = client.get("/api/tags")
    if response.status_code == 200:
        for item in response.json().get("models", []):
            if item.get("name") == model or item.get("model") == model:
                return item.get("digest", "unknown")[:12]
    return "unknown"


def annotate_sheet(client, model, rows, kb, note, num_ctx=NUM_CTX, log=print):
    """Fill behaviour, short_answer and notes for every row, in order."""
    filled = []
    for number, row in enumerate(rows, start=1):
        behaviour, short_answer = annotate(client, model, kb, row["question"], num_ctx)
        filled.append(
            {**row, "behaviour": behaviour, "short_answer": short_answer, "notes": note}
        )
        log(f"{number:>2}/{len(rows)} {row['id']}: {behaviour}")
    return filled


def read_sheet(path=SHEET):
    with open(path, encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows or "question" not in rows[0]:
        raise SystemExit(f"{path}: no questions")
    return rows


def write_sheet(rows, path=OUT):
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["id", "question", "behaviour", "short_answer", "notes"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(
            {key: row.get(key, "") for key in writer.fieldnames} for row in rows
        )


def main(argv=None, client=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--num-ctx", type=int, default=NUM_CTX)
    args = parser.parse_args(argv)

    env = read_env()
    if args.model == env.get("LLM_MODEL"):
        raise SystemExit(
            f"{args.model} is the answering model (LLM_MODEL); pick a different annotator"
        )
    client = client or httpx.Client(
        base_url=env.get("OLLAMA_URL") or DEFAULT_URL, timeout=600
    )
    note = (
        f"model annotator {args.model} ({model_digest(client, args.model)}), not human"
    )

    rows = annotate_sheet(
        client, args.model, read_sheet(), knowledge_base(), note, args.num_ctx
    )
    write_sheet(rows, Path(args.out))
    print(f"wrote {len(rows)} rows to {args.out}")
    print(f"next: python -m evals.validate_golden --agreement {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

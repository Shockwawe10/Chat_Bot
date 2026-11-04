"""Example customer questions per chunk, for RETRIEVAL=questions (HyPE / QuOTE style).

Customers ask in everyday words ("yearly check-up"); the documents use the company's
("inspection"). `python -m app.questions generate` asks the answering model (LLM_MODEL,
pinned) for 5 customer-style questions per chunk of the active index, from that chunk
alone, with prompts/chunk_questions_v1.txt. They go to data/chunk_questions.json so a
person can read them. Each entry keeps a hash of its chunk, so a file made for other
chunks is refused instead of used. The dataset is never shown to the model.
"""

import argparse
import hashlib
import json
import sys
from string import Template

from app.embedder import EmbeddingError
from app.generator import PROMPTS_DIR, LlmUnavailable, OllamaLlm
from app.index import INDEX_DIR, open_client, read_manifest
from app.settings import ROOT

QUESTIONS_FILE = ROOT / "data" / "chunk_questions.json"
PROMPT_FILE = PROMPTS_DIR / "chunk_questions_v1.txt"
SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {"type": "array", "items": {"type": "string", "minLength": 1}, "minItems": 3, "maxItems": 5}
    },
    "required": ["questions"],
    "additionalProperties": False,
}


class QuestionsUnavailable(RuntimeError):
    pass


def _clean(text):
    return text.replace("\r\n", "\n")


def chunk_hash(heading_path, text):
    return hashlib.sha256(f"{heading_path}\n{_clean(text)}".encode()).hexdigest()


def prompt_text():
    return _clean(PROMPT_FILE.read_bytes().decode("utf-8"))


def ask(llm, heading_path, text):
    """5 questions for one chunk: deduplicated, stripped, in the model's order."""
    prompt = Template(prompt_text()).substitute(passage=f"{heading_path}\n{_clean(text)}")
    payload = {
        "model": llm.cfg.model,
        "stream": False,
        "think": False,
        "format": SCHEMA,
        "messages": [{"role": "user", "content": prompt}],
        "options": {"temperature": 0, "seed": llm.cfg.seed, "num_ctx": llm.cfg.num_ctx, "num_predict": 400},
    }
    response = llm.client.post("/api/chat", json=payload)
    if response.status_code != 200:
        raise LlmUnavailable(f"Ollama returned {response.status_code}: {response.text}")
    questions = json.loads(response.json()["message"]["content"])["questions"]
    return list(dict.fromkeys(question.strip() for question in questions if question.strip()))


def generate(collection, llm):
    stored = collection.get(include=["documents", "metadatas"])
    chunks = {}
    for chunk_id, text, meta in sorted(zip(stored["ids"], stored["documents"], stored["metadatas"])):
        chunks[chunk_id] = {
            "chunk_sha256": chunk_hash(meta["heading_path"], text),
            "questions": ask(llm, meta["heading_path"], text),
        }
    return {
        "model": llm.cfg.model,
        "digest": llm.cfg.digest,
        "prompt": PROMPT_FILE.name,
        "prompt_sha256": hashlib.sha256(prompt_text().encode()).hexdigest(),
        "chunks": chunks,
    }


def load(path, collection):
    """{chunk id: [questions]} for every chunk in the collection, or QuestionsUnavailable."""
    if not path.exists():
        raise QuestionsUnavailable(f"{path} is missing; run: python -m app.questions generate")
    entries = json.loads(path.read_text(encoding="utf-8"))["chunks"]
    stored = collection.get(include=["documents", "metadatas"])
    result = {}
    for chunk_id, text, meta in zip(stored["ids"], stored["documents"], stored["metadatas"]):
        entry = entries.get(chunk_id)
        if entry is None or entry["chunk_sha256"] != chunk_hash(meta["heading_path"], text):
            raise QuestionsUnavailable(f"{path} was made for other chunks ({chunk_id}); generate it again")
        result[chunk_id] = entry["questions"]
    return result


def main():
    parser = argparse.ArgumentParser(description="Generate example customer questions for every chunk.")
    parser.add_argument("command", choices=["generate"])
    parser.parse_args()
    manifest = read_manifest(INDEX_DIR)
    if manifest is None:
        sys.exit("no index; run: python -m app.index build")
    llm = OllamaLlm.from_env()
    try:
        llm.check_pinned()
        collection = open_client(INDEX_DIR).get_collection(manifest["active_collection"], embedding_function=None)
        data = generate(collection, llm)
    except (LlmUnavailable, EmbeddingError) as error:
        sys.exit(f"generate failed: {error}")
    QUESTIONS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    count = sum(len(entry["questions"]) for entry in data["chunks"].values())
    print(f"wrote {count} questions for {len(data['chunks'])} chunks to {QUESTIONS_FILE}")


if __name__ == "__main__":
    main()

"""The model annotator sees the knowledge base and the question, never the answer key."""

import json
from pathlib import Path

import httpx
import pytest

from evals import blind_annotate
from evals.blind_annotate import (
    BEHAVIOURS,
    annotate,
    annotate_sheet,
    knowledge_base,
    main,
)


def fake_client(behaviour="answer", seen=None, prompt_eval_count=7000):
    def handler(request):
        if request.url.path == "/api/tags":
            return httpx.Response(
                200,
                json={
                    "models": [{"name": "phi4-mini:3.8b", "digest": "abc123def4567890"}]
                },
            )
        body = json.loads(request.content)
        if seen is not None:
            seen.append(body)
        reply = {"behaviour": behaviour, "short_answer": "A short reply."}
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps(reply)},
                "prompt_eval_count": prompt_eval_count,
            },
        )

    return httpx.Client(
        base_url="http://ollama", transport=httpx.MockTransport(handler)
    )


def test_knowledge_base_has_every_document():
    kb = knowledge_base()
    for path in blind_annotate.KB_DIR.glob("*.md"):
        assert f"=== {path.name} ===" in kb
    assert "\r" not in kb


def test_the_answer_key_is_never_read():
    source = Path(blind_annotate.__file__).read_text(encoding="utf-8")
    # The module docstring may name the file; the code must not.
    code = source.split('"""', 2)[2]
    assert "golden_dataset" not in code


def test_prompt_holds_the_knowledge_base_and_the_question():
    seen = []
    annotate(
        fake_client(seen=seen), "phi4-mini:3.8b", "KB TEXT", "Is the site visit free?"
    )
    system, user = seen[0]["messages"]
    assert "KB TEXT" in system["content"] and "$kb" not in system["content"]
    assert user["content"] == "Is the site visit free?"
    assert seen[0]["format"]["properties"]["behaviour"]["enum"] == list(BEHAVIOURS)


def test_a_behaviour_outside_the_five_is_refused():
    with pytest.raises(ValueError):
        annotate(fake_client(behaviour="maybe"), "phi4-mini:3.8b", "KB", "Q?")


def test_a_full_context_is_refused_because_the_knowledge_base_may_be_cut():
    with pytest.raises(RuntimeError):
        annotate(
            fake_client(prompt_eval_count=12288),
            "phi4-mini:3.8b",
            "KB",
            "Q?",
            num_ctx=12288,
        )


def test_every_row_is_filled_and_marked_as_a_model():
    rows = [{"id": "g001", "question": "Q1?"}, {"id": "g002", "question": "Q2?"}]
    filled = annotate_sheet(
        fake_client(),
        "phi4-mini:3.8b",
        rows,
        "KB",
        "model annotator x, not human",
        log=lambda *_: None,
    )
    assert [r["behaviour"] for r in filled] == ["answer", "answer"]
    assert all(r["notes"] == "model annotator x, not human" for r in filled)


def test_the_answering_model_is_refused(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "qwen3:4b-instruct")
    with pytest.raises(SystemExit):
        main(["--model", "qwen3:4b-instruct"], client=fake_client())


def test_main_writes_a_separate_file_and_leaves_the_blank_sheet(tmp_path, monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "qwen3:4b-instruct")
    blank = blind_annotate.SHEET.read_bytes()
    out = tmp_path / "out.csv"
    main(["--out", str(out)], client=fake_client())
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "id,question,behaviour,short_answer,notes"
    assert len(lines) == 21
    assert "(abc123def456), not human" in lines[1]
    assert blind_annotate.SHEET.read_bytes() == blank

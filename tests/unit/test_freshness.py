"""The freshness gate (evals/freshness.py): a committed run must be about the commit it is in."""

import pytest

from evals.freshness import SETTINGS, inputs_digest, problems, settings, stamp

ENV = {"PROMPT_VERSION": "v5", "TOP_K": "8", "RETRIEVAL": "questions", "LLM_MODEL": "m:1"}


def project(root, newline="\n"):
    """A small project with every answer input, written with the given line ending."""
    files = {
        "app/api.py": "def ask():\n    return 1\n",
        "app/guards.py": "BLOCK = True\n",
        "prompts/answer_v5.txt": "Rules:\n- data only\n",
        "prompts/answer_v2.txt": "Old rules\n",
        "data/kb/warranty.md": "# Warranty\n\n15 years.\n",
        "data/chunk_questions.json": '{"chunks": {}}\n',
        "data/allowed_contacts.txt": "support@example.com\n",
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.replace("\n", newline).encode())
    env_example = root / ".env.example"
    env_example.write_text("".join(f"{key}={value}\n" for key, value in ENV.items()), encoding="utf-8")
    return env_example


def test_line_endings_do_not_change_the_digest(tmp_path):
    project(tmp_path / "lf")
    project(tmp_path / "crlf", "\r\n")
    assert inputs_digest("v5", tmp_path / "lf") == inputs_digest("v5", tmp_path / "crlf")


@pytest.mark.parametrize(
    "name",
    ["app/api.py", "prompts/answer_v5.txt", "data/kb/warranty.md", "data/chunk_questions.json", "data/allowed_contacts.txt"],
)
def test_every_answer_input_changes_the_digest(tmp_path, name):
    project(tmp_path)
    before = inputs_digest("v5", tmp_path)
    (tmp_path / name).write_text((tmp_path / name).read_text(encoding="utf-8") + "changed\n", encoding="utf-8")
    assert inputs_digest("v5", tmp_path) != before


def test_a_new_document_changes_the_digest_and_another_prompt_version_does_not(tmp_path):
    project(tmp_path)
    before = inputs_digest("v5", tmp_path)
    (tmp_path / "prompts" / "answer_v2.txt").write_text("Changed old rules\n", encoding="utf-8")
    assert inputs_digest("v5", tmp_path) == before
    (tmp_path / "data" / "kb" / "new.md").write_text("# New\n", encoding="utf-8")
    assert inputs_digest("v5", tmp_path) != before


def test_settings_fill_the_code_defaults():
    assert settings({}) == {key: default for key, default in SETTINGS.items()}
    assert settings({"TOP_K": 8})["TOP_K"] == "8"


def test_a_run_stamped_now_is_fresh(tmp_path):
    env_example = project(tmp_path)
    report = stamp(ENV, tmp_path)
    assert problems(report, tmp_path, env_example) == []


def test_a_changed_input_after_the_run_is_stale(tmp_path):
    env_example = project(tmp_path)
    report = stamp(ENV, tmp_path)
    (tmp_path / "prompts" / "answer_v5.txt").write_text("Broken rules\n", encoding="utf-8")
    assert problems(report, tmp_path, env_example) == [
        "app code, prompt, knowledge base or contacts changed since the run; make a new run"
    ]


def test_a_run_with_other_settings_than_env_example_is_refused(tmp_path):
    env_example = project(tmp_path)
    report = stamp({**ENV, "TOP_K": "5", "ANSWER_CHECK": "minicheck"}, tmp_path)
    assert problems(report, tmp_path, env_example) == ["settings differ from .env.example: ANSWER_CHECK, TOP_K"]


def test_a_run_of_a_prompt_not_in_the_commit_is_refused(tmp_path):
    env_example = project(tmp_path)
    report = stamp(ENV, tmp_path)
    (tmp_path / "prompts" / "answer_v5.txt").unlink()
    assert "prompt v5 is not in the commit" in problems(report, tmp_path, env_example)


def test_an_old_run_without_a_stamp_is_refused(tmp_path):
    env_example = project(tmp_path)
    assert problems({"prompt_version": "v5"}, tmp_path, env_example) == [
        "the run records no inputs digest or settings; make a new run"
    ]

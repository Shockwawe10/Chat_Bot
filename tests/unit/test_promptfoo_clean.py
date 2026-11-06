"""evals/promptfoo_clean.py removes the local project path from promptfoo result files."""

import json

from evals.promptfoo_clean import main, relative

ROOT_TEXT = "C:\\Users\\Someone\\Projects\\RAG"


def test_paths_under_the_project_become_relative_in_any_case(tmp_path):
    root = tmp_path / "RAG"
    root.mkdir()
    data = {"config": {"basePath": str(root.resolve()) + "\\runs"}, "list": [str(root.resolve()).upper() + "/a.yaml", "plain"]}
    assert relative(data, root) == {"config": {"basePath": "runs"}, "list": ["a.yaml", "plain"]}


def test_the_project_root_itself_becomes_a_dot(tmp_path):
    assert relative(str(tmp_path.resolve()), tmp_path) == "."


def test_main_rewrites_the_file_and_keeps_everything_else(tmp_path, monkeypatch):
    import evals.promptfoo_clean as module

    monkeypatch.setattr(module, "ROOT", tmp_path)
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"basePath": str(tmp_path.resolve()) + "\\runs", "n": 96, "name": "Виталик-free"}), encoding="utf-8")
    main([str(path)])
    assert json.loads(path.read_text(encoding="utf-8")) == {"basePath": "runs", "n": 96, "name": "Виталик-free"}


def test_the_committed_promptfoo_result_holds_no_local_path():
    from app.settings import ROOT

    text = (ROOT / "reports" / "security" / "promptfoo-latest.json").read_text(encoding="utf-8").lower()
    assert str(ROOT.resolve()).lower().replace("\\", "\\\\") not in text
    assert "c:\\\\users" not in text

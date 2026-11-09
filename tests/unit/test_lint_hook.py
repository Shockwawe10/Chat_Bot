"""The lint-before-commit hook (.claude/hooks/lint_before_commit.py): a commit cannot pass a failed ruff check."""

import importlib.util
import io
import json
import subprocess

import pytest

from app.settings import ROOT

SPEC = importlib.util.spec_from_file_location("lint_before_commit", ROOT / ".claude" / "hooks" / "lint_before_commit.py")
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)


@pytest.mark.parametrize(
    "command, commits",
    [
        ('git commit -q -m "x"', True),
        ("make lint; git commit -m x", True),
        ("make lint | tail -1 && git add a.py && git commit -F - <<'EOF'", True),
        ('git -c user.name=x commit -m "y"', True),
        ("git commit --amend --no-edit", True),
        ("git status --short", False),
        ("git log --oneline -1", False),
        ("git commit-tree abc", False),
        ('echo "remember to git commitment"', False),
        ("make test", False),
    ],
)
def test_only_commands_that_run_git_commit_are_checked(command, commits):
    assert hook.runs_commit(command) is commits


def call(command, monkeypatch, ruff_code, findings="tests/x.py:3:1: I001 Import block is un-sorted"):
    monkeypatch.setattr(hook, "ruff", lambda root: subprocess.CompletedProcess([], ruff_code, findings if ruff_code else "", ""))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_input": {"command": command}})))
    return hook.main()


def test_a_commit_is_blocked_while_ruff_fails_and_the_findings_are_shown(monkeypatch, capsys):
    assert call("make lint; git commit -m x", monkeypatch, ruff_code=1) == 2
    assert "I001 Import block is un-sorted" in capsys.readouterr().err


def test_a_commit_passes_when_ruff_passes(monkeypatch):
    assert call('git commit -m "x"', monkeypatch, ruff_code=0) == 0


def test_other_commands_never_run_ruff(monkeypatch):
    def no_ruff(root):
        raise AssertionError("ruff must not run for a command that does not commit")

    monkeypatch.setattr(hook, "ruff", no_ruff)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_input": {"command": "git status"}})))
    assert hook.main() == 0

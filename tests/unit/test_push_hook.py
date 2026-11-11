"""The tests-before-push hook (.claude/hooks/tests_before_push.py): a push cannot pass a failed lint or test run."""

import importlib.util
import io
import json
import subprocess

import pytest

from app.settings import ROOT

SPEC = importlib.util.spec_from_file_location("tests_before_push", ROOT / ".claude" / "hooks" / "tests_before_push.py")
hook = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hook)


@pytest.mark.parametrize(
    "command, pushes",
    [
        ("git push -q origin stage-7/ui-e2e-docker", True),
        ('make test > "$S/test.log" 2>&1; echo "test exit $?"; git push -q origin main', True),
        ("make lint && make test && git push", True),
        ("git -c http.extraHeader=x push origin main", True),
        ("git push -u origin later/telegram-bot 2>&1 | tail -2", True),
        ("git status --short", False),
        ("git fetch -q origin", False),
        ('git commit -q -m "push the button"', False),
        ("git push-mirror", False),
        ("make test", False),
    ],
)
def test_only_commands_that_run_git_push_are_checked(command, pushes):
    assert hook.runs_push(command) is pushes


def call(command, monkeypatch, codes):
    ran = []

    def fake(root, args):
        ran.append(args[0])
        code = codes[args[0]]
        return subprocess.CompletedProcess([], code, "2 failed, 1543 passed" if code else "ok", "")

    monkeypatch.setattr(hook, "check", fake)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"tool_input": {"command": command}})))
    return hook.main(), ran


def test_a_push_with_failing_tests_is_blocked_with_the_summary(monkeypatch, capsys):
    code, ran = call("make test; git push", monkeypatch, {"ruff": 0, "pytest": 1})
    assert code == 2 and ran == ["ruff", "pytest"]
    assert "make test (pytest) fails" in capsys.readouterr().err


def test_a_push_with_a_lint_error_is_blocked_before_the_tests_run(monkeypatch, capsys):
    code, ran = call("git push", monkeypatch, {"ruff": 1, "pytest": 0})
    assert code == 2 and ran == ["ruff"]
    assert "make lint (ruff check .) fails" in capsys.readouterr().err


def test_a_push_goes_ahead_when_lint_and_tests_pass(monkeypatch):
    assert call("git push -q origin main", monkeypatch, {"ruff": 0, "pytest": 0}) == (0, ["ruff", "pytest"])


def test_other_commands_run_no_checks(monkeypatch):
    assert call("git status --short", monkeypatch, {"ruff": 1, "pytest": 1}) == (0, [])


def test_unreadable_hook_input_never_blocks(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert hook.main() == 0


def test_the_hook_runs_the_same_checks_as_ci():
    assert [args[:2] for _, args in hook.CHECKS] == [["ruff", "check"], ["pytest", "-q"]]

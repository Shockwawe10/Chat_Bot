"""PreToolUse hook for Bash: block a git push while make lint or make test fails.

CLAUDE.md requires make lint and make test before every push. In Stage 7 a push still went out
past failing tests: `make test > log; ...; git push` ran the push after the failure, and two
commits were red in CI (92f8593, 5a78205; LESSONS.md, 2026-11-11). This hook runs the same two
checks CI runs (ruff check . and pytest with pytest.ini's defaults) before any Bash command that
runs `git push`, so the order or chaining of the command no longer matters. It checks the working
tree, so commit first. Exit 2 blocks the command and shows the message to Claude.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# "git push", also with options before the subcommand ("git -c k=v push"); not "git push-something".
PUSH = re.compile(r"(?<![\w.-])git(?:\s+-{1,2}[\w.=-]+(?:\s+[^\s|;&-][^\s|;&]*)?)*\s+push(?![\w-])")
MESSAGE = "Blocked by .claude/hooks/tests_before_push.py: {check} fails, so nothing is pushed. Fix it first:\n{output}"


def runs_push(command):
    return bool(PUSH.search(command))


def python(root):
    return str(root / ".venv" / ("Scripts" if os.name == "nt" else "bin") / "python")


def check(root, args):
    return subprocess.run(
        [python(root), "-m", *args],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


CHECKS = (
    ("make lint (ruff check .)", ["ruff", "check", ".", "--output-format", "concise"]),
    ("make test (pytest)", ["pytest", "-q", "-p", "no:cacheprovider"]),
)


def main():
    try:
        command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    except ValueError:
        return 0
    if not runs_push(command or ""):
        return 0
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
    for name, args in CHECKS:
        result = check(root, args)
        if result.returncode != 0:
            output = "\n".join((result.stdout or result.stderr).strip().splitlines()[-15:])
            print(MESSAGE.format(check=name, output=output), file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

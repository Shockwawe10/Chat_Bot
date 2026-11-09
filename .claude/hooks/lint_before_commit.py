"""PreToolUse hook for Bash: block a git commit while ruff check . fails.

CLAUDE.md requires make lint before every push. Twice on 2026-11-09 a commit went in with a lint
error anyway: once `make lint | tail -1` hid the exit code, once `make lint; git commit` ran the
commit after the failure (LESSONS.md). This hook makes the order of the command irrelevant: any
Bash command that runs `git commit` is blocked, with ruff's findings, until `ruff check .` passes
on the working tree. Exit 2 blocks the command and shows the message to Claude.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

# "git commit", also with options before the subcommand ("git -c k=v commit"); not "git commit-tree".
COMMIT = re.compile(r"(?<![\w.-])git(?:\s+-{1,2}[\w.=-]+(?:\s+[^\s|;&-][^\s|;&]*)?)*\s+commit(?![\w-])")
MESSAGE = (
    "Blocked by .claude/hooks/lint_before_commit.py: ruff check . fails, so nothing is committed. "
    "Fix these first (ruff check . --fix fixes import order):\n{findings}"
)


def runs_commit(command):
    return bool(COMMIT.search(command))


def ruff(root):
    python = root / ".venv" / ("Scripts" if os.name == "nt" else "bin") / "python"
    return subprocess.run(
        [str(python), "-m", "ruff", "check", ".", "--output-format", "concise"],
        cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
    )


def main():
    try:
        command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    except ValueError:
        return 0
    if not runs_commit(command or ""):
        return 0
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
    result = ruff(root)
    if result.returncode != 0:
        findings = "\n".join((result.stdout or result.stderr).strip().splitlines()[-15:])
        print(MESSAGE.format(findings=findings), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

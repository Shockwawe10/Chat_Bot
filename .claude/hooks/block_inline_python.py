"""PreToolUse hook for Bash: block Python run from a heredoc or a long python -c.

CLAUDE.md: Python longer than about 15 lines, or with nested quotes, goes in a
scratchpad .py file written with the Write tool, never through a bash heredoc.
The rule alone did not stop it (LESSONS.md, 2026-11-02 and 2026-11-04), so this
hook enforces it. Exit 2 blocks the command and shows the message to Claude.
Plain file appends such as  cat >> file <<'EOF'  are not blocked.
"""

import json
import re
import sys

MAX_INLINE = 300
PYTHON = r"python(?:3(?:\.\d+)?)?(?:\.exe)?"
# A python call followed by "<<" in the same simple command (stops at | ; & and newlines).
HEREDOC = re.compile(rf"(?<![\w.-]){PYTHON}\b[^\n|;&]*<<")
INLINE = re.compile(rf"(?<![\w.-]){PYTHON}\b(?:\s+-[A-Za-z]+)*?\s+-c\s+(\"(?:\\.|[^\"\\])*\"|'[^']*')", re.S)
MESSAGE = (
    "Blocked by .claude/hooks/block_inline_python.py: {why}. Write the Python to a scratchpad "
    ".py file with the Write tool and run that file (CLAUDE.md rule)."
)


def reason(command):
    if HEREDOC.search(command):
        return "Python run from a heredoc"
    for match in INLINE.finditer(command):
        code = match.group(1)[1:-1]
        if "\n" in code:
            return "python -c with code spanning more than one line"
        if len(code) > MAX_INLINE:
            return f"python -c with {len(code)} characters of code (limit {MAX_INLINE})"
    return None


def main():
    try:
        command = json.load(sys.stdin).get("tool_input", {}).get("command", "")
    except ValueError:
        return 0
    why = reason(command or "")
    if why:
        print(MESSAGE.format(why=why), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())

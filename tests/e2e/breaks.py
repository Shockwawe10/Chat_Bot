"""Break copies of the chat window and check the browser tests catch each break: python -m tests.e2e.breaks

Like evals/mutation_check.py, it never edits the real ui/app.py: each break is written to a copy in
a temporary folder, and the browser tests load it through E2E_UI_APP. Takes about a minute.
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from app.settings import ROOT

BREAKS = {
    "sources never shown": ('    if turn.get("sources"):\n', "    if False:\n"),
    "raw error text shown": (
        "        return None, UNAVAILABLE\n    return response.json(), None\n",
        "        return None, response.text\n    return response.json(), None\n",
    ),
    "a proposed booking shown as booked": ('            if booking["status"] == "confirmed":\n', "            if True:\n"),
    "empty input sent": ("    if message and message.strip():\n", "    if message is not None:\n"),
    "the question shown only with the answer": ('        with st.chat_message("user"):\n            st.markdown(text)\n', ""),
}


def main():
    source = (ROOT / "ui" / "app.py").read_text(encoding="utf-8")
    survived = []
    with tempfile.TemporaryDirectory(prefix="ui-breaks-") as folder:
        for name, (old, new) in BREAKS.items():
            if source.count(old) != 1:
                sys.exit(f"{name}: the text to break is not in ui/app.py exactly once")
            copy = Path(folder) / f"app_{len(survived)}_{name.replace(' ', '_')}.py"
            copy.write_text(source.replace(old, new), encoding="utf-8")
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "tests/e2e", "-m", "e2e", "-q", "-p", "no:cacheprovider"],
                cwd=ROOT, env={**os.environ, "E2E_UI_APP": str(copy)},
                capture_output=True, text=True, encoding="utf-8", errors="replace", check=False,
            )
            failed = [line.split("::")[1].split(" ")[0] for line in result.stdout.splitlines() if line.startswith("FAILED")]
            print(f"{'caught' if failed else 'SURVIVED'}  {name}  {' '.join(failed)}", flush=True)
            if not failed:
                survived.append(name)
    print(f"total {len(BREAKS)}, caught {len(BREAKS) - len(survived)}, survived: {survived or 'none'}")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())

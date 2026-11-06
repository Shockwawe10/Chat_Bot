"""Make a promptfoo result file safe to commit: absolute local paths become project-relative.

    python -m evals.promptfoo_clean reports/security/promptfoo-latest.json

promptfoo writes the absolute path of its config (basePath), which holds the local user name.
`make redteam` runs this after every red-team run.
"""

import json
import sys
from pathlib import Path

from app.settings import ROOT


def relative(value, root=None):
    """Every string under `value` with the project's absolute path replaced by a relative one."""
    root = ROOT if root is None else root
    if isinstance(value, dict):
        return {key: relative(item, root) for key, item in value.items()}
    if isinstance(value, list):
        return [relative(item, root) for item in value]
    if isinstance(value, str):
        prefix = str(root.resolve()).lower()
        lowered = value.lower()
        if prefix in lowered:
            start = lowered.index(prefix)
            rest = value[start + len(prefix) :].lstrip("\\/").replace("\\", "/")
            return value[:start] + (rest or ".")
    return value


def main(argv=None):
    for name in argv if argv is not None else sys.argv[1:]:
        path = Path(name)
        data = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps(relative(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())

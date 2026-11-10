"""Start the API in its container: check Ollama, a fresh demo database, a fresh index, then the server.

    python docker/start_api.py      # the api service in docker-compose.yml runs this

Ollama must be the version pinned in OLLAMA_VERSION (.env.example), the one the committed evals
ran on: an Ollama update once changed an answer while every gate passed (reports/drift.md).
The database is rebuilt from the CSV files on every start, so leads and bookings made in the
demo do not outlive a restart. The index is rebuilt too, so it always matches the knowledge
base in the image. Written in Python, not sh, so a Windows checkout with CRLF line endings
still runs.
"""

import os
import subprocess
import sys

import httpx

STEPS = (
    [sys.executable, "-m", "mcp_server.seed"],
    [sys.executable, "-m", "app.index", "build"],
)
SERVER = [
    sys.executable, "-m", "uvicorn", "app.api:create_default_app", "--factory",
    "--host", "0.0.0.0", "--port", "8000",
]


def ollama_problem(env, get=httpx.get):
    """Why the API must not start on this Ollama, or None when it is the pinned version."""
    url, pinned = env.get("OLLAMA_URL", ""), env.get("OLLAMA_VERSION", "")
    try:
        version = get(f"{url}/api/version", timeout=10).json()["version"]
    except (httpx.HTTPError, ValueError, KeyError) as error:
        return f"no Ollama at {url} ({error.__class__.__name__}); start the desktop Ollama"
    if version != pinned:
        return f"Ollama at {url} is {version}, not the pinned {pinned} (OLLAMA_VERSION in .env.example)"
    return None


def main():
    problem = ollama_problem(os.environ)
    if problem:
        sys.exit(f"start: {problem}")
    for step in STEPS:
        print("start:", " ".join(step[1:]), flush=True)
        subprocess.run(step, check=True)
    os.execv(SERVER[0], SERVER)


if __name__ == "__main__":
    main()

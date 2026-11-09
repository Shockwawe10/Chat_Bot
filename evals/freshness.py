"""Is a saved run still about this commit? The freshness gate for runs checked in CI.

CI has no model, so it checks the committed runs (reports/latest.json, reports/security/latest.json)
instead of making new ones. That only means something if those runs were made with what is in
the commit. Every run records:

- inputs_sha256: a digest of everything that shapes an answer: the app code, the answer prompt,
  the knowledge base, the example questions and the allowed contacts. Line endings are
  normalised, because Git stores LF and a Windows checkout has CRLF: the index fingerprint
  differs between the two and cannot be compared in CI.
- settings: the environment values that shape an answer, with the code's defaults filled in.

A run is fresh when both match the commit, and its settings are the documented defaults in
.env.example. Change a prompt, a document or a setting, and CI fails until a new run is committed.

The run must also be made on the Ollama version pinned in .env.example (OLLAMA_VERSION). Ollama
updates itself, and one update changed an answer while every gate still passed (reports/drift.md).
"""

import hashlib

from dotenv import dotenv_values

from app.settings import ROOT

ENV_EXAMPLE = ROOT / ".env.example"
# Keys that change what the chatbot answers, with the code's default when a key is not set.
SETTINGS = {
    "PROMPT_VERSION": "v2",
    "TOP_K": "5",
    "RETRIEVAL": "dense",
    "ANSWER_CHECK": "off",
    "ANSWER_CHECK_MODEL": "",
    "ANSWER_CHECK_DIGEST": "",
    "OUTPUT_GUARD": "on",
    "LLM_MODEL": "",
    "LLM_DIGEST": "",
    "LLM_SEED": "42",
    "LLM_NUM_CTX": "4096",
    "LLM_NUM_PREDICT": "512",
    "TEMPERATURE": "0",
    "EMBEDDING_MODEL": "",
    "EMBEDDING_DIGEST": "",
    "CHUNK_SIZE": "500",
    "CHUNK_MAX": "800",
    "CHUNK_MIN": "100",
}


def settings(env):
    """The answer-shaping settings of an environment, defaults filled in, as strings."""
    return {key: str(env.get(key) or default) for key, default in SETTINGS.items()}


def answer_inputs(prompt_version, root=ROOT):
    """The files that shape an answer, as paths relative to the project, sorted."""
    files = sorted((root / "app").glob("*.py"))
    files += [root / "prompts" / f"answer_{prompt_version}.txt"]
    files += sorted((root / "data" / "kb").glob("*.md"))
    files += [root / "data" / "chunk_questions.json", root / "data" / "allowed_contacts.txt"]
    return files


def inputs_digest(prompt_version, root=ROOT):
    """sha256 over each input's relative path and its text with LF line endings."""
    digest = hashlib.sha256()
    for path in answer_inputs(prompt_version, root):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


def agent_inputs(root=ROOT):
    """The files that shape the agent's behaviour on its dev cases (Stage 6), sorted."""
    files = sorted((root / "app").glob("*.py")) + sorted((root / "mcp_server").glob("*.py"))
    files += sorted((root / "prompts").glob("agent_*.txt")) + [root / "data" / "allowed_contacts.txt"]
    files += [root / "data" / name for name in ("leads.csv", "products.csv", "projects.csv")]
    files += [root / "evals" / name for name in ("agent_cases.jsonl", "agent_attacks.jsonl", "agent_eval.py")]
    return files


def agent_inputs_digest(root=ROOT):
    """sha256 over the agent's inputs, like inputs_digest: relative path and text with LF line endings."""
    digest = hashlib.sha256()
    for path in agent_inputs(root):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes().replace(b"\r\n", b"\n"))
        digest.update(b"\0")
    return digest.hexdigest()


def stamp(env, root=ROOT):
    """What a run records about its inputs."""
    current = settings(env)
    return {"inputs_sha256": inputs_digest(current["PROMPT_VERSION"], root), "settings": current}


def pinned_ollama(env_example=None):
    """The Ollama version committed runs are made on (OLLAMA_VERSION in .env.example), or None."""
    return dotenv_values(env_example or ENV_EXAMPLE).get("OLLAMA_VERSION") or None


def ollama_problem(version, pinned):
    """Why an Ollama version is not the pinned one, or None. No pin, no problem."""
    if pinned and version != pinned:
        return f"Ollama {version or 'unknown'} is not the pinned {pinned} (OLLAMA_VERSION in .env.example)"
    return None


def problems(report, root=ROOT, env_example=None):
    """Why a saved run is not about this commit, or an empty list."""
    if "inputs_sha256" not in report or "settings" not in report:
        return ["the run records no inputs digest or settings; make a new run"]
    found = []
    documented = settings(dotenv_values(env_example or ENV_EXAMPLE))
    changed = sorted(key for key in SETTINGS if report["settings"].get(key) != documented[key])
    if changed:
        found.append(f"settings differ from .env.example: {', '.join(changed)}")
    version = ollama_problem(report.get("ollama_version"), pinned_ollama(env_example))
    if version:
        found.append(version)
    version = report["settings"].get("PROMPT_VERSION", "v2")
    if not (root / "prompts" / f"answer_{version}.txt").exists():
        found.append(f"prompt {version} is not in the commit")
    elif report["inputs_sha256"] != inputs_digest(version, root):
        found.append("app code, prompt, knowledge base or contacts changed since the run; make a new run")
    return found

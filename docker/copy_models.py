"""Copy the three models the app uses from this PC's Ollama into the Docker volume: make docker-models.

Only for Ollama in Docker (docker-compose.ollama.yml); the default demo uses the desktop Ollama.

    python docker/copy_models.py            # models dir: OLLAMA_MODELS, else ~/.ollama/models

The models are the ones named in .env.example (answer, embeddings, answer check). Only their
manifests and the blobs those list are copied, so about 7.5 GB instead of everything on the PC
and nothing is downloaded. The app checks each model's digest when it starts, so a wrong copy
shows up there. A model the PC does not have can be pulled inside the container instead:
docker compose exec ollama ollama pull <model>.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
MODEL_KEYS = ("LLM_MODEL", "EMBEDDING_MODEL", "ANSWER_CHECK_MODEL")
VOLUME = "rag-ollama-models"
MANIFEST_DIRS = ("manifests/registry.ollama.ai/library", "manifests-v2/ollama.com/library")


def models_dir():
    return Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")


def wanted_models(env_example=ROOT / ".env.example"):
    env = dotenv_values(env_example)
    return [env[key] for key in MODEL_KEYS]


def ollama_image(compose=ROOT / "docker-compose.ollama.yml"):
    return yaml.safe_load(compose.read_text(encoding="utf-8"))["services"]["ollama"]["image"]


def files_for(model, source):
    """The paths, relative to the models dir, that make up one model: its manifests and blobs."""
    name, _, tag = model.partition(":")
    manifests = [f"{folder}/{name}/{tag or 'latest'}" for folder in MANIFEST_DIRS]
    manifests = [path for path in manifests if (source / path).is_file()]
    if not manifests:
        raise SystemExit(f"{model} is not in {source}; pull it on the PC first (ollama pull {model})")
    manifest = json.loads((source / manifests[0]).read_text(encoding="utf-8"))
    digests = [manifest["config"]["digest"], *(layer["digest"] for layer in manifest["layers"])]
    blobs = [f"blobs/{digest.replace(':', '-')}" for digest in digests]
    missing = [blob for blob in blobs if not (source / blob).is_file()]
    if missing:
        raise SystemExit(f"{model}: {len(missing)} blob(s) missing in {source}")
    return manifests + blobs


def main():
    source = models_dir()
    paths = []
    for model in wanted_models():
        paths += files_for(model, source)
    size = sum((source / path).stat().st_size for path in paths)
    print(f"copying {len(paths)} files, {size / 1e9:.2f} GB, from {source} into the {VOLUME} volume")
    script = " && ".join(f"mkdir -p \"/dst/$(dirname '{p}')\" && cp -u '/src/{p}' '/dst/{p}'" for p in paths)
    command = [
        "docker", "run", "--rm", "--entrypoint", "sh",
        "-v", f"{source}:/src:ro", "-v", f"{VOLUME}:/dst",
        ollama_image(), "-c", script,
    ]
    sys.exit(subprocess.run(command, check=False).returncode)


if __name__ == "__main__":
    main()

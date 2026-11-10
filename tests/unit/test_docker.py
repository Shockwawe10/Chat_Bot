"""The Docker files stay in step with the rest of the project.

The image must run the versions the tests and evals ran on, the Ollama container must be the
pinned Ollama, secrets and local state must stay out of the image, and only the chat window
may be reachable, and only from this PC.
"""

import ast
import json
import sys
from pathlib import Path

import httpx
import pytest
import yaml
from dotenv import dotenv_values

from docker import copy_models, start_api

ROOT = Path(__file__).resolve().parents[2]
# Import name -> package name, where they differ. pydantic comes with fastapi.
PACKAGE_OF = {"dotenv": "python-dotenv", "yaml": "PyYAML", "markdown_it": "markdown-it-py", "pydantic": "fastapi"}
FIRST_PARTY = {"app", "mcp_server", "ui"}


def pins(path):
    lines = (line.strip() for line in path.read_text(encoding="utf-8").splitlines())
    return dict(line.split("==") for line in lines if line and not line.startswith("#"))


def compose(name="docker-compose.yml"):
    return yaml.safe_load((ROOT / name).read_text(encoding="utf-8"))


def imported_modules():
    names = set()
    for folder in FIRST_PARTY:
        for path in (ROOT / folder).rglob("*.py"):
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                if isinstance(node, ast.Import):
                    names |= {alias.name.split(".")[0] for alias in node.names}
                elif isinstance(node, ast.ImportFrom) and node.level == 0:
                    names.add(node.module.split(".")[0])
    return names - FIRST_PARTY - set(sys.stdlib_module_names)


def test_the_image_pins_equal_the_project_pins():
    project, image = pins(ROOT / "requirements.txt"), pins(ROOT / "requirements-app.txt")
    assert {name: project.get(name) for name in image} == image


def test_every_package_the_app_imports_is_installed_in_the_image():
    image = {name.lower() for name in pins(ROOT / "requirements-app.txt")}
    missing = {name for name in imported_modules() if PACKAGE_OF.get(name, name).lower() not in image}
    assert not missing


def test_the_base_image_and_the_ollama_image_are_pinned_by_digest():
    base = next(line for line in (ROOT / "Dockerfile").read_text(encoding="utf-8").splitlines() if line.startswith("FROM"))
    assert "@sha256:" in base
    assert "@sha256:" in compose("docker-compose.ollama.yml")["services"]["ollama"]["image"]


def test_the_ollama_container_is_the_pinned_ollama_version():
    pinned = dotenv_values(ROOT / ".env.example")["OLLAMA_VERSION"]
    image = compose("docker-compose.ollama.yml")["services"]["ollama"]["image"]
    assert image.split("@")[0] == f"ollama/ollama:{pinned}"


@pytest.mark.parametrize("path", [".env", "data/app.db", ".chroma/", "runs/", ".git/"])
def test_secrets_and_local_state_stay_out_of_the_image(path):
    ignored = (ROOT / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert path in ignored


@pytest.mark.parametrize("name", ["docker-compose.yml", "docker-compose.ollama.yml"])
def test_only_the_chat_window_has_a_port_and_only_on_this_pc(name):
    services = {**compose()["services"], **compose(name)["services"]}
    published = {service: config.get("ports", []) for service, config in services.items()}
    assert published.pop("ui") == ["127.0.0.1:8501:8501"]
    assert not any(published.values())


def test_the_containers_use_the_committed_settings_and_the_desktop_ollama_the_evals_ran_on():
    api = compose()["services"]["api"]
    assert api["env_file"] == ".env.example"
    assert api["environment"] == {"OLLAMA_URL": "http://host.docker.internal:11434"}
    assert compose("docker-compose.ollama.yml")["services"]["api"]["environment"] == {"OLLAMA_URL": "http://ollama:11434"}


def test_the_telegram_bot_is_optional_and_its_token_comes_only_from_the_local_env():
    telegram = compose()["services"]["telegram"]
    assert telegram["profiles"] == ["telegram"] and "ports" not in telegram
    assert telegram["environment"]["TELEGRAM_BOT_TOKEN"] == "${TELEGRAM_BOT_TOKEN:-}"
    assert dotenv_values(ROOT / ".env.example")["TELEGRAM_BOT_TOKEN"] == ""


class Reply:
    def __init__(self, body):
        self.body = body

    def json(self):
        return self.body


def answering(body):
    return lambda url, timeout: Reply(body)


def unreachable(url, timeout):
    raise httpx.ConnectError("refused")


ENV = {"OLLAMA_URL": "http://host.docker.internal:11434", "OLLAMA_VERSION": "0.40.15"}


def test_the_api_starts_only_on_the_pinned_ollama_version():
    assert start_api.ollama_problem(ENV, answering({"version": "0.40.15"})) is None
    assert "not the pinned 0.40.15" in start_api.ollama_problem(ENV, answering({"version": "0.41.0"}))
    assert "no Ollama" in start_api.ollama_problem(ENV, unreachable)
    assert "no Ollama" in start_api.ollama_problem(ENV, answering({}))


def write_model(models, name, tag, digests):
    manifest = models / "manifests/registry.ollama.ai/library" / name / tag
    manifest.parent.mkdir(parents=True)
    layers = [{"digest": digest} for digest in digests[1:]]
    manifest.write_text(json.dumps({"config": {"digest": digests[0]}, "layers": layers}), encoding="utf-8")
    (models / "blobs").mkdir(exist_ok=True)
    for digest in digests:
        (models / "blobs" / digest.replace(":", "-")).write_bytes(b"x")


def test_copying_a_model_takes_its_manifest_and_only_the_blobs_it_lists(tmp_path):
    write_model(tmp_path, "qwen3", "4b-instruct", ["sha256:aa", "sha256:bb"])
    write_model(tmp_path, "other", "1b", ["sha256:cc"])
    assert copy_models.files_for("qwen3:4b-instruct", tmp_path) == [
        "manifests/registry.ollama.ai/library/qwen3/4b-instruct",
        "blobs/sha256-aa",
        "blobs/sha256-bb",
    ]


def test_a_model_missing_on_the_pc_or_with_a_missing_blob_stops_the_copy(tmp_path):
    write_model(tmp_path, "qwen3", "4b-instruct", ["sha256:aa", "sha256:bb"])
    (tmp_path / "blobs" / "sha256-bb").unlink()
    with pytest.raises(SystemExit, match="missing"):
        copy_models.files_for("qwen3:4b-instruct", tmp_path)
    with pytest.raises(SystemExit, match="not in"):
        copy_models.files_for("phi4-mini:3.8b", tmp_path)


def test_the_models_copied_are_the_three_the_app_uses():
    env = dotenv_values(ROOT / ".env.example")
    assert copy_models.wanted_models() == [env["LLM_MODEL"], env["EMBEDDING_MODEL"], env["ANSWER_CHECK_MODEL"]]

"""Start the stand-in API and the Streamlit chat window for the browser tests, once per session."""

import os
import socket
import subprocess
import sys
import time

import httpx
import pytest

from app.settings import ROOT


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for(url, process, seconds=60):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{url}: the process exited with code {process.returncode}")
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"{url} did not answer within {seconds} s")


def start(args, url, env=None):
    process = subprocess.Popen(
        [sys.executable, *args], cwd=ROOT, env={**os.environ, **(env or {})},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    wait_for(url, process)
    return process


@pytest.fixture(scope="session")
def stub_api():
    port = free_port()
    process = start(["-m", "uvicorn", "tests.e2e.stub_api:app", "--host", "127.0.0.1", "--port", str(port)], f"http://127.0.0.1:{port}/docs")
    yield f"http://127.0.0.1:{port}"
    process.terminate()
    process.wait(10)


def streamlit(api_url):
    port = free_port()
    # E2E_UI_APP runs another copy of the window, such as a deliberately broken one (README, browser tests).
    app = os.environ.get("E2E_UI_APP", "ui/app.py")
    args = ["-m", "streamlit", "run", app, "--server.headless", "true", "--server.port", str(port),
            "--server.address", "127.0.0.1", "--browser.gatherUsageStats", "false"]
    return start(args, f"http://127.0.0.1:{port}/_stcore/health", {"API_URL": api_url}), f"http://127.0.0.1:{port}"


@pytest.fixture(scope="session")
def chat_url(stub_api):
    process, url = streamlit(stub_api)
    yield url
    process.terminate()
    process.wait(10)


@pytest.fixture(scope="session")
def chat_url_without_api():
    """The chat window pointed at a port where nothing listens: the API is down."""
    process, url = streamlit(f"http://127.0.0.1:{free_port()}")
    yield url
    process.terminate()
    process.wait(10)

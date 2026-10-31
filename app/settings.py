"""Reads project settings: .env first, then the process environment, which wins."""

import os
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def read_env():
    return {**dotenv_values(ENV_FILE), **os.environ}

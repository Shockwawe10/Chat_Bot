"""The SQLite database behind the MCP tools: schema, the fixed vocabularies, and connections.

The vocabularies come from the knowledge base, and tests/data/test_demo_data.py checks they still
agree with it: the 8 stages of data/kb/process-cooperation-stages.md, the 3 sales regions of
data/kb/company-overview.md, and the corrosivity categories of data/kb/corrosion-categories.md.
"""

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from app.settings import ROOT, read_env

DEFAULT_DB = ROOT / "data" / "app.db"

STAGES = (
    "Request",
    "Site survey",
    "Preliminary design and commercial offer",
    "Contract",
    "Detailed design",
    "Supply",
    "Installation",
    "Handover",
)
REGIONS = ("North", "Central", "South")
MOUNT_TYPES = ("ground", "flat_roof", "pitched_roof", "carport")
# CX is a category, but the company offers no system for it (corrosion-categories.md).
CATEGORIES = ("C1", "C2", "C3", "C4", "C5")
MIN_POWER_KW = 100  # "The smallest project it accepts is 100 kWp" (company-overview.md)


def _in(values):
    return "(" + ", ".join(f"'{value}'" for value in values) + ")"


SCHEMA = f"""
CREATE TABLE products (
    product_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    mount_type TEXT NOT NULL CHECK (mount_type IN {_in(MOUNT_TYPES)}),
    mounting TEXT NOT NULL,
    material TEXT NOT NULL,
    max_corrosion_category TEXT NOT NULL CHECK (max_corrosion_category IN {_in(CATEGORIES)}),
    kb_doc TEXT NOT NULL
);
CREATE TABLE leads (
    lead_id TEXT PRIMARY KEY,
    company TEXT NOT NULL,
    contact_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    region TEXT NOT NULL CHECK (region IN {_in(REGIONS)}),
    power_kw REAL NOT NULL CHECK (power_kw >= {MIN_POWER_KW}),
    mount_type TEXT NOT NULL CHECK (mount_type IN {_in(MOUNT_TYPES)}),
    created_at TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'seed' CHECK (source IN ('seed', 'agent'))
);
CREATE TABLE projects (
    project_id TEXT PRIMARY KEY,
    lead_id TEXT NOT NULL REFERENCES leads (lead_id),
    name TEXT NOT NULL,
    region TEXT NOT NULL CHECK (region IN {_in(REGIONS)}),
    power_kw REAL NOT NULL CHECK (power_kw >= {MIN_POWER_KW}),
    mount_type TEXT NOT NULL CHECK (mount_type IN {_in(MOUNT_TYPES)}),
    product_id TEXT NOT NULL REFERENCES products (product_id),
    stage TEXT NOT NULL CHECK (stage IN {_in(STAGES)}),
    stage_updated TEXT NOT NULL,
    comment TEXT NOT NULL DEFAULT ''
);
CREATE TABLE site_surveys (
    survey_id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL REFERENCES projects (project_id),
    survey_date TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'confirmed', 'cancelled')),
    session_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    confirmed_at TEXT
);
"""


def db_path(env=None):
    env = read_env() if env is None else env
    value = env.get("DB_PATH")
    if not value:
        return DEFAULT_DB
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def connect(path=None):
    """A connection with foreign keys on and rows readable by column name. The caller closes it."""
    connection = sqlite3.connect(path or db_path())
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


@contextmanager
def opened(path=None):
    """A connection that commits on success, rolls back on error, and is always closed.

    `with sqlite3.connect(...)` alone commits but leaves the connection open, and on Windows an
    open connection keeps the file locked, so make seed could not replace the database.
    """
    connection = connect(path)
    try:
        with connection:
            yield connection
    finally:
        connection.close()

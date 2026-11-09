"""Build data/app.db from the demo CSV files: make seed.

    python -m mcp_server.seed            # DB_PATH from .env, default data/app.db

The database is rebuilt from scratch each time: leads the agent saved are dropped, and the
products, projects and seeded leads come back exactly as the CSV files say. The new database is
written beside the old one and swapped in only when it is complete, so a failed seed leaves the
old database untouched.
"""

import csv
import sys

from app.settings import ROOT
from mcp_server.db import SCHEMA, connect, db_path

DATA = ROOT / "data"
TABLES = (  # in foreign-key order
    ("products", DATA / "products.csv"),
    ("leads", DATA / "leads.csv"),
    ("projects", DATA / "projects.csv"),
)


def read_rows(path):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def build(target, data_dir=None):
    """Write a fresh database to target. Returns {table: rows}."""
    tables = [(name, (data_dir / path.name) if data_dir else path) for name, path in TABLES]
    partial = target.with_name(target.name + ".partial")
    partial.unlink(missing_ok=True)
    counts = {}
    connection = connect(partial)
    try:
        with connection:
            connection.executescript(SCHEMA)
            for table, path in tables:
                rows = read_rows(path)
                columns = list(rows[0])
                marks = ", ".join("?" for _ in columns)
                connection.executemany(
                    f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({marks})",
                    [tuple(row[column] for column in columns) for row in rows],
                )
                counts[table] = len(rows)
            counts["site_surveys"] = 0
    finally:
        connection.close()
    partial.replace(target)
    return counts


def main():
    target = db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    counts = build(target)
    print(f"built {target.relative_to(ROOT) if target.is_relative_to(ROOT) else target}: " + ", ".join(f"{t} {n}" for t, n in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())

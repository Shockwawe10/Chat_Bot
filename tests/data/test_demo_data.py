"""The demo company data (data/*.csv) and its database (make seed) agree with the knowledge base.

The agent answers from both: a product fact in products.csv that differs from data/kb would make
the agent and the RAG pipeline contradict each other.
"""

import csv
import re
import sqlite3

import pytest

from app.settings import ROOT
from mcp_server.db import CATEGORIES, MIN_POWER_KW, MOUNT_TYPES, REGIONS, STAGES, opened
from mcp_server.seed import build

KB = ROOT / "data" / "kb"


def rows(name):
    with open(ROOT / "data" / name, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


PRODUCTS, LEADS, PROJECTS = rows("products.csv"), rows("leads.csv"), rows("projects.csv")


def kb_text(doc):
    return (KB / f"{doc}.md").read_text(encoding="utf-8").replace("\r\n", "\n")


def overview_table():
    """{product name: (mounting, material, category)} from the products overview page."""
    table = {}
    for line in kb_text("products-overview").splitlines():
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) == 4 and re.fullmatch(r"C\d", cells[3]):
            table[cells[0]] = tuple(cells[1:])
    return table


def test_every_product_is_the_one_in_the_kb_overview_with_the_same_facts():
    table = overview_table()
    assert len(table) == 6
    assert {p["name"]: (p["mounting"], p["material"], p["max_corrosion_category"]) for p in PRODUCTS} == table


def test_every_product_points_at_its_own_kb_document():
    for product in PRODUCTS:
        assert product["name"] in kb_text(product["kb_doc"]), product["product_id"]


def test_the_stages_are_the_eight_of_the_kb_process_page():
    numbered = re.findall(r"^\d+\. \*\*(.+?)\.\*\*", kb_text("process-cooperation-stages"), re.MULTILINE)
    assert tuple(numbered) == STAGES


def test_the_regions_and_the_smallest_project_are_the_kb_s():
    overview = kb_text("company-overview")
    assert "three sales regions: North, Central and South" in overview and REGIONS == ("North", "Central", "South")
    assert f"The smallest project it accepts is {MIN_POWER_KW} kWp" in overview


def test_the_categories_are_the_kb_s_without_cx():
    text = kb_text("corrosion-categories")
    assert all(f"| {category} |" in text for category in CATEGORIES)
    assert "The company does not offer any system for category CX." in text and "CX" not in CATEGORIES


def test_contacts_are_clearly_fake():
    """Synthetic contacts only: reserved .test domains, the 555-01xx fictional range, -Test names."""
    assert len({lead["email"] for lead in LEADS}) == len(LEADS)
    for lead in LEADS:
        assert lead["email"].endswith(".test"), lead["lead_id"]
        assert re.fullmatch(r"\+1-555-01\d\d", lead["phone"]), lead["lead_id"]
        assert lead["contact_name"].endswith("-Test") and " Test " in f" {lead['company']} ", lead["lead_id"]


def test_each_project_matches_its_lead_and_a_product_of_its_mount_type():
    leads = {lead["lead_id"]: lead for lead in LEADS}
    products = {product["product_id"]: product for product in PRODUCTS}
    for project in PROJECTS:
        lead = leads[project["lead_id"]]
        assert (project["region"], project["power_kw"], project["mount_type"]) == (lead["region"], lead["power_kw"], lead["mount_type"])
        assert products[project["product_id"]]["mount_type"] == project["mount_type"], project["project_id"]
        assert project["mount_type"] in MOUNT_TYPES and project["stage"] in STAGES


def test_one_project_comment_carries_the_planted_injection_and_no_other_does():
    """P-1006's comment is a deliberate indirect-injection test (README, Stage 6). Nothing else may carry one."""
    planted = [p["project_id"] for p in PROJECTS if "ignore your previous instructions" in p["comment"].lower()]
    assert planted == ["P-1006"]


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "app.db"
    return path, build(path)


def test_seed_loads_every_row(database):
    path, counts = database
    assert counts == {"products": 6, "leads": len(LEADS), "projects": len(PROJECTS), "site_surveys": 0}
    with opened(path) as connection:
        assert connection.execute("SELECT count(*) FROM projects").fetchone()[0] == len(PROJECTS)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO projects VALUES ('P-9', 'L-999', 'x', 'North', 500, 'ground', 'GF-1', 'Request', '2026-11-01', '')",
        "INSERT INTO projects VALUES ('P-9', 'L-001', 'x', 'North', 500, 'ground', 'XX-9', 'Request', '2026-11-01', '')",
        "INSERT INTO projects VALUES ('P-9', 'L-001', 'x', 'North', 500, 'ground', 'GF-1', 'Done', '2026-11-01', '')",
        "INSERT INTO leads (lead_id, company, contact_name, email, phone, region, power_kw, mount_type, created_at) VALUES ('L-9', 'c', 'n', 'e', 'p', 'North', 50, 'ground', '2026-11-01')",
        "INSERT INTO leads (lead_id, company, contact_name, email, phone, region, power_kw, mount_type, created_at) VALUES ('L-9', 'c', 'n', 'e', 'p', 'West', 500, 'ground', '2026-11-01')",
        "INSERT INTO site_surveys (project_id, survey_date, status, session_id, created_at) VALUES ('P-1001', '2026-12-01', 'booked', 's', 'now')",
    ],
    ids=["unknown lead", "unknown product", "unknown stage", "under 100 kWp", "unknown region", "unknown survey status"],
)
def test_the_database_refuses_data_the_kb_rules_out(database, statement):
    path, _ = database
    with opened(path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute(statement)


def test_a_reseed_drops_what_the_agent_saved(database):
    path, _ = database
    with opened(path) as connection:
        connection.execute(
            "INSERT INTO leads VALUES ('L-100', 'c', 'n', 'e@x.test', '+1-555-0199', 'North', 500, 'ground', '2026-11-01', 'agent')"
        )
    build(path)
    with opened(path) as connection:
        assert connection.execute("SELECT count(*) FROM leads WHERE source = 'agent'").fetchone()[0] == 0


def test_a_failed_seed_leaves_the_old_database_untouched(database, tmp_path):
    path, _ = database
    bad = tmp_path / "bad"
    bad.mkdir()
    for name in ("products.csv", "leads.csv"):
        (bad / name).write_text((ROOT / "data" / name).read_text(encoding="utf-8"), encoding="utf-8")
    (bad / "projects.csv").write_text(
        "project_id,lead_id,name,region,power_kw,mount_type,product_id,stage,stage_updated,comment\n"
        "P-9,L-999,x,North,500,ground,GF-1,Request,2026-11-01,\n",
        encoding="utf-8",
    )
    with pytest.raises(sqlite3.IntegrityError):
        build(path, bad)
    with opened(path) as connection:
        assert connection.execute("SELECT count(*) FROM projects").fetchone()[0] == len(PROJECTS)

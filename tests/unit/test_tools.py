"""The four MCP tools (mcp_server/tools.py) on a freshly seeded database. No model, no MCP SDK."""

import csv
from datetime import date

import pytest

from app.settings import ROOT
from mcp_server import tools
from mcp_server.db import opened
from mcp_server.seed import build

MONDAY = date(2026, 11, 9)
with open(ROOT / "data" / "leads.csv", encoding="utf-8", newline="") as handle:
    SEEDED = list(csv.DictReader(handle))


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "app.db"
    build(path)
    return path


def lead(db, **changes):
    args = {
        "company": "Riverside Mill Test Ltd", "region": "Central", "power_kw": 450, "mount_type": "flat_roof",
        "contact_name": "Ada Brooks-Test", "email": "ada.brooks@riverside-mill.test", "phone": "+1-555-0150",
    }
    args.update(changes)
    return tools.create_lead(**args, db=db)


def surveys(db):
    with opened(db) as connection:
        return [dict(row) for row in connection.execute("SELECT * FROM site_surveys ORDER BY survey_id")]


# create_lead


def test_a_saved_lead_matches_what_the_customer_said(db):
    result = lead(db)
    saved = result["saved"]
    assert saved["lead_id"] == f"L-{len(SEEDED) + 1:03d}" and saved["source"] == "agent"
    with opened(db) as connection:
        row = dict(connection.execute("SELECT * FROM leads WHERE lead_id = ?", (saved["lead_id"],)).fetchone())
    assert row == saved
    assert (row["company"], row["region"], row["power_kw"], row["mount_type"], row["contact_name"], row["email"], row["phone"]) == (
        "Riverside Mill Test Ltd", "Central", 450.0, "flat_roof", "Ada Brooks-Test", "ada.brooks@riverside-mill.test", "+1-555-0150",
    )


@pytest.mark.parametrize(
    "change, error",
    [
        ({"company": " "}, "missing: company"),
        ({"email": ""}, "missing: email"),
        ({"contact_name": None}, "missing: contact_name"),
        ({"region": "West"}, "region must be one of"),
        ({"power_kw": "500"}, "must be a number"),
        ({"power_kw": True}, "must be a number"),
        ({"power_kw": 99.9}, "smallest project the company accepts is 100 kWp"),
        ({"mount_type": "roof"}, "mount_type must be one of"),
        ({"email": "ada at riverside"}, "is not an email address"),
        ({"email": "MIRA.OLSEN@northwind-logistics.test"}, "already exists"),
    ],
    ids=["no company", "no email", "no contact name", "unknown region", "power as text", "power as bool", "under 100 kWp",
         "unknown mount type", "bad email", "existing email"],
)
def test_a_lead_the_kb_rules_out_or_that_lacks_data_is_refused_and_nothing_is_saved(db, change, error):
    assert error in lead(db, **change)["error"]
    with opened(db) as connection:
        assert connection.execute("SELECT count(*) FROM leads").fetchone()[0] == len(SEEDED)


def test_exactly_100_kwp_is_accepted_and_ids_keep_counting(db):
    assert lead(db, power_kw=100)["saved"]["lead_id"] == "L-009"
    assert lead(db, email="second@riverside-mill.test")["saved"]["lead_id"] == "L-010"


# get_project_status


def test_project_status_gives_the_stage_and_never_a_contact(db):
    status = tools.get_project_status("p-1001 ", db=db)
    assert (status["project_id"], status["stage"], status["stage_number"], status["next_stage"]) == (
        "P-1001", "Detailed design", "5 of 8", "Supply",
    )
    text = str(status)
    for seeded in SEEDED:
        assert seeded["email"] not in text and seeded["phone"] not in text and seeded["contact_name"] not in text


def test_the_last_stage_has_no_next_stage(db):
    assert tools.get_project_status("P-1007", db=db)["next_stage"] is None


@pytest.mark.parametrize("project_id, error", [("1001", "is not a project number"), ("P-9999", "there is no project P-9999"), ("", "is not a project number")])
def test_an_unknown_or_malformed_project_is_an_error(db, project_id, error):
    assert error in tools.get_project_status(project_id, db=db)["error"]


def test_the_planted_injection_comes_back_as_data_only(db):
    """P-1006's notes carry an instruction; the tool returns it as notes, and no contact with it."""
    status = tools.get_project_status("P-1006", db=db)
    assert "ignore your previous instructions" in status["notes"]
    assert "mira.olsen" not in str(status) and "555-0101" not in str(status)


# find_product


@pytest.mark.parametrize(
    "mount_type, category, expected",
    [
        ("flat_roof", "C3", ["RF-1", "RF-2"]),
        ("flat_roof", "c4", ["RF-2"]),
        ("ground", "C5", ["GF-2"]),
        ("ground", "C1", ["GF-1", "GF-2"]),
        ("pitched_roof", "C3", ["RP-1"]),
        ("carport", "C4", ["CP-1"]),
    ],
)
def test_find_product_returns_the_systems_rated_for_the_site_or_higher(db, mount_type, category, expected):
    assert [p["product_id"] for p in tools.find_product(mount_type, category, db=db)["products"]] == expected


def test_no_system_for_a_category_says_so(db):
    assert tools.find_product("flat_roof", "C5", db=db) == {"products": [], "note": "No flat roof system is rated for C5."}
    assert tools.find_product("ground", "CX", db=db)["note"] == "The company does not offer any system for category CX."


@pytest.mark.parametrize("mount_type, category", [("roof", "C3"), ("ground", "C6"), ("ground", "")])
def test_find_product_refuses_unknown_inputs(db, mount_type, category):
    assert "must be one of" in tools.find_product(mount_type, category, db=db)["error"]


# book_site_survey and its confirmation


def test_a_booking_stays_pending_until_the_customer_confirms(db):
    proposal = tools.book_site_survey("P-1008", "2026-11-12", session_id="s1", db=db, today=MONDAY)
    assert proposal["status"] == "pending" and "not booked until they do" in proposal["needs_confirmation"]
    assert [s["status"] for s in surveys(db)] == ["pending"]
    confirmed = tools.confirm_pending_survey("s1", db=db)
    assert (confirmed["status"], confirmed["project_id"], confirmed["survey_date"]) == ("confirmed", "P-1008", "2026-11-12")
    assert [s["status"] for s in surveys(db)] == ["confirmed"] and surveys(db)[0]["confirmed_at"]


def test_a_new_proposal_replaces_the_pending_one_of_the_same_conversation(db):
    tools.book_site_survey("P-1008", "2026-11-12", session_id="s1", db=db, today=MONDAY)
    tools.book_site_survey("P-1002", "2026-11-13", session_id="s1", db=db, today=MONDAY)
    assert [(s["project_id"], s["status"]) for s in surveys(db)] == [("P-1008", "cancelled"), ("P-1002", "pending")]


def test_another_conversation_cannot_confirm_a_booking(db):
    tools.book_site_survey("P-1008", "2026-11-12", session_id="s1", db=db, today=MONDAY)
    assert "no pending site survey" in tools.confirm_pending_survey("s2", db=db)["error"]
    assert [s["status"] for s in surveys(db)] == ["pending"]


@pytest.mark.parametrize(
    "project_id, day, error",
    [
        ("P-1008", "2026-11-09", "is not in the future"),
        ("P-1008", "2026-11-01", "is not in the future"),
        ("P-1008", "2026-11-14", "is a weekend"),
        ("P-1008", "next Tuesday", "is not a date"),
        ("P-9999", "2026-11-12", "there is no project P-9999"),
        ("P-1001", "2026-11-12", "past the site survey"),
    ],
    ids=["today", "past", "saturday", "words", "unknown project", "past the survey stage"],
)
def test_a_booking_that_cannot_happen_is_refused_and_nothing_is_saved(db, project_id, day, error):
    assert error in tools.book_site_survey(project_id, day, session_id="s1", db=db, today=MONDAY)["error"]
    assert surveys(db) == []


def test_the_agent_cannot_reach_the_confirmation():
    assert tools.confirm_pending_survey not in tools.AGENT_TOOLS
    assert [tool.__name__ for tool in tools.AGENT_TOOLS] == ["create_lead", "get_project_status", "find_product", "book_site_survey"]

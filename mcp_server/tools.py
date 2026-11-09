"""The four MCP tools as plain functions over data/app.db, testable without a model or the MCP SDK.

mcp_server/server.py exposes exactly these four to the agent. Every tool checks its own inputs and
returns a dict: the result, or {"error": "..."} in words the model can pass on, never an exception.

Two rules hold in code, not in a prompt:
- Data minimisation. No tool returns a customer's email or phone, except create_lead echoing what
  that customer just gave. So another customer's contact can only reach an answer if the model
  invents it, and the /chat guard checks for that (Stage 6, step 3).
- Confirmation outside the model's reach. book_site_survey only makes a pending booking.
  confirm_pending_survey makes it real, and it is not an MCP tool: the /chat layer calls it when
  the customer's own next message confirms. A model cannot confirm a booking by itself.
"""

import re
from datetime import date, datetime

from mcp_server.db import CATEGORIES, MIN_POWER_KW, MOUNT_TYPES, REGIONS, STAGES, opened

PROJECT_ID = re.compile(r"^P-\d{4}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# A survey comes before the design (process-cooperation-stages.md): later stages cannot book one.
SURVEY_STAGES = ("Request", "Site survey")


def _error(text):
    return {"error": text}


def _now():
    return datetime.now().isoformat(timespec="seconds")


def _project(connection, project_id):
    project_id = (project_id or "").strip().upper()
    if not PROJECT_ID.match(project_id):
        return None, _error(f"'{project_id}' is not a project number; project numbers look like P-1001")
    row = connection.execute("SELECT * FROM projects WHERE project_id = ?", (project_id,)).fetchone()
    if row is None:
        return None, _error(f"there is no project {project_id}")
    return row, None


def create_lead(company, region, power_kw, mount_type, contact_name, email, phone="", *, db=None):
    """Save a new customer request. Returns the saved lead, exactly as stored."""
    fields = {"company": company, "contact_name": contact_name, "email": email}
    missing = [name for name, value in fields.items() if not str(value or "").strip()]
    if missing:
        return _error(f"missing: {', '.join(missing)}; ask the customer, never invent it")
    if region not in REGIONS:
        return _error(f"region must be one of {', '.join(REGIONS)}; for other sites, ask the customer to write to sales@example.com")
    if isinstance(power_kw, bool) or not isinstance(power_kw, (int, float)):
        return _error("power_kw must be a number of kWp")
    if power_kw < MIN_POWER_KW:
        return _error(f"the smallest project the company accepts is {MIN_POWER_KW} kWp")
    if mount_type not in MOUNT_TYPES:
        return _error(f"mount_type must be one of {', '.join(MOUNT_TYPES)}")
    if not EMAIL.match(email.strip()):
        return _error(f"'{email}' is not an email address")
    with opened(db) as connection:
        if connection.execute("SELECT 1 FROM leads WHERE lower(email) = lower(?)", (email.strip(),)).fetchone():
            return _error("a request with this email already exists; the sales team will reply to it")
        last = connection.execute("SELECT max(CAST(substr(lead_id, 3) AS INTEGER)) FROM leads").fetchone()[0] or 0
        lead = {
            "lead_id": f"L-{last + 1:03d}",
            "company": company.strip(),
            "contact_name": contact_name.strip(),
            "email": email.strip(),
            "phone": (phone or "").strip(),
            "region": region,
            "power_kw": float(power_kw),
            "mount_type": mount_type,
            "created_at": _now(),
            "source": "agent",
        }
        connection.execute(
            f"INSERT INTO leads ({', '.join(lead)}) VALUES ({', '.join('?' for _ in lead)})", tuple(lead.values())
        )
    return {"saved": lead}


def get_project_status(project_id, *, db=None):
    """A project's stage and notes. Never the customer's contact details."""
    with opened(db) as connection:
        row, error = _project(connection, project_id)
        if error:
            return error
        product = connection.execute("SELECT name FROM products WHERE product_id = ?", (row["product_id"],)).fetchone()
    number = STAGES.index(row["stage"]) + 1
    return {
        "project_id": row["project_id"],
        "name": row["name"],
        "stage": row["stage"],
        "stage_number": f"{number} of {len(STAGES)}",
        "next_stage": STAGES[number] if number < len(STAGES) else None,
        "stage_updated": row["stage_updated"],
        "product": product["name"],
        "notes": row["comment"],
    }


def find_product(mount_type, corrosion_class, *, db=None):
    """The products of a mounting type rated for a site's corrosivity category or higher."""
    if mount_type not in MOUNT_TYPES:
        return _error(f"mount_type must be one of {', '.join(MOUNT_TYPES)}")
    category = (corrosion_class or "").strip().upper()
    if category == "CX":
        return {"products": [], "note": "The company does not offer any system for category CX."}
    if category not in CATEGORIES:
        return _error(f"corrosion_class must be one of {', '.join(CATEGORIES)} or CX")
    with opened(db) as connection:
        rows = connection.execute(
            "SELECT product_id, name, mounting, material, max_corrosion_category FROM products"
            " WHERE mount_type = ? AND max_corrosion_category >= ? ORDER BY product_id",
            (mount_type, category),
        ).fetchall()
    products = [dict(row) for row in rows]
    if not products:
        return {"products": [], "note": f"No {mount_type.replace('_', ' ')} system is rated for {category}."}
    return {"products": products}


def book_site_survey(project_id, survey_date, *, session_id, db=None, today=None):
    """Propose a site survey. It stays pending until the customer confirms (confirm_pending_survey)."""
    today = today or date.today()
    try:
        day = date.fromisoformat((survey_date or "").strip())
    except ValueError:
        return _error(f"'{survey_date}' is not a date; use the form 2026-12-01")
    if day <= today:
        return _error(f"{day.isoformat()} is not in the future")
    if day.weekday() >= 5:
        return _error(f"{day.isoformat()} is a weekend; surveys are on working days")
    with opened(db) as connection:
        row, error = _project(connection, project_id)
        if error:
            return error
        if row["stage"] not in SURVEY_STAGES:
            return _error(f"{row['project_id']} is at the stage '{row['stage']}', past the site survey")
        # One pending proposal per conversation: a new one replaces the old.
        connection.execute(
            "UPDATE site_surveys SET status = 'cancelled' WHERE session_id = ? AND status = 'pending'", (session_id,)
        )
        cursor = connection.execute(
            "INSERT INTO site_surveys (project_id, survey_date, status, session_id, created_at)"
            " VALUES (?, ?, 'pending', ?, ?)",
            (row["project_id"], day.isoformat(), session_id, _now()),
        )
    return {
        "survey_id": cursor.lastrowid,
        "status": "pending",
        "project_id": row["project_id"],
        "survey_date": day.isoformat(),
        "needs_confirmation": "Ask the customer to confirm this date. It is not booked until they do.",
    }


def confirm_pending_survey(session_id, *, db=None):
    """Called by the /chat layer when the customer confirms, never by the model."""
    with opened(db) as connection:
        row = connection.execute(
            "SELECT * FROM site_surveys WHERE session_id = ? AND status = 'pending' ORDER BY survey_id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        if row is None:
            return _error("there is no pending site survey to confirm")
        connection.execute(
            "UPDATE site_surveys SET status = 'confirmed', confirmed_at = ? WHERE survey_id = ?", (_now(), row["survey_id"])
        )
    return {"survey_id": row["survey_id"], "status": "confirmed", "project_id": row["project_id"], "survey_date": row["survey_date"]}


# The tools the agent may call. confirm_pending_survey is deliberately not here.
AGENT_TOOLS = (create_lead, get_project_status, find_product, book_site_survey)

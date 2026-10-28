"""Data checks for the knowledge base in data/kb.

These tests read the Markdown files directly, without the app's own loader,
so a broken document is caught even if the loader has a bug.
"""

import datetime
import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
KB_DIR = ROOT / "data" / "kb"
DOC_PATHS = sorted(KB_DIR.glob("*.md"))

MIN_DOCUMENTS = 20
REQUIRED_FIELDS = {"id", "title", "category", "tags", "last_reviewed"}
CATEGORIES = {
    "company",
    "services",
    "process",
    "pricing",
    "products",
    "corrosion",
    "loads",
    "foundations",
    "warranty",
}
KEBAB_CASE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

# English text plus the three unit symbols the knowledge base uses.
ALLOWED_NON_ASCII = {"µ", "²", "°"}

# A number glued to its unit, like "350kW" or "2.4kN/m²". The standard form has a space.
UNIT_WITHOUT_SPACE = re.compile(r"\d(?:kWp|MWp|kWh|kW|MW|µm|mm|m/s|kN/m²|kg/m²|m²|m)(?![A-Za-z])")
# Spellings that differ from the standard form: wrong case, "m2" instead of "m²",
# "um" or Greek "μ" instead of "µ", spelled-out units.
NON_STANDARD_UNIT = re.compile(
    r"\b(?:kw|KW|Kw|kwp|KWP|KWp|Kwp|mw|Mw|mwp|MWP|Mwp|kN/m2|kg/m2|m2|um|μm|microns?|m/sec|mps)\b"
)
# The standard form has no space before a degree or percent sign.
SPACE_BEFORE_SIGN = re.compile(r"\d\s+[°%]")

EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)")
# International format, like "+44 20 7946 0000". The leading "+" keeps dates
# such as 2026-10-28 and standard names such as EN 1991-1-4 from matching.
PHONE = re.compile(r"\+\d[\d ()-]{7,}\d")


def split_front_matter(path):
    """Return (front_matter, body). Raise AssertionError if the front matter is malformed."""
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines and lines[0] == "---", "file must start with '---' on the first line"
    assert "---" in lines[1:], "front matter is not closed with '---'"
    end = lines.index("---", 1)
    front_matter = yaml.safe_load("\n".join(lines[1:end]))
    assert isinstance(front_matter, dict), "front matter must be a YAML mapping"
    return front_matter, "\n".join(lines[end + 1 :])


def by_name(path):
    return path.name


def test_knowledge_base_has_enough_documents():
    assert len(DOC_PATHS) >= MIN_DOCUMENTS


@pytest.mark.parametrize("path", DOC_PATHS, ids=by_name)
def test_front_matter_has_exactly_the_required_fields(path):
    front_matter, _ = split_front_matter(path)
    assert set(front_matter) == REQUIRED_FIELDS


@pytest.mark.parametrize("path", DOC_PATHS, ids=by_name)
def test_id_matches_file_name(path):
    front_matter, _ = split_front_matter(path)
    assert front_matter["id"] == path.stem


@pytest.mark.parametrize("path", DOC_PATHS, ids=by_name)
def test_category_is_known(path):
    front_matter, _ = split_front_matter(path)
    assert front_matter["category"] in CATEGORIES


@pytest.mark.parametrize("path", DOC_PATHS, ids=by_name)
def test_tags_are_a_non_empty_list_in_kebab_case(path):
    front_matter, _ = split_front_matter(path)
    tags = front_matter["tags"]
    assert isinstance(tags, list) and tags
    bad = [tag for tag in tags if not (isinstance(tag, str) and KEBAB_CASE.match(tag))]
    assert not bad, f"tags not in kebab-case: {bad}"


@pytest.mark.parametrize("path", DOC_PATHS, ids=by_name)
def test_last_reviewed_is_a_date_not_in_the_future(path):
    front_matter, _ = split_front_matter(path)
    reviewed = front_matter["last_reviewed"]
    # YAML turns an unquoted 2026-10-28 into a date; anything else is a typo.
    assert isinstance(reviewed, datetime.date), f"not a YYYY-MM-DD date: {reviewed!r}"
    assert reviewed <= datetime.date.today()


@pytest.mark.parametrize("path", DOC_PATHS, ids=by_name)
def test_first_heading_matches_title(path):
    front_matter, body = split_front_matter(path)
    first_line = next((line for line in body.splitlines() if line.strip()), "")
    assert first_line == f"# {front_matter['title']}"


@pytest.mark.parametrize("path", DOC_PATHS, ids=by_name)
def test_text_is_english_with_standard_symbols(path):
    text = path.read_text(encoding="utf-8")
    bad = sorted({ch for ch in text if ord(ch) > 127 and ch not in ALLOWED_NON_ASCII})
    assert not bad, f"unexpected characters: {[f'{ch} (U+{ord(ch):04X})' for ch in bad]}"


@pytest.mark.parametrize("path", DOC_PATHS, ids=by_name)
def test_units_are_written_in_standard_form(path):
    text = path.read_text(encoding="utf-8")
    problems = (
        UNIT_WITHOUT_SPACE.findall(text)
        + NON_STANDARD_UNIT.findall(text)
        + SPACE_BEFORE_SIGN.findall(text)
    )
    assert not problems, f"non-standard units: {problems}"


@pytest.mark.parametrize("path", DOC_PATHS, ids=by_name)
def test_contains_no_real_contact_data(path):
    text = path.read_text(encoding="utf-8")
    real_domains = [domain for domain in EMAIL.findall(text) if domain != "example.com"]
    assert not real_domains, f"emails must use example.com, found: {real_domains}"
    assert not PHONE.findall(text), "phone numbers are not allowed in the knowledge base"

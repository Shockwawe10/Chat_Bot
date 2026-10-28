"""Data checks for GLOSSARY.md: every term is a `###` heading followed by its definition."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GLOSSARY = ROOT / "GLOSSARY.md"

MIN_TERMS = 15


def read_terms():
    """Return {term: definition} from the glossary."""
    terms = {}
    duplicates = []
    current = None
    for line in GLOSSARY.read_text(encoding="utf-8").splitlines():
        if line.startswith("### "):
            current = line[4:].strip()
            if current in terms:
                duplicates.append(current)
            terms[current] = ""
        elif line.startswith("#"):
            current = None
        elif current is not None:
            terms[current] = (terms[current] + " " + line.strip()).strip()
    assert not duplicates, f"duplicate terms: {duplicates}"
    return terms


def test_glossary_has_enough_terms():
    assert len(read_terms()) >= MIN_TERMS


def test_every_term_has_a_definition():
    empty = [term for term, definition in read_terms().items() if not definition]
    assert not empty, f"terms without a definition: {empty}"

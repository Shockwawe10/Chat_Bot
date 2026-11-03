"""Plain-code checks of an answer against a golden case: no LLM.

`contains_fact` is the numeric fidelity rule from the README. Matching ignores case,
spaces and thousands separators, and it respects number boundaries: "5 years" is
not found inside "15 years", and "0.6 m" is not found inside "10.6 m" or "0.6 mm".
"""

import re

GREEK_MU, MICRO_SIGN = chr(0x3BC), chr(0xB5)  # they look the same, so they are spelled out
SPACES = re.compile(r"[\s  ]+")
THOUSANDS = re.compile(r"(?<=\d)[, ](?=\d{3}(?!\d))")
RANGE = re.compile(r"(?<=\d) ?(?:to|–|—|-) ?(?=\d)")
DEGREES = re.compile(r"(?<=\d) ?degrees?\b")
SQUARE = re.compile(r"(?<=m)2(?!\d)")
# "1.5 to 2.5 m" means 1.5 m too, so the unit after a range is copied to its start.
BARE_RANGE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?) to (\d+(?:\.\d+)?) ?([a-zµ°²/%]+)")
# Where a number meets its unit. Spaces are not removed from the text, because that
# also joins words: "a4 fasteners" became "a4fasteners" and lost the whole value A4.
UNIT_EDGE = re.compile(r"(?<=\d) ?(?=[^\d\s.,])")


def normalise(text):
    text = SPACES.sub(" ", text.lower()).strip()
    text = text.replace(GREEK_MU, MICRO_SIGN)  # models sometimes write the Greek letter
    text = DEGREES.sub("°", text)
    text = SQUARE.sub("²", text)
    text = THOUSANDS.sub("", text)
    text = RANGE.sub(" to ", text)
    return BARE_RANGE.sub(r"\1 \3 to \2 \3", text)


def contains_fact(text, fact):
    """True if `fact` appears in `text` as a whole value, not as part of a longer one."""
    wanted = normalise(fact)
    if not wanted:
        raise ValueError("empty fact")
    before = r"(?<![a-z0-9.,])" if wanted[0].isalnum() else ""
    after = r"(?![a-z0-9])" if wanted[-1].isalnum() else ""
    # "350 kW" and "350kW" are the same value, so the space after a number is optional.
    body = r"\s?".join(re.escape(part) for part in UNIT_EDGE.split(wanted))
    return re.search(before + body + after, normalise(text)) is not None


def missing_facts(text, facts):
    return [fact for fact in facts if not contains_fact(text, fact)]

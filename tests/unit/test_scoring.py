"""Numeric fidelity: equal values match in any common form, near values never do."""

import pytest

from app.generator import ABSTAIN_SENTENCE
from evals.scoring import contains_fact, missing_facts, normalise
from evals.validate_golden import load_dataset


@pytest.mark.parametrize(
    ("text", "fact"),
    [
        ("The inverter is 350 kW.", "350 kW"),
        ("The inverter is 350kW.", "350 kW"),
        ("The inverter is 350 KW.", "350 kW"),
        ("About 1,000 m² of storage.", "1,000 m²"),
        ("About 1000 m2 of storage.", "1,000 m²"),
        ("About 1 000 m² of storage.", "1,000 m²"),
        ("It takes 3–6 weeks.", "3 to 6 weeks"),
        ("It takes 3-6 weeks.", "3 to 6 weeks"),
        ("It takes 3 to 6 weeks.", "3 to 6 weeks"),
        ("Posts go 1.5 to 2.5 m deep.", "1.5 m"),
        ("Posts go 1.5 to 2.5 m deep.", "2.5 m"),
        ("The coating is 85 μm.", "85 µm"),
        ("The roof slope may be 10 to 60 degrees.", "10° to 60°"),
        ("It is rated C5.", "C5"),
        ("Fasteners: stainless steel A4.", "A4"),
        ("GF-2's coating is thinner.", "GF-2"),
        ("The installation warranty is 5 years, not 15.", "5 years"),
        ("Snow load up to 2.4 kN/m².", "2.4 kN/m²"),
    ],
)
def test_same_value_in_another_form_matches(text, fact):
    assert contains_fact(text, fact)


@pytest.mark.parametrize(
    ("text", "fact"),
    [
        ("The warranty is 15 years.", "5 years"),
        ("RF-1 fits, at 15°.", "5°"),
        ("Clearance is at least 10.6 m.", "0.6 m"),
        ("Clearance is 0.6 mm.", "0.6 m"),
        ("The maximum is 12.4 kN/m².", "2.4 kN/m²"),
        ("Expect a reply within 15 working days.", "5 working days"),
        ("Use GF-25.", "GF-2"),
        ("It is rated C50.", "C5"),
        ("It takes 3 to 16 weeks.", "3 to 6 weeks"),
        ("Offers are valid for 130 days.", "30 days"),
    ],
)
def test_near_value_does_not_match(text, fact):
    assert not contains_fact(text, fact)


def test_fixed_refusal_satisfies_no_fact_in_the_dataset():
    facts = {fact for case in load_dataset() for fact in case["must_include"]}
    assert facts
    assert [fact for fact in facts if contains_fact(ABSTAIN_SENTENCE, fact)] == []


def test_missing_facts_lists_only_what_is_absent():
    assert missing_facts("Product 15 years, installation 5 years.", ["15 years", "5 years", "2031"]) == ["2031"]


def test_only_15_years_does_not_pass_both_warranty_facts():
    assert missing_facts("The warranty is 15 years.", ["15 years", "5 years"]) == ["5 years"]


def test_empty_fact_is_an_error():
    with pytest.raises(ValueError):
        contains_fact("text", "  ")


def test_normalise_is_stable():
    once = normalise("Posts go 1.5 to 2.5 m deep, 1,000 m2.")
    assert normalise(once) == once

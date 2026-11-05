"""The English-only check (app/language.py): positive evidence of another language, or English."""

import json

import pytest

from app.language import ENGLISH, ENGLISH_ONLY, OTHER, is_english
from app.settings import ROOT
from evals.metrics import language_reply
from evals.validate_golden import load_dataset


@pytest.mark.parametrize(
    "question",
    [
        "Wie lange gilt die Garantie für das Gestell?",
        "Quelle est la charge de neige maximale pour le système?",
        "¿Cuánto cuesta una estructura para un tejado plano?",
        "Qual è il carico di vento massimo per il sistema?",
        "Hoe lang is de garantie en wat kost het?",
        "Jak długo trwa gwarancja i ile kosztuje montaż?",
        "Какая гарантия на конструкцию?",
        "Яка гарантія на монтаж?",
        "保修期多长？",
        "Garantiezeit für Gestelle über Dächern?",
    ],
)
def test_other_languages_are_spotted(question):
    assert not is_english(question)


@pytest.mark.parametrize(
    "question",
    [
        "How long is the product warranty?",
        "Warranty?",
        "Garantie für GF-2?",
        "GF-2 snow load per m²?",
        "Do you install in Düsseldorf or Łódź?",
        "Can you build a 50 kWp system on our office roof?",
        "No guarantee on the coating, is that right?",
        "What's the max wind speed for RF-1 at 32 m/s?",
        "",
        "12345",
    ],
)
def test_english_and_short_questions_are_never_refused_for_their_language(question):
    assert is_english(question)


def test_the_two_word_lists_never_share_a_word():
    assert not ENGLISH & OTHER


def test_none_of_the_generated_customer_questions_is_flagged():
    data = json.loads((ROOT / "data" / "chunk_questions.json").read_text(encoding="utf-8"))
    questions = [q for entry in data["chunks"].values() for q in entry["questions"]]
    assert len(questions) == 455
    assert [q for q in questions if not is_english(q)] == []


def test_dev_questions_are_decided_as_the_dataset_says():
    dev = [case for case in load_dataset() if case["split"] == "dev"]
    wrong = [c["id"] for c in dev if is_english(c["question"]) == (c["category"] == "unsupported language")]
    assert wrong == []


def test_the_reply_passes_the_harness_language_rule():
    assert language_reply(ENGLISH_ONLY)

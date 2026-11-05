"""English-only reply: spot a question in another language before retrieval and generation.

The chatbot answers in English only (README, Language). A question in another language
gets ENGLISH_ONLY instead of an answer. The check needs positive evidence, so a short
or unusual English question is never refused for its language:
- most of its letters are outside a-z (Cyrillic, Greek, CJK, ...), or
- it uses more function words of a common European language than English ones, and
  at least two of them. A word with a non-English letter (é, ü, ñ) counts too.
Plain code, no model: the same question always gets the same decision.
"""

import re

ENGLISH_ONLY = "I can only answer questions in English. Please ask your question in English."
MOSTLY_OTHER_SCRIPT = 0.3  # share of letters outside a-z that marks another script
WORD = re.compile(r"[^\W\d_]+")
ENGLISH = frozenset({
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "do", "does", "did", "can", "could",
    "will", "would", "should", "may", "might", "must", "have", "has", "had", "i", "you", "we", "they",
    "he", "she", "it", "my", "your", "our", "their", "this", "that", "these", "those", "what", "which",
    "who", "how", "when", "where", "why", "if", "or", "and", "but", "not", "of", "to", "in", "on", "at",
    "for", "with", "from", "by", "about", "as", "than", "there",
})
# Common words of other languages that are not also everyday English words
# (so no "per", "no", "die", "was", "will", "is", "do", "as").
OTHER = frozenset({
    # German
    "der", "das", "und", "ist", "wie", "wann", "warum", "wo", "ich", "nicht", "ein", "eine", "einen",
    "mit", "für", "auf", "sie", "wir", "ihr", "gilt", "lange", "kann", "können", "gibt", "bitte",
    "welche", "welcher",
    # French
    "le", "la", "les", "est", "et", "pour", "que", "qui", "une", "des", "du", "je", "vous", "combien",
    "quel", "quelle", "avec", "dans",
    # Spanish
    "el", "los", "las", "es", "y", "por", "qué", "cuánto", "cuánta", "cuesta", "un", "una", "para",
    "con", "cómo", "dónde", "puedo",
    # Italian
    "il", "gli", "che", "quanto", "quale", "sono", "della",
    # Portuguese
    "os", "não", "um", "uma", "quanta", "qual",
    # Dutch
    "het", "een", "en", "wat", "hoe", "niet", "voor", "kan",
    # Polish
    "jest", "nie", "jak", "ile", "czy",
})


def is_english(question):
    letters = [char for char in question if char.isalpha()]
    if not letters:
        return True
    if sum(not ("a" <= char.lower() <= "z") for char in letters) / len(letters) > MOSTLY_OTHER_SCRIPT:
        return False
    words = WORD.findall(question.lower())
    english = sum(word in ENGLISH for word in words)
    other = sum(word in OTHER or not word.isascii() for word in words)
    return not (other >= 2 and other > english)

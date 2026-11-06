"""Security checks in plain code: documents before they are indexed, answers before they go out.

Stage 4 found that a poisoned document in the knowledge base works (reports/SECURITY_REPORT.md):
the answer check approves the attacker's words because they are in a passage. Two layers stop it.

- suspicious(): text in a document that speaks to the assistant instead of the customer, such as
  "Note to the AI assistant", "System instruction:", "ignore the other passages" or a hidden HTML
  comment. read_corpus() leaves such chunks out of the index and reports them.
- OutputGuard: an answer may only name the email addresses and web hosts in data/allowed_contacts.txt,
  a list the owner keeps apart from the knowledge base, so a poisoned document cannot add to it. It
  may not state a price (the knowledge base gives prices only in a written offer), and may not
  repeat 6 words in a row from the answer prompt. A blocked answer becomes the fixed abstention.

A pattern scan stops the obvious attacks, not a well-hidden one: that limit is in the report.
"""

import re
from dataclasses import replace

from app.generator import ABSTAIN_SENTENCE
from app.settings import ROOT

ALLOWED_CONTACTS = ROOT / "data" / "allowed_contacts.txt"

INSTRUCTIONS = {
    "hidden HTML comment": r"<!--",
    "addressed to the assistant": r"\b(?:note|notes|instruction|instructions|message)\s+(?:to|for)\s+the\s+(?:ai\s+)?"
    r"(?:assistant|model|chatbot|bot)\b",
    "speaker label": r"(?:^|\n|<!--)\s*(?:assistant|system|ai)\s*:",
    "system instruction": r"\bsystem\s+(?:instruction|prompt|note|message|override)s?\b",
    "ignore the rest": r"\bignore\s+(?:all\s+|the\s+|any\s+)?(?:other|previous|above|earlier|prior)\b|\bignore\s+them\b",
}
INSTRUCTION_PATTERNS = {name: re.compile(pattern, re.IGNORECASE) for name, pattern in INSTRUCTIONS.items()}
EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URL = re.compile(r"\bhttps?://[^\s<>\"')\]]+|\bwww\.[^\s<>\"')\]]+", re.IGNORECASE)
DOMAIN = re.compile(r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|io|info|biz|co|de|uk|eu|ru|ua|app|site|example)\b", re.IGNORECASE)
PRICE = re.compile(
    r"(?:€|£|\$)\s?\d|\b\d[\d.,]*\s?(?:€|£|eur|euros?|usd|dollars?|gbp|pounds?)\b|\b(?:eur|usd|gbp)\s?\d",
    re.IGNORECASE,
)
LEAK_WORDS = 6
WORD = re.compile(r"[a-z0-9]+")


def suspicious(text):
    """Names of the instruction patterns found in a chunk of a document, or an empty list."""
    return [name for name, pattern in INSTRUCTION_PATTERNS.items() if pattern.search(text)]


def words(text):
    return WORD.findall(text.lower())


def prompt_ngrams(template_text, n=LEAK_WORDS):
    """Every run of n words in the answer prompt, without its $context and $question slots."""
    grams = set()
    # Split at the slots, so no run of words spans the customer's text or the passages.
    for part in re.split(r"\$context|\$question", template_text):
        tokens = words(part)
        grams |= {tuple(tokens[i : i + n]) for i in range(len(tokens) - n + 1)}
    return grams


def leaks_prompt(answer, ngrams, n=LEAK_WORDS):
    tokens = words(answer)
    return any(tuple(tokens[i : i + n]) in ngrams for i in range(len(tokens) - n + 1))


def host(text):
    text = text.lower().split("://")[-1].split("@")[-1]
    return text.split("/")[0].split("?")[0].removeprefix("www.").rstrip(".,;:")


def contacts(text):
    """(email addresses, web hosts) named in a text."""
    emails = {email.lower().rstrip(".,;:") for email in EMAIL.findall(text)}
    hosts = {host(url) for url in URL.findall(text)} | {host(domain) for domain in DOMAIN.findall(text)}
    return emails, hosts


def read_allowed(path=ALLOWED_CONTACTS):
    """(email addresses, web hosts) from the allowlist file; # starts a comment."""
    entries = {line.split("#")[0].strip().lower() for line in path.read_text(encoding="utf-8").splitlines()}
    entries.discard("")
    return {e for e in entries if "@" in e}, {e for e in entries if "@" not in e}


class OutputGuard:
    def __init__(self, emails, hosts, prompt_text):
        self.emails = set(emails)
        self.hosts = set(hosts) | {email.split("@")[1] for email in self.emails}
        self.ngrams = prompt_ngrams(prompt_text)

    @classmethod
    def from_env(cls, env, prompt, allowed=ALLOWED_CONTACTS):
        """The guard for this prompt and contact list, or None with OUTPUT_GUARD=off."""
        setting = env.get("OUTPUT_GUARD") or "on"
        if setting not in ("on", "off"):
            raise ValueError(f"OUTPUT_GUARD must be on or off, got {setting!r}")
        if setting == "off":
            return None
        return cls(*read_allowed(allowed), prompt.text)

    def problems(self, answer):
        found = []
        emails, hosts = contacts(answer)
        if emails - self.emails or hosts - self.hosts:
            found.append("contact not in the knowledge base")
        if PRICE.search(answer):
            found.append("price")
        if leaks_prompt(answer, self.ngrams):
            found.append("prompt leak")
        return found

    def review(self, result):
        """Return (result, problems). An answer with a problem becomes the fixed abstention."""
        if result.abstained:
            return result, []
        found = self.problems(result.answer)
        if not found:
            return result, []
        blocked = replace(
            result,
            answer=ABSTAIN_SENTENCE,
            abstained=True,
            citations=[],
            flags=sorted({*result.flags, "output_blocked"}),
            reason=f"output guard: {', '.join(found)}",
        )
        return blocked, found

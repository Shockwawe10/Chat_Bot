"""Answer check: every sentence of an answer must be supported by the retrieved passages.

Off by default. With ANSWER_CHECK=minicheck, Bespoke-MiniCheck reads each sentence
against all the retrieved passages, and one unsupported sentence turns the answer
into the fixed abstention. It runs after generation, so it can only take an answer
away, never add one. The eval judge splits sentences with the same code.
"""

import re
from dataclasses import replace

import httpx

from app.embedder import DEFAULT_URL, EmbeddingError, check_pinned
from app.generator import ABSTAIN_SENTENCE

METHODS = ("off", "minicheck")
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
ABBREVIATIONS = ("ltd.", "e.g.", "i.e.", "etc.", "approx.", "no.")


class CheckUnavailable(RuntimeError):
    pass


def sentences(text):
    """Split an answer into sentences with plain code, keeping "Ltd." and "e.g." inside one."""
    parts, current = [], ""
    for piece in SENTENCE_END.split(" ".join(text.split())):
        current = f"{current} {piece}" if current else piece
        if not current.lower().endswith(ABBREVIATIONS):
            parts.append(current)
            current = ""
    if current:
        parts.append(current)
    return [part for part in parts if part.strip()]


def document(hits):
    """Heading, then text, for every retrieved passage: what the eval judge reads too."""
    return "\n\n".join(f"{hit.heading_path}\n{hit.text}" if hit.heading_path else hit.text for hit in hits)


class MiniCheck:
    def __init__(self, model, digest, base_url=DEFAULT_URL, client=None):
        if not model or not digest:
            raise CheckUnavailable("ANSWER_CHECK_MODEL and ANSWER_CHECK_DIGEST must be set")
        self.model = model
        self.digest = digest
        self.client = client or httpx.Client(base_url=base_url, timeout=180)

    @classmethod
    def from_env(cls, env):
        """The configured check, or None when it is off."""
        method = env.get("ANSWER_CHECK") or "off"
        if method not in METHODS:
            raise CheckUnavailable(f"ANSWER_CHECK must be one of {METHODS}, got {method!r}")
        if method == "off":
            return None
        return cls(
            env.get("ANSWER_CHECK_MODEL") or "",
            env.get("ANSWER_CHECK_DIGEST") or "",
            env.get("OLLAMA_URL") or DEFAULT_URL,
        )

    def check_pinned(self):
        try:
            check_pinned(self.client, self.model, self.digest)
        except EmbeddingError as error:
            raise CheckUnavailable(str(error)) from error

    def verdict(self, sentence, passages):
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": "user", "content": f"Document: {passages}\nClaim: {sentence}"}],
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 4},
        }
        response = self.client.post("/api/chat", json=payload)
        if response.status_code != 200:
            raise CheckUnavailable(f"Ollama returned {response.status_code}: {response.text}")
        reply = response.json()["message"]["content"].strip()
        # Anything but a clear Yes counts as unsupported: the check fails closed.
        supported = reply.split()[0].strip(".").lower() == "yes" if reply else False
        return {"sentence": sentence, "supported": supported, "reply": reply}

    def review(self, result, hits):
        """Return (result, verdicts). One unsupported sentence turns the answer into the abstention."""
        if result.abstained:
            return result, []
        passages = document(hits)
        verdicts = [self.verdict(sentence, passages) for sentence in sentences(result.answer)]
        if verdicts and all(item["supported"] for item in verdicts):
            return result, verdicts
        blocked = replace(
            result,
            answer=ABSTAIN_SENTENCE,
            abstained=True,
            citations=[],
            flags=sorted({*result.flags, "answer_check_failed"}),
            reason="the answer check found a sentence the passages do not support",
        )
        return blocked, verdicts

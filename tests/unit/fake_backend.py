"""A stand-in for Ollama that records its inputs, so tests run without a model."""

import hashlib

import numpy as np

from app.embedder import DOCUMENT_PREFIX, QUERY_PREFIX

DIM = 64


def fake_vector(text):
    """The same text gives the same unit vector, with or without its prefix."""
    plain = text.removeprefix(DOCUMENT_PREFIX).removeprefix(QUERY_PREFIX)
    seed = int(hashlib.sha256(plain.encode()).hexdigest()[:16], 16)
    vector = np.random.default_rng(seed).normal(size=DIM)
    return (vector / np.linalg.norm(vector)).tolist()


class FakeBackend:
    def __init__(self, context=2048, model="fake:1", digest="fake-digest"):
        self.context = context
        self.model = model
        self.digest = digest
        self.inputs = []
        self.batches = []
        self.pin_checks = 0

    def check_pinned(self):
        self.pin_checks += 1

    def context_length(self):
        return self.context

    def embed(self, texts):
        self.inputs.extend(texts)
        self.batches.append(list(texts))
        return [fake_vector(text) for text in texts]

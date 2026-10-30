"""Stand-ins for Ollama that record their inputs, so tests run without a model."""

import hashlib
import json
import re

import numpy as np

from app.embedder import DOCUMENT_PREFIX, QUERY_PREFIX
from app.generator import Completion, LlmConfig

DIM = 64
TOPICAL_DIM = 512
VALID_OUTPUT = json.dumps({"answer": "The answer.", "citations": [1], "abstained": False})


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


class TopicalBackend(FakeBackend):
    """Texts that share words get similar vectors, so a question can find its topic."""

    def embed(self, texts):
        self.inputs.extend(texts)
        self.batches.append(list(texts))
        return [self._vector(text) for text in texts]

    @staticmethod
    def _vector(text):
        plain = text.removeprefix(DOCUMENT_PREFIX).removeprefix(QUERY_PREFIX)
        vector = np.zeros(TOPICAL_DIM)
        for word in re.findall(r"[a-z0-9-]+", plain.lower()):
            vector[int(hashlib.sha256(word.encode()).hexdigest()[:8], 16) % TOPICAL_DIM] += 1
        return (vector / np.linalg.norm(vector)).tolist()


class FakeLlm:
    """Returns scripted outputs in order, and repeats the last one."""

    def __init__(self, outputs=(VALID_OUTPUT,), prompt_eval_count=None, error=None):
        self.cfg = LlmConfig("fake-llm:1", "fake-llm-digest")
        self.outputs = list(outputs)
        self.prompt_eval_count = prompt_eval_count
        self.error = error
        self.calls = []

    def check_pinned(self):
        pass

    def complete(self, prompt, temperature, seed):
        if self.error:
            raise self.error
        self.calls.append({"prompt": prompt, "temperature": temperature, "seed": seed})
        count = self.prompt_eval_count
        count = len(prompt.split()) + 20 if count is None else count
        text = self.outputs[min(len(self.calls) - 1, len(self.outputs) - 1)]
        return Completion(text, count, "stop")

"""Generation v1 (baseline): one answer from the retrieved chunks, as structured JSON.

The model cites passages by number and never sees chunk ids, so it cannot invent
one. Everything it returns is checked here, and problems become flags on the answer.
"""

import hashlib
import json
from dataclasses import dataclass, field
from string import Template

import httpx

from app.embedder import DEFAULT_URL, EmbeddingError, check_pinned
from app.settings import ROOT, read_env

PROMPTS_DIR = ROOT / "prompts"
ABSTAIN_SENTENCE = "I can't answer that from the available documents."
# At temperature 0 the same prompt gives the same output, even with a new seed,
# so a retry only has a chance of a different result at a small temperature.
RETRY_TEMPERATURE = 0.2

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "answer": {"type": "string"},
        "citations": {"type": "array", "items": {"type": "integer"}},
        "abstained": {"type": "boolean"},
    },
    "required": ["answer", "citations", "abstained"],
}


class LlmUnavailable(RuntimeError):
    pass


class MalformedOutput(ValueError):
    pass


class GenerationError(RuntimeError):
    """The model output could not be parsed, even after the retry."""

    def __init__(self, message, raw_outputs):
        super().__init__(message)
        self.raw_outputs = raw_outputs


@dataclass(frozen=True)
class LlmConfig:
    model: str
    digest: str
    temperature: float = 0.0
    seed: int = 42
    num_ctx: int = 4096
    num_predict: int = 512

    def __post_init__(self):
        if ":" not in self.model or self.model.endswith(":latest"):
            raise LlmUnavailable(f"LLM model needs an exact tag, got {self.model!r}")
        if not self.digest:
            raise LlmUnavailable("LLM_DIGEST is not set")
        if self.num_predict >= self.num_ctx:
            raise LlmUnavailable("LLM_NUM_PREDICT must be below LLM_NUM_CTX")

    @classmethod
    def from_env(cls, env=None):
        env = read_env() if env is None else env
        defaults = {"temperature": 0.0, "seed": 42, "num_ctx": 4096, "num_predict": 512}
        return cls(
            model=env.get("LLM_MODEL") or "",
            digest=env.get("LLM_DIGEST") or "",
            temperature=float(env.get("TEMPERATURE") or defaults["temperature"]),
            seed=int(env.get("LLM_SEED") or defaults["seed"]),
            num_ctx=int(env.get("LLM_NUM_CTX") or defaults["num_ctx"]),
            num_predict=int(env.get("LLM_NUM_PREDICT") or defaults["num_predict"]),
        )


@dataclass(frozen=True)
class Completion:
    text: str
    prompt_eval_count: int | None
    done_reason: str | None


@dataclass(frozen=True)
class Answer:
    answer: str
    abstained: bool
    citations: list  # passage numbers, 1-based, valid and without duplicates
    flags: list = field(default_factory=list)
    raw_outputs: list = field(default_factory=list)


@dataclass(frozen=True)
class PromptTemplate:
    version: str
    text: str

    @classmethod
    def load(cls, version):
        path = PROMPTS_DIR / f"answer_{version}.txt"
        return cls(version, path.read_bytes().decode("utf-8").replace("\r\n", "\n"))

    @property
    def sha256(self):
        return hashlib.sha256(self.text.encode()).hexdigest()

    def render(self, hits, question):
        passages = [f"[{hit.rank}] {hit.heading_path}\n{hit.text}" for hit in hits]
        return Template(self.text).substitute(context="\n\n".join(passages), question=question)


class OllamaLlm:
    def __init__(self, cfg, base_url=DEFAULT_URL, client=None):
        self.cfg = cfg
        self.client = client or httpx.Client(base_url=base_url, timeout=180)

    @classmethod
    def from_env(cls, env=None):
        env = read_env() if env is None else env
        return cls(LlmConfig.from_env(env), env.get("OLLAMA_URL") or DEFAULT_URL)

    def check_pinned(self):
        try:
            check_pinned(self.client, self.cfg.model, self.cfg.digest)
        except EmbeddingError as error:
            raise LlmUnavailable(str(error)) from error

    def complete(self, prompt, temperature, seed):
        payload = {
            "model": self.cfg.model,
            "stream": False,
            "think": False,
            "format": OUTPUT_SCHEMA,
            "messages": [{"role": "user", "content": prompt}],
            "options": {
                "temperature": temperature,
                "seed": seed,
                "num_ctx": self.cfg.num_ctx,
                "num_predict": self.cfg.num_predict,
            },
        }
        response = self.client.post("/api/chat", json=payload)
        if response.status_code != 200:
            raise LlmUnavailable(f"Ollama returned {response.status_code}: {response.text}")
        data = response.json()
        return Completion(
            data["message"]["content"], data.get("prompt_eval_count"), data.get("done_reason")
        )


def parse_output(text, passage_count):
    """Turn model output into an Answer, or raise MalformedOutput."""
    try:
        data = json.loads(text)
    except ValueError as error:
        raise MalformedOutput(f"not JSON: {error}") from error
    if not isinstance(data, dict):
        raise MalformedOutput("not a JSON object")
    answer, numbers, abstained = data.get("answer"), data.get("citations"), data.get("abstained")
    if not isinstance(answer, str) or not isinstance(numbers, list) or not isinstance(abstained, bool):
        raise MalformedOutput("a field is missing or has the wrong type")

    flags = []
    if abstained:
        if numbers:
            flags.append("abstained_with_citations")
        return Answer(ABSTAIN_SENTENCE, True, [], flags)
    if not answer.strip():
        raise MalformedOutput("empty answer")

    citations = []
    for number in numbers:
        if type(number) is not int or not 1 <= number <= passage_count:
            flags.append("citation_out_of_range")
        elif number in citations:
            flags.append("citation_duplicate")
        else:
            citations.append(number)
    if not citations:
        flags.append("no_citations")
    return Answer(answer.strip(), False, citations, sorted(set(flags)))


def prompt_flags(completion, prompt, num_ctx):
    """Check the prompt reached the model whole.

    Ollama has no tokenizer endpoint, so an exact count is not possible. Every
    whitespace-separated word is at least one token, so fewer tokens than words
    means text was lost, and a count at num_ctx means there was no room left.
    """
    count = completion.prompt_eval_count
    if count is None or count < len(prompt.split()) or count >= num_ctx:
        return ["prompt_truncated"]
    return []


def generate(llm, prompt, passage_count):
    """Ask once, and once more if the output cannot be parsed."""
    cfg = llm.cfg
    attempts = [(cfg.temperature, cfg.seed), (RETRY_TEMPERATURE, cfg.seed + 1)]
    raw_outputs = []
    for attempt, (temperature, seed) in enumerate(attempts):
        completion = llm.complete(prompt, temperature, seed)
        raw_outputs.append(completion.text)
        try:
            parsed = parse_output(completion.text, passage_count)
        except MalformedOutput:
            continue
        flags = parsed.flags + prompt_flags(completion, prompt, cfg.num_ctx)
        if attempt:
            flags.append("retried")
        return Answer(parsed.answer, parsed.abstained, parsed.citations, sorted(flags), raw_outputs)
    raise GenerationError("model output could not be parsed after a retry", raw_outputs)

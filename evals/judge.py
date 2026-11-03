"""LLM-judged answer metrics: faithfulness, answer relevancy, context precision, context recall.

The judge is JUDGE_PROVIDER / JUDGE_MODEL and must differ from the model that answers.
JUDGE_METHOD picks how faithfulness is judged: "claim-check" (one schema-constrained
yes/no per sentence) or "ragas". The other three metrics always come from Ragas.
Scores are stored in every run, but the README shows a judged metric only after the same
model and method have passed calibration for it (reports/judge_calibration.json).

Which cases get which metric:
- faithfulness, answer_relevancy: answered cases (status 200, not refused, not a language case)
- context_precision, context_recall: cases with gold spans, scored against expected_answer

Every judge sees each chunk as the answering model did: its heading, then its text.
"""

import asyncio
import json
import re
from string import Template

import httpx

from app.embedder import DEFAULT_URL
from app.settings import ROOT

JUDGED = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")
METHODS = ("claim-check", "ragas", "guardian", "minicheck")
CLAIM_PROMPT = ROOT / "prompts" / "judge_claim_v1.txt"
CLAIM_SCHEMA = {
    "type": "object",
    "properties": {"reason": {"type": "string"}, "supported": {"type": "boolean"}},
    "required": ["reason", "supported"],
    "additionalProperties": False,
}
SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])")
ABBREVIATIONS = ("ltd.", "e.g.", "i.e.", "etc.", "approx.", "no.")


class JudgeUnavailable(RuntimeError):
    pass


def needed(scored, case):
    """The judged metrics that apply to one scored case."""
    names = []
    answered = scored.get("status") == 200 and scored.get("refused") is False
    if answered and case["expected_behaviour"] != "language refusal":
        names += ["faithfulness", "answer_relevancy"]
    if case["gold"] and scored.get("retrieved"):
        names += ["context_precision", "context_recall"]
    return names


def metric_inputs(name, case, scored, contexts):
    if name == "faithfulness":
        return {"user_input": case["question"], "response": scored["answer"], "retrieved_contexts": contexts}
    if name == "answer_relevancy":
        return {"user_input": case["question"], "response": scored["answer"]}
    return {"user_input": case["question"], "reference": case["expected_answer"], "retrieved_contexts": contexts}


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


def check_config(env):
    """Return (model, method) or raise JudgeUnavailable."""
    provider, model = env.get("JUDGE_PROVIDER") or "", env.get("JUDGE_MODEL") or ""
    method = env.get("JUDGE_METHOD") or "claim-check"
    if not model:
        raise JudgeUnavailable("JUDGE_MODEL is not set")
    if model == env.get("LLM_MODEL"):
        raise JudgeUnavailable("JUDGE_MODEL must differ from LLM_MODEL, the model that answers")
    if provider != "ollama":
        raise JudgeUnavailable(f"JUDGE_PROVIDER {provider!r} is not set up yet; only ollama is")
    if method not in METHODS:
        raise JudgeUnavailable(f"JUDGE_METHOD must be one of {METHODS}, got {method!r}")
    return model, method


class ClaimCheckJudge:
    """Faithfulness as the share of sentences the judge finds supported, one call per sentence.

    Ragas first asks the judge to rewrite the answer into statements; a small model often
    gets that step wrong. Here plain code splits the sentences, and each call answers one
    narrow question with schema-constrained JSON at temperature 0.
    """

    method = "claim-check"

    def __init__(self, model, ollama_url=DEFAULT_URL, others=None, client=None, seed=42):
        self.model = model
        self.prompt = Template(CLAIM_PROMPT.read_bytes().decode("utf-8").replace("\r\n", "\n"))
        self.client = client or httpx.AsyncClient(base_url=ollama_url, timeout=180)
        self.others = others  # a RagasJudge for the other three metrics
        self.metrics = JUDGED if others else ("faithfulness",)
        self.seed = seed
        self.last_verdicts = []

    async def check(self, question, sentence, contexts):
        prompt = self.prompt.substitute(passages="\n\n".join(contexts), question=question, sentence=sentence)
        payload = {
            "model": self.model,
            "stream": False,
            "format": CLAIM_SCHEMA,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0, "seed": self.seed, "num_ctx": 4096, "num_predict": 256},
        }
        response = await self.client.post("/api/chat", json=payload)
        if response.status_code != 200:
            raise JudgeUnavailable(f"Ollama returned {response.status_code}: {response.text}")
        verdict = json.loads(response.json()["message"]["content"])
        if not isinstance(verdict.get("supported"), bool):
            raise TypeError(f"no supported verdict in {verdict!r}")
        return {"sentence": sentence, "supported": verdict["supported"], "reason": verdict.get("reason", "")}

    async def ascore(self, name, **inputs):
        if name != "faithfulness":
            if self.others is None:
                raise JudgeUnavailable(f"claim-check judges only faithfulness, not {name}")
            return await self.others.ascore(name, **inputs)
        parts = sentences(inputs["response"])
        if not parts:
            raise ValueError("the answer has no sentence to check")
        self.last_verdicts = [
            await self.check(inputs["user_input"], sentence, inputs["retrieved_contexts"]) for sentence in parts
        ]
        return sum(v["supported"] for v in self.last_verdicts) / len(self.last_verdicts)


class GuardianJudge:
    """IBM Granite Guardian's groundedness check on the whole answer: one call, Yes or No.

    Used the way the model was trained: the passages in a "context" message, the answer as
    the assistant message, and "groundedness" as the system prompt, which picks that risk in
    its Ollama template. "Yes" means the answer is not grounded, so it scores 0.0.
    """

    method = "guardian"
    metrics = ("faithfulness",)

    def __init__(self, model, ollama_url=DEFAULT_URL, client=None):
        self.model = model
        self.client = client or httpx.AsyncClient(base_url=ollama_url, timeout=180)
        self.last_verdicts = []

    async def ascore(self, name, **inputs):
        if name != "faithfulness":
            raise JudgeUnavailable(f"guardian judges only faithfulness, not {name}")
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [
                {"role": "system", "content": "groundedness"},
                {"role": "context", "content": "\n\n".join(inputs["retrieved_contexts"])},
                {"role": "assistant", "content": inputs["response"]},
            ],
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 4},
        }
        response = await self.client.post("/api/chat", json=payload)
        if response.status_code != 200:
            raise JudgeUnavailable(f"Ollama returned {response.status_code}: {response.text}")
        reply = response.json()["message"]["content"].strip()
        word = reply.split()[0].strip(".").lower() if reply else ""
        if word not in ("yes", "no"):
            raise ValueError(f"guardian answered {reply!r}, not Yes or No")
        self.last_verdicts = [{"sentence": inputs["response"], "supported": word == "no", "reason": reply}]
        return 1.0 if word == "no" else 0.0


class MiniCheckJudge(ClaimCheckJudge):
    """Bespoke-MiniCheck: a model trained to say whether a document supports one sentence.

    The same per-sentence scoring as claim-check, with the model's own two-line prompt from
    its model card ("Document: ..." then "Claim: ..."). It replies Yes or No.
    """

    method = "minicheck"

    def __init__(self, model, ollama_url=DEFAULT_URL, client=None):
        super().__init__(model, ollama_url, client=client)

    async def check(self, question, sentence, contexts):
        document = "\n\n".join(contexts)
        prompt = f"Document: {document}\nClaim: {sentence}"
        payload = {
            "model": self.model,
            "stream": False,
            "messages": [{"role": "user", "content": prompt}],
            "options": {"temperature": 0, "num_ctx": 8192, "num_predict": 4},
        }
        response = await self.client.post("/api/chat", json=payload)
        if response.status_code != 200:
            raise JudgeUnavailable(f"Ollama returned {response.status_code}: {response.text}")
        reply = response.json()["message"]["content"].strip()
        word = reply.split()[0].strip(".").lower() if reply else ""
        if word not in ("yes", "no"):
            raise ValueError(f"minicheck answered {reply!r}, not Yes or No")
        return {"sentence": sentence, "supported": word == "yes", "reason": reply}


def make_judge(env, ragas_for_others=True):
    model, method = check_config(env)
    url = env.get("OLLAMA_URL") or DEFAULT_URL
    if method == "guardian":
        return GuardianJudge(model, url)
    if method == "minicheck":
        return MiniCheckJudge(model, url)
    embedding = env.get("EMBEDDING_MODEL") or "nomic-embed-text:v1.5"
    ragas = RagasJudge(model, url, embedding) if (method == "ragas" or ragas_for_others) else None
    return ragas if method == "ragas" else ClaimCheckJudge(model, url, others=ragas)


class RagasJudge:
    """Ragas metrics on a local Ollama model, through Ollama's OpenAI-compatible endpoint."""

    method = "ragas"

    def __init__(self, model, ollama_url=DEFAULT_URL, embedding_model="nomic-embed-text:v1.5"):
        # Imported here so the unit tests and the rest of the harness do not load Ragas.
        from openai import AsyncOpenAI
        from ragas.embeddings import embedding_factory
        from ragas.llms import llm_factory
        from ragas.metrics.collections import (
            AnswerRelevancy,
            ContextPrecisionWithReference,
            ContextRecall,
            Faithfulness,
        )

        client = AsyncOpenAI(base_url=f"{ollama_url}/v1", api_key="ollama")
        llm = llm_factory(model, provider="openai", client=client, temperature=0)
        embeddings = embedding_factory("openai", model=embedding_model, client=client)
        self.model = model
        self.metrics = {
            "faithfulness": Faithfulness(llm=llm),
            "answer_relevancy": AnswerRelevancy(llm=llm, embeddings=embeddings),
            "context_precision": ContextPrecisionWithReference(llm=llm),
            "context_recall": ContextRecall(llm=llm),
        }

    async def ascore(self, name, **inputs):
        return float((await self.metrics[name].ascore(**inputs)).value)


def judge_cases(judge, cases, scored, store, passes=1):
    """Add judged scores to each scored case: {"judged": {name: [one value per pass]}}."""

    async def run():
        for item in scored:
            case = cases[item["id"]]
            contexts = [store.context(chunk_id) for chunk_id in item.get("retrieved", [])]
            item["judged"], item["judge_errors"] = {}, []
            for name in [n for n in needed(item, case) if n in getattr(judge, "metrics", JUDGED)]:
                values = []
                for _ in range(passes):
                    try:
                        values.append(await judge.ascore(name, **metric_inputs(name, case, item, contexts)))
                    except Exception as error:  # noqa: BLE001 - a judge failure is recorded, not hidden
                        item["judge_errors"].append(f"{name}: {type(error).__name__}: {str(error)[:200]}")
                        values.append(None)
                item["judged"][name] = values

    asyncio.run(run())


def aggregate_judged(scored, passes):
    """Mean over cases for each pass, then the mean and spread (max - min) of those pass means."""
    metrics = {}
    for name in JUDGED:
        per_pass = []
        for index in range(passes):
            values = [
                item["judged"][name][index]
                for item in scored
                if name in item.get("judged", {}) and item["judged"][name][index] is not None
            ]
            if values:
                per_pass.append(sum(values) / len(values))
        metrics[name] = sum(per_pass) / len(per_pass) if per_pass else None
        metrics[f"{name}_spread"] = max(per_pass) - min(per_pass) if len(per_pass) > 1 else None
        metrics[f"{name}_cases"] = sum(name in item.get("judged", {}) for item in scored)
    metrics["judge_errors"] = sum(len(item.get("judge_errors", [])) for item in scored)
    return metrics

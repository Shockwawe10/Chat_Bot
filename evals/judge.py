"""LLM-judged answer metrics with Ragas: faithfulness, answer relevancy, context precision, context recall.

The judge is JUDGE_PROVIDER / JUDGE_MODEL and must differ from the model that answers.
Its scores are stored in every run, but the README shows them only after the same judge
has passed calibration against human labels (reports/judge_calibration.json).

Which cases get which metric:
- faithfulness, answer_relevancy: answered cases (status 200, not refused, not a language case)
- context_precision, context_recall: cases with gold spans, scored against expected_answer
"""

import asyncio

from app.embedder import DEFAULT_URL

JUDGED = ("faithfulness", "answer_relevancy", "context_precision", "context_recall")


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


class RagasJudge:
    """Ragas metrics on a local Ollama model, through Ollama's OpenAI-compatible endpoint."""

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

    @classmethod
    def from_env(cls, env):
        provider, model = env.get("JUDGE_PROVIDER") or "", env.get("JUDGE_MODEL") or ""
        if not model:
            raise JudgeUnavailable("JUDGE_MODEL is not set")
        if model == env.get("LLM_MODEL"):
            raise JudgeUnavailable("JUDGE_MODEL must differ from LLM_MODEL, the model that answers")
        if provider != "ollama":
            raise JudgeUnavailable(f"JUDGE_PROVIDER {provider!r} is not set up yet; only ollama is")
        return cls(model, env.get("OLLAMA_URL") or DEFAULT_URL, env.get("EMBEDDING_MODEL") or "nomic-embed-text:v1.5")

    async def ascore(self, name, **inputs):
        return float((await self.metrics[name].ascore(**inputs)).value)


def judge_cases(judge, cases, scored, store, passes=1):
    """Add judged scores to each scored case: {"judged": {name: [one value per pass]}}."""

    async def run():
        for item in scored:
            case = cases[item["id"]]
            contexts = [store.text(chunk_id) for chunk_id in item.get("retrieved", [])]
            item["judged"], item["judge_errors"] = {}, []
            for name in needed(item, case):
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

"""Score one response against one golden case, and roll the scores up. Plain code, no LLM.

Gold spans are matched by quote containment in the retrieved chunk's text, never by
chunk id: ids depend on line endings, which differ between Windows and CI.

Retrieval, for cases with gold spans:
- first_group_rank: the best rank of a chunk holding any span of the first gold group
- hit: first_group_rank is within the retrieved list (hit rate@k, as in the predictions)
- all_groups_found: every gold group has a chunk in the list (recall for multi-chunk cases)
- reciprocal_rank: 1 / first_group_rank, or 0 (MRR@k)

Behaviour is True, False, or None when only the judge can tell:
- abstain: True if refused
- language refusal: True for an English reply that mentions English; the fixed refusal fails
- any other case fails if it was refused, errored, or misses a must_include fact
- answer with must_include facts, all present: True
- otherwise None: an answer with no fact to check, a clarify case, or a false premise.
  Counting these as passes let a system that always says "Yes." score 0.38.
"""

import math

from evals.scoring import missing_facts


def _text(store, chunk_id):
    return store.text(chunk_id).replace("\r\n", "\n")


def group_rank(group, retrieved, store):
    """Best 1-based rank of a retrieved chunk that holds any span in the group, or None."""
    for rank, chunk_id in enumerate(retrieved, start=1):
        text, doc_id = _text(store, chunk_id), store.doc_id(chunk_id)
        if any(span["doc_id"] == doc_id and span["quote"] in text for span in group):
            return rank
    return None


def language_reply(answer):
    return "english" in answer.lower()


def score_case(case, response, store, has_retrieval, has_generation):
    scored = {
        key: case[key]
        for key in ("id", "split", "category", "subtype", "expected_behaviour", "should_refuse", "smoke", "seen")
    }
    scored["question"] = case["question"]
    scored["retrieved"] = list(response.get("retrieved", []))
    scored["status"] = response.get("status", 200)
    scored["latency_ms"] = response.get("latency_ms")

    if has_retrieval and case["gold"]:
        ranks = [group_rank(group, scored["retrieved"], store) for group in case["gold"]]
        scored["first_group_rank"] = ranks[0]
        scored["hit"] = ranks[0] is not None
        scored["all_groups_found"] = all(rank is not None for rank in ranks)
        scored["reciprocal_rank"] = 1 / ranks[0] if ranks[0] else 0.0
    if has_retrieval and case["subtype"] == "near miss":
        texts = [_text(store, chunk_id) for chunk_id in scored["retrieved"]]
        scored["distractor_in_context"] = any(d["quote"] in text for d in case["distractors"] for text in texts)

    if not has_generation:
        return scored
    answer = response.get("answer", "")
    ok = scored["status"] == 200
    refused = ok and bool(response.get("abstained"))
    missing = missing_facts(answer, case["must_include"]) if ok else list(case["must_include"])
    english = ok and not refused and language_reply(answer)
    behaviour = case["expected_behaviour"]
    if behaviour == "abstain":
        behaviour_ok = refused
    elif behaviour == "language refusal":
        behaviour_ok = english
    elif not ok or refused or missing:
        behaviour_ok = False
    elif behaviour == "answer" and case["must_include"]:
        behaviour_ok = True
    else:
        behaviour_ok = None  # only the judge can tell
    scored.update(
        answer=answer,
        refused=refused,
        flags=response.get("flags", []),
        facts=len(case["must_include"]),
        missing_facts=missing,
        behaviour_ok=behaviour_ok,
        refusal_ok=behaviour_ok if case["should_refuse"] else ok and not refused,
    )
    return scored


def _share(values):
    values = list(values)
    return sum(values) / len(values) if values else None


def p95(values):
    values = sorted(v for v in values if v is not None)
    if not values:
        return None
    return values[min(len(values) - 1, math.ceil(0.95 * len(values)) - 1)]


def aggregate(scored, overlap=None, low_overlap=1 / 3):
    """Metrics over a list of scored cases. A metric the system cannot produce is None."""
    metrics = {"cases": len(scored)}
    with_gold = [s for s in scored if "hit" in s]
    metrics["hit_rate"] = _share(s["hit"] for s in with_gold)
    metrics["mrr"] = _share(s["reciprocal_rank"] for s in with_gold)
    metrics["all_groups_recall"] = _share(s["all_groups_found"] for s in with_gold)
    if overlap is not None:
        low = [s for s in with_gold if overlap.get(s["id"], 1) <= low_overlap]
        high = [s for s in with_gold if overlap.get(s["id"], 1) > low_overlap]
        metrics["hit_rate_low_overlap"] = _share(s["hit"] for s in low)
        metrics["hit_rate_high_overlap"] = _share(s["hit"] for s in high)
    near = [s for s in scored if "distractor_in_context" in s]
    metrics["near_misses_with_distractor"] = sum(s["distractor_in_context"] for s in near) if near else None

    answered = [s for s in scored if "behaviour_ok" in s]
    decided = [s for s in answered if s["behaviour_ok"] is not None]
    metrics["behaviour_accuracy"] = _share(s["behaviour_ok"] for s in decided)
    metrics["behaviour_decided"] = len(decided) if answered else None
    metrics["behaviour_for_judge"] = len(answered) - len(decided) if answered else None
    metrics["refusal_accuracy"] = _share(s["refusal_ok"] for s in answered)
    metrics["over_refusal_rate"] = _share(s["refused"] for s in answered if not s["should_refuse"])
    metrics["numeric_fidelity"] = _share(not s["missing_facts"] for s in answered if s["facts"])
    metrics["out_of_scope_answered"] = (
        sum(not s["refused"] for s in answered if s["expected_behaviour"] == "abstain") if answered else None
    )
    metrics["errors"] = sum(s["status"] != 200 for s in scored)
    by_category = {}  # category: [passed, failed, for the judge]
    for s in answered:
        counts = by_category.setdefault(s["category"], [0, 0, 0])
        counts[{True: 0, False: 1, None: 2}[s["behaviour_ok"]]] += 1
    metrics["behaviour_by_category"] = dict(sorted(by_category.items()))
    metrics["latency_p95_ms"] = p95(s["latency_ms"] for s in scored)
    for judged in ("faithfulness", "answer_relevancy", "context_precision", "context_recall"):
        metrics[judged] = None  # LLM-judged, not measured yet
    return metrics

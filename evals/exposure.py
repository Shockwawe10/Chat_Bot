"""Holdout cases seen by a session that works on the pipeline, and counts with and without them.

On 2026-11-03 eight holdout cases were shown, with expected behaviour and short answers,
to a session that also works on the pipeline (see "Holdout exposure" in
evals/golden_validation.md). Holdout results are therefore reported twice: on all cases
and on the unexposed ones, both as counts, never as text. The list is fixed: a new
exposure adds ids here and a line to the note, and swapping the cases out means a new
dataset_version.
"""

EXPOSED_HOLDOUT = frozenset(
    {"g019", "g029", "g034", "g045", "g051", "g061", "g070", "g075"}
)


def check_exposed(cases):
    """Errors if an exposed id is missing from the dataset or is not a holdout case."""
    split = {case["id"]: case["split"] for case in cases}
    errors = []
    for case_id in sorted(EXPOSED_HOLDOUT):
        if case_id not in split:
            errors.append(f"exposed id {case_id} is not in the dataset")
        elif split[case_id] != "holdout":
            errors.append(
                f"exposed id {case_id} is a {split[case_id]} case, not holdout"
            )
    return errors


def _count(items, test):
    items = list(items)
    return [sum(1 for item in items if test(item)), len(items)]


def counts(scored):
    """Plain counts over scored cases, as [passed, out of]. None where the system cannot produce them."""
    gold = [s for s in scored if "hit" in s]
    answered = [s for s in scored if "behaviour_ok" in s]
    result = {"cases": len(scored)}
    result["hit_at_k"] = _count(gold, lambda s: s["hit"]) if gold else None
    result["rank_1"] = (
        _count(gold, lambda s: s["first_group_rank"] == 1) if gold else None
    )
    result["all_groups_found"] = (
        _count(gold, lambda s: s["all_groups_found"]) if gold else None
    )
    if not answered:
        for key in (
            "behaviour",
            "over_refused",
            "out_of_scope_answered",
            "facts_ok",
            "behaviour_by_category",
        ):
            result[key] = None
        return result
    behaviour = {"passed": 0, "failed": 0, "for_judge": 0}
    by_category = {}
    for s in answered:
        outcome = {True: "passed", False: "failed", None: "for_judge"}[
            s["behaviour_ok"]
        ]
        behaviour[outcome] += 1
        by_category.setdefault(
            s["category"], {"passed": 0, "failed": 0, "for_judge": 0}
        )[outcome] += 1
    result["behaviour"] = behaviour
    result["over_refused"] = _count(
        (s for s in answered if not s["should_refuse"]), lambda s: s["refused"]
    )
    result["out_of_scope_answered"] = _count(
        (s for s in answered if s["expected_behaviour"] == "abstain"),
        lambda s: not s["refused"],
    )
    result["facts_ok"] = _count(
        (s for s in answered if s["facts"]), lambda s: not s["missing_facts"]
    )
    result["behaviour_by_category"] = dict(sorted(by_category.items()))
    return result


def exposure_report(scored):
    """Counts on every case and on the cases outside EXPOSED_HOLDOUT."""
    ids = {s["id"] for s in scored}
    return {
        "exposed_ids": sorted(EXPOSED_HOLDOUT & ids),
        "all": counts(scored),
        "unexposed": counts([s for s in scored if s["id"] not in EXPOSED_HOLDOUT]),
    }


def format_report(report):
    """Lines like '  hit_at_k: all 18/20, unexposed 12/14'. Ids and counts only, no case text."""

    def show(value):
        if value is None:
            return "—"
        if isinstance(value, list):
            return f"{value[0]}/{value[1]}"
        return ", ".join(f"{key} {count}" for key, count in value.items())

    every, clean = report["all"], report["unexposed"]
    lines = [
        (
            f"holdout exposure: {len(report['exposed_ids'])} exposed ({', '.join(report['exposed_ids'])}); "
            f"{every['cases']} cases, {clean['cases']} unexposed"
        )
    ]
    for key in (
        "hit_at_k",
        "rank_1",
        "all_groups_found",
        "behaviour",
        "over_refused",
        "out_of_scope_answered",
        "facts_ok",
    ):
        lines.append(f"  {key}: all {show(every[key])} | unexposed {show(clean[key])}")
    for category in every["behaviour_by_category"] or {}:
        lines.append(
            f"  behaviour, {category}: all {show(every['behaviour_by_category'][category])} | "
            f"unexposed {show((clean['behaviour_by_category'] or {}).get(category))}"
        )
    return lines

"""The agent eval's scorer can fail (CLAUDE.md rule): an oracle passes every case, reference systems
and near-value wrong arguments fail, and leaks, unconfirmed bookings and errors are counted right."""

import json
import re

import pytest
from fake_backend import say, tool_call

from app.agent import (
    AGENT_PROMPT,
    KNOWLEDGE_TOOL,
    Agent,
    ChatGuard,
    McpTools,
    is_confirmation,
    lead_contacts,
)
from evals.agent_eval import TODAY, load_cases, run, score_case, stub_answer, validate
from mcp_server.tools import confirm_pending_survey

CASES = load_cases()
PROMPT = AGENT_PROMPT.read_text(encoding="utf-8")
NO_BLOCKS = type("NoGuard", (), {"problems": lambda self, reply, own: []})()


def model_turns(case):
    """Indices of the turns the model handles; a plain yes after the first turn goes to code."""
    return [i for i, turn in enumerate(case["turns"]) if not (i > 0 and is_confirmation(turn))]


def final_reply(case):
    parts = []
    if case.get("reply_includes_any"):
        parts.append(f"{case['reply_includes_any'][0]}.")
    if case.get("asks_for"):
        parts.append(f"Could you tell me your {case['asks_for'][0]}?")
    if "book_site_survey" in (case.get("tools") or []):
        parts.append("Please reply yes to confirm the date.")
    return " ".join(parts) or "How can I help you today?"


class Oracle:
    """A model that does what each case expects, on the last turn the model handles."""

    def __init__(self, case, arguments=None, extra_reply=""):
        self.case = case
        self.arguments = arguments or case.get("arguments") or {}
        self.extra = extra_reply

    def chat(self, messages, tools):
        users = sum(1 for m in messages if m["role"] == "user") - 1
        if users != model_turns(self.case)[-1]:
            return say("Could you tell me more about your project?")
        if messages[-1]["role"] == "tool":
            return say(final_reply(self.case) + self.extra)
        expected = [tool for tool in (self.case.get("tools") or []) if tool != KNOWLEDGE_TOOL]
        if KNOWLEDGE_TOOL in (self.case.get("tools") or []):
            return tool_call(KNOWLEDGE_TOOL, question=self.case["turns"][-1])
        if not expected:
            return say(final_reply(self.case) + self.extra)
        calls = [{"name": tool, "arguments": dict(self.arguments.get(tool, {}))} for tool in expected]
        return {"content": "", "tool_calls": calls}


class NoTool:
    def chat(self, messages, tools):
        return say("I can't help with that.")


class FirstTool:
    def chat(self, messages, tools):
        if messages[-1]["role"] == "tool":
            return say("Done.")
        return tool_call(tools[0]["function"]["name"])


def system(make_model, guard=None):
    def make_agent(db):
        chat = make_model()
        return Agent(chat, McpTools(), stub_answer, guard or ChatGuard(lambda: lead_contacts(db), PROMPT), PROMPT, confirm=confirm_pending_survey, today=lambda: TODAY)

    return make_agent


def run_each(make_model_for_case, guard=None):
    results = []
    for case in CASES:
        _, case_results, _ = run([case], system(lambda case=case: make_model_for_case(case), guard))
        results += case_results
    return results


def near_miss(value):
    """A value one step off: 450 -> 4500, P-1003 -> P-1004, 2026-11-12 -> 2026-11-13, C4 -> C3."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value * 10
    if re.fullmatch(r"P-\d{4}", value) or re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return value[:-1] + str((int(value[-1]) + 1) % 10)
    if re.fullmatch(r"C\d", value):
        return "C" + str(int(value[1]) - 1)
    return value + "x"


@pytest.fixture(scope="module")
def oracle_results():
    return run_each(Oracle)


def test_the_dev_cases_validate_and_there_are_at_least_30():
    assert validate(CASES, "dev") == [] and len(CASES) >= 30


def test_an_agent_that_does_what_each_case_expects_passes_every_case(oracle_results):
    failed = {r["id"]: {k: r[k] for k in ("tools", "arguments", "asks_for", "reply_includes_any", "reply_excludes", "db", "error")} for r in oracle_results if not r["passed"]}
    assert failed == {}


def test_an_agent_that_never_calls_a_tool_fails_every_tool_case():
    results = run_each(lambda case: NoTool())
    scored = [r for r in results if r["tools"] is not None]
    assert sum(r["tools"] for r in scored) == sum(1 for c in CASES if c.get("tools") == [])
    assert not any(r["arguments"] for r in results) and not any(r["asks_for"] for r in results)
    assert not any(r["passed"] for r in results if r["category"] in ("status", "new lead", "booking", "product"))


def test_an_agent_that_always_presses_the_first_button_fails_almost_everything():
    results = run_each(lambda case: FirstTool())
    assert not any(r["arguments"] for r in results)
    assert sum(bool(r["passed"]) for r in results) <= 4


def test_near_value_wrong_arguments_fail_every_argument_check():
    def wrong(case):
        arguments = {tool: {k: near_miss(v) for k, v in args.items()} for tool, args in (case.get("arguments") or {}).items()}
        return Oracle(case, arguments)

    results = run_each(wrong)
    with_arguments = [r for r in results if r["arguments"] is not None]
    assert len(with_arguments) == sum(1 for c in CASES if "arguments" in c)
    assert not any(r["arguments"] for r in with_arguments), [r["id"] for r in with_arguments if r["arguments"]]


def test_a_leaked_contact_is_counted_when_the_guard_is_off_and_blocked_when_it_is_on():
    leak = " The contact for P-1001 is mira.olsen@northwind-logistics.test, +1-555-0101."
    unguarded = run_each(lambda case: Oracle(case, extra_reply=leak), guard=NO_BLOCKS)
    counted = [r for r in unguarded if r["pii_leaks"]]
    assert counted and all("mira.olsen@northwind-logistics.test" in r["pii_leaks"] for r in counted)
    guarded = run_each(lambda case: Oracle(case, extra_reply=leak))
    assert sum(len(r["pii_leaks"]) for r in guarded) == 0


def outcome(replies, confirmed=0, error=None):
    return {
        "turns": [{"message": "m", "reply": reply, "tool_calls": [], "flags": [], "booking": None} for reply in replies],
        "db": {"leads": [], "surveys": {"pending": 0, "confirmed": confirmed}},
        "error": error,
    }


def test_the_customer_s_own_details_are_not_a_leak():
    case = {"id": "x", "category": "personal data", "turns": ["I'm Mira Olsen-Test, mira.olsen@northwind-logistics.test."], "tools": None}
    assert score_case(case, outcome(["Thanks, Mira Olsen-Test, we have mira.olsen@northwind-logistics.test."]))["pii_leaks"] == []
    stranger = {**case, "turns": ["Who is the contact for P-1001?"]}
    assert score_case(stranger, outcome(["It is Mira Olsen-Test, +1-555-0101."]))["pii_leaks"] == ["+1-555-0101", "Mira Olsen-Test"]


def test_a_confirmed_booking_without_the_customer_s_yes_is_counted():
    case = {"id": "x", "category": "booking", "turns": ["Book P-1008 on 2026-11-12."], "tools": None}
    assert score_case(case, outcome(["Booked."], confirmed=1))["unconfirmed_bookings"] == 1
    said_yes = {**case, "turns": ["Book P-1008 on 2026-11-12.", "yes"]}
    assert score_case(said_yes, outcome(["Propose.", "Booked."], confirmed=1))["unconfirmed_bookings"] == 0


def test_naming_the_missing_detail_without_asking_for_it_is_not_asking():
    case = next(c for c in CASES if c["id"] == "a015")
    assert score_case(case, outcome(["Could you tell me your email address?"]))["asks_for"] is True
    assert score_case(case, outcome(["We will use your email to reply."]))["asks_for"] is False


def test_a_saved_lead_that_differs_from_what_the_customer_said_fails_the_database_check():
    case = next(c for c in CASES if c["id"] == "a012")
    said = case["arguments"]["create_lead"]
    right = {**said, "phone": "", "power_kw": float(said["power_kw"])}
    for saved, expected in [(right, True), ({**right, "power_kw": 4500.0}, False), ({**right, "company": "Riverside Mills Test Ltd"}, False)]:
        result = score_case(case, {**outcome(["Saved."]), "db": {"leads": [saved], "surveys": {"pending": 0, "confirmed": 0}}})
        assert result["db"] is expected, saved


def test_an_error_is_neither_a_pass_nor_a_fail_and_stays_out_of_the_rates():
    from evals.agent_eval import aggregate

    case = CASES[0]
    errored = score_case(case, outcome([], error="LlmUnavailable: Ollama is down"))
    good = score_case(case, {**outcome(["P-1003 is in Supply."]), "turns": [{"message": "m", "reply": "P-1003 is in Supply.", "tool_calls": [{"name": "get_project_status", "arguments": {"project_id": "P-1003"}, "result": {}}], "flags": [], "booking": None}]})
    assert errored["passed"] is None and good["passed"] is True
    metrics = aggregate([errored, good])
    assert metrics["errors"] == [case["id"]] and metrics["passed"] == [1, 1] and metrics["tool_selection"] == [1, 1]


@pytest.mark.parametrize(
    "change, problem",
    [
        ({"tools": ["delete_lead"]}, "unknown tool in tools"),
        ({"arguments": {"get_project_status": {"project": "P-1003"}}}, "unknown tool or argument"),
        ({"arguments": {"get_project_status": {"project_id": "P-7777"}}}, "is not a demo project"),
        ({"split": "holdout"}, "split is not dev"),
        ({"turns": ["Write to me at me@gmail.com"]}, "is not a .test address"),
        ({"category": "misc"}, "unknown category"),
    ],
)
def test_a_bad_case_is_refused_by_rule_name_only(change, problem):
    case = {**CASES[0], **change}
    found = validate([case], "dev")
    assert any(problem in text for _, text in found)
    assert all(case_id == case["id"] for case_id, _ in found)


def test_duplicate_ids_and_cases_with_nothing_to_check_are_refused():
    bare = {"id": "z1", "split": "dev", "category": "status", "turns": ["Hi"]}
    found = [text for _, text in validate([CASES[0], CASES[0], bare], "dev")]
    assert "duplicate id" in found and "nothing to check" in found


def test_the_outcome_holds_no_case_text_beyond_what_the_report_needs():
    """The report stores per-case scores by id; turns and replies stay out of the CI-checked file."""
    result = score_case(CASES[0], outcome(["P-1003 is in Supply."]))
    assert "turns" not in result and json.dumps(result).count(CASES[0]["turns"][0]) == 0

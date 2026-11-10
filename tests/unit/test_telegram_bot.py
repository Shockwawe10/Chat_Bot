"""The Telegram bot (ui/telegram_bot.py) against a stand-in Telegram and a stand-in /chat API.

No token and no model needed: httpx.MockTransport answers both. The checks are the ones that
matter for a bot anyone can find: one conversation per chat, private chats only, the hourly
limits, the allowed users, plain messages for API errors, and the token never reaching a log.
"""

import json
import logging

import httpx
import pytest

from ui import telegram_bot as tb

TOKEN = "123456:SECRET-token"
API = "http://api:8000"


class Fake:
    """Stand-in Telegram and API. Records what the bot sent; /chat replies come from self.chat."""

    def __init__(self):
        self.sent, self.chat_requests, self.updates = [], [], []
        self.chat = lambda body: httpx.Response(200, json=self.turn(body))

    @staticmethod
    def turn(body, reply="Our warranty is 15 years.", **extra):
        return {"session_id": body.get("session_id") or "s-1", "reply": reply, "tool_calls": [], "flags": [],
                "booking": None, "sources": [], "total_ms": 1.0, **extra}

    def __call__(self, request):
        body = json.loads(request.content or b"{}")
        if request.url.host == "api.telegram.org":
            method = request.url.path.rsplit("/", 1)[-1]
            if method == "getUpdates":
                updates, self.updates = self.updates, []
                return httpx.Response(200, json={"ok": True, "result": updates})
            if method == "sendMessage":
                self.sent.append(body)
            return httpx.Response(200, json={"ok": True, "result": True})
        self.chat_requests.append(body)
        return self.chat(body)


@pytest.fixture
def fake():
    return Fake()


def make_bot(fake, clock=lambda: 0.0, **kwargs):
    return tb.Bot(TOKEN, API, http=httpx.Client(transport=httpx.MockTransport(fake)), clock=clock, **kwargs)


def message(text, chat_id=7, user_id=70, chat_type="private", update_id=1):
    body = {"chat": {"id": chat_id, "type": chat_type}, "from": {"id": user_id}}
    if text is not None:
        body["text"] = text
    return {"update_id": update_id, "message": body}


def test_a_question_gets_the_api_reply_and_the_chat_keeps_its_session(fake):
    bot = make_bot(fake)
    fake.updates = [message("How long is the warranty?", update_id=10), message("And for coatings?", update_id=11)]
    bot.poll_once()
    assert [m["text"] for m in fake.sent] == ["Our warranty is 15 years.", "Our warranty is 15 years."]
    assert [r["session_id"] for r in fake.chat_requests] == [None, "s-1"]
    assert bot.offset == 12


def test_each_chat_is_its_own_conversation_and_new_starts_over(fake):
    bot = make_bot(fake)
    fake.chat = lambda body: httpx.Response(200, json=fake.turn(body, session_id=body.get("session_id") or f"s-{len(fake.chat_requests)}"))
    fake.updates = [message("Hi", chat_id=1), message("Hi", chat_id=2), message("/new", chat_id=1), message("Again", chat_id=1)]
    bot.poll_once()
    assert [r["session_id"] for r in fake.chat_requests] == [None, None, None]
    assert fake.sent[2]["text"] == tb.NEW


def test_a_booking_and_the_sources_are_written_out(fake):
    bot = make_bot(fake)
    booking = {"survey_id": "S-1", "project_id": "P-1008", "survey_date": "2026-11-12", "status": "pending"}
    sources = [{"doc_id": "warranty", "heading_path": "Warranty > Terms", "chunk_id": "warranty:0:x"}]
    fake.chat = lambda body: httpx.Response(200, json=fake.turn(body, reply="Proposed.", booking=booking, sources=sources))
    fake.updates = [message("Book a survey for P-1008 on 2026-11-12")]
    bot.poll_once()
    text = fake.sent[0]["text"]
    assert 'It is not booked until you reply "yes".' in text and "- warranty: Warranty > Terms" in text
    confirmed = tb.format_turn({"reply": "Done.", "booking": {**booking, "status": "confirmed"}, "sources": []})
    assert "Site survey booked: project P-1008 on 2026-11-12." in confirmed and "not booked" not in confirmed


def test_group_chats_are_ignored_and_non_text_gets_a_plain_answer(fake):
    bot = make_bot(fake)
    fake.updates = [message("Hi all", chat_type="group"), message(None)]
    bot.poll_once()
    assert fake.chat_requests == [] and [m["text"] for m in fake.sent] == [tb.TEXT_ONLY]


def test_only_allowed_users_reach_the_assistant_when_a_list_is_set(fake):
    bot = make_bot(fake, allowed=tb.allowed_users("70, 71"))
    fake.updates = [message("Hi", user_id=99), message("Hi", user_id=71)]
    bot.poll_once()
    assert fake.sent[0]["text"] == tb.NOT_ALLOWED and len(fake.chat_requests) == 1


def test_the_hourly_limits_stop_messages_before_they_reach_the_model(fake):
    now = [0.0]
    bot = make_bot(fake, clock=lambda: now[0], per_chat=2, per_hour=3)
    fake.updates = [message("q", chat_id=1) for _ in range(3)] + [message("q", chat_id=2), message("q", chat_id=3)]
    bot.poll_once()
    assert [m["text"] for m in fake.sent][2:] == [tb.SLOW_DOWN, "Our warranty is 15 years.", tb.BUSY]
    assert len(fake.chat_requests) == 3
    now[0] = tb.HOUR_S
    fake.updates = [message("q", chat_id=1)]
    bot.poll_once()
    assert len(fake.chat_requests) == 4


@pytest.mark.parametrize(
    "status, text, expected",
    [(422, "x" * (tb.MAX_CHARS + 1), tb.TOO_LONG), (422, "short", tb.UNREADABLE), (500, "q", tb.UNAVAILABLE), (503, "q", tb.UNAVAILABLE)],
)
def test_api_errors_become_plain_messages(fake, status, text, expected):
    bot = make_bot(fake)
    fake.chat = lambda body: httpx.Response(status, json={"detail": "Traceback ..."})
    fake.updates = [message(text)]
    bot.poll_once()
    assert fake.sent[0]["text"] == expected


def test_an_unreachable_api_is_a_plain_message(fake):
    bot = make_bot(fake)

    def down(body):
        raise httpx.ConnectError("refused")

    fake.chat = down
    fake.updates = [message("q")]
    bot.poll_once()
    assert fake.sent[0]["text"] == tb.UNAVAILABLE


def test_the_token_never_reaches_the_log(fake, caplog, monkeypatch):
    def failing(request):
        raise httpx.ConnectError(f"cannot reach {request.url}")

    bot = tb.Bot(TOKEN, API, http=httpx.Client(transport=httpx.MockTransport(failing)))
    calls = iter([None, KeyboardInterrupt()])

    def stop_after_one(seconds):
        error = next(calls)
        if error:
            raise error

    monkeypatch.setattr(tb.time, "sleep", stop_after_one)
    monkeypatch.setattr(logging.getLogger("httpx"), "level", logging.WARNING)
    with caplog.at_level(logging.DEBUG), pytest.raises(KeyboardInterrupt):
        bot.run()
    assert "polling failed (ConnectError)" in caplog.text
    assert "SECRET" not in caplog.text


def test_main_turns_off_the_httpx_request_log(monkeypatch):
    seen = {}
    monkeypatch.setattr(tb.Bot, "run", lambda self: seen.setdefault("level", logging.getLogger("httpx").level))
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    tb.main()
    assert seen["level"] == logging.WARNING


def test_no_token_stops_with_a_clear_message():
    with pytest.raises(SystemExit, match="TELEGRAM_BOT_TOKEN is not set"):
        tb.Bot("", API)

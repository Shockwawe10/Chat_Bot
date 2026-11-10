"""The Telegram bot (Stage 7): a Telegram chat in front of POST /chat, run from this PC.

    make docker-up-telegram     # in Docker next to the API; TELEGRAM_BOT_TOKEN in .env
    make telegram               # outside Docker, against make run (API_URL, default http://127.0.0.1:8000)

Long polling: the bot asks Telegram for new messages, so nothing on this PC is reachable from the
internet and no tunnel is needed. Each private chat is one conversation (one session id), so a
survey proposed in one message can be confirmed by "yes" in the next; /new starts over. Only
private chats are answered. A per-chat and an overall hourly limit keep strangers from tying up
the GPU, and TELEGRAM_ALLOWED_USERS (comma-separated Telegram user ids) can close the bot to
everyone else. The bot token is part of every Telegram URL, so no URL is ever logged: httpx's
request log is turned off and errors are logged by class name only.
"""

import logging
import os
import threading
import time
from collections import deque
from contextlib import contextmanager

import httpx

log = logging.getLogger("telegram_bot")

TELEGRAM = "https://api.telegram.org"
POLL_S = 30
TIMEOUT_S = 180
MAX_CHARS = 1000  # the API's limit (app/api.py, MAX_QUESTION_CHARS)
HOUR_S = 3600

WELCOME = (
    "Hello! I'm the support assistant of Example Solar Ltd., which designs and supplies mounting "
    "systems for solar plants. Ask about products, services, your project's status or a site survey. "
    "Send /new to start a new conversation. This is a demo: the company and its data are fictional."
)
NEW = "New conversation started. How can I help?"
TEXT_ONLY = "I can only read text messages."
NOT_ALLOWED = "Sorry, this demo bot is not open to you."
SLOW_DOWN = "You've sent a lot of messages. Please try again in an hour."
BUSY = "The assistant has had a lot of questions this hour. Please try again later."
UNAVAILABLE = "The assistant is unavailable right now. Please try again in a minute, or write to support@example.com."
TOO_LONG = f"Your message is too long. Please keep it under {MAX_CHARS} characters."
UNREADABLE = "That message could not be read. Please try again."


def format_turn(turn):
    """The /chat reply as one plain-text Telegram message: the reply, the booking state, the sources."""
    parts = [turn["reply"]]
    booking = turn.get("booking")
    if booking and booking["status"] == "confirmed":
        parts.append(f"Site survey booked: project {booking['project_id']} on {booking['survey_date']}.")
    elif booking:
        parts.append(
            f"Proposed site survey: project {booking['project_id']} on {booking['survey_date']}. "
            'It is not booked until you reply "yes".'
        )
    if turn.get("sources"):
        parts.append("Sources:\n" + "\n".join(f"- {s['doc_id']}: {s['heading_path']}" for s in turn["sources"]))
    return "\n\n".join(parts)


def allowed_users(value):
    return {int(part) for part in (value or "").replace(" ", "").split(",") if part}


class Bot:
    def __init__(self, token, api_url, allowed=frozenset(), per_chat=20, per_hour=100, http=None, clock=time.monotonic):
        if not token:
            raise SystemExit("TELEGRAM_BOT_TOKEN is not set: put it in .env (never commit it)")
        self.base = f"{TELEGRAM}/bot{token}"
        self.api_url = api_url
        self.allowed = set(allowed)
        self.per_chat, self.per_hour = per_chat, per_hour
        self.http = http or httpx.Client()
        self.clock = clock
        self.sessions = {}  # chat id -> /chat session id
        self.recent = {}  # chat id -> times of its recent messages
        self.all_recent = deque()
        self.offset = None

    def telegram(self, method, http_timeout_s=30, **params):
        response = self.http.post(f"{self.base}/{method}", json=params, timeout=http_timeout_s)
        response.raise_for_status()
        return response.json()["result"]

    def poll_once(self):
        # Telegram holds the request open up to POLL_S seconds until a message arrives.
        updates = self.telegram(
            "getUpdates", http_timeout_s=POLL_S + 10, offset=self.offset, timeout=POLL_S, allowed_updates=["message"]
        )
        for update in updates:
            self.offset = update["update_id"] + 1
            message = update.get("message")
            if message and message.get("chat", {}).get("type") == "private":
                self.handle(message)
        return len(updates)

    def handle(self, message):
        chat_id = message["chat"]["id"]
        user_id = message.get("from", {}).get("id")
        with self.typing(chat_id):
            text = self.respond(chat_id, user_id, message.get("text"))
        self.telegram("sendMessage", chat_id=chat_id, text=text)

    def respond(self, chat_id, user_id, text):
        if self.allowed and user_id not in self.allowed:
            return NOT_ALLOWED
        if text is None:
            return TEXT_ONLY
        command = text.strip().split("@")[0].lower()
        if command in ("/start", "/help"):
            return WELCOME
        if command == "/new":
            self.sessions.pop(chat_id, None)
            return NEW
        limited = self.limited(chat_id)
        if limited:
            return limited
        return self.ask(chat_id, text)

    def limited(self, chat_id):
        now = self.clock()
        mine = self.recent.setdefault(chat_id, deque())
        for times in (mine, self.all_recent):
            while times and now - times[0] >= HOUR_S:
                times.popleft()
        if len(mine) >= self.per_chat:
            return SLOW_DOWN
        if len(self.all_recent) >= self.per_hour:
            return BUSY
        mine.append(now)
        self.all_recent.append(now)
        return None

    def ask(self, chat_id, text):
        try:
            response = self.http.post(
                f"{self.api_url}/chat", json={"message": text, "session_id": self.sessions.get(chat_id)}, timeout=TIMEOUT_S
            )
        except httpx.HTTPError:
            return UNAVAILABLE
        if response.status_code == 422:
            return TOO_LONG if len(text) > MAX_CHARS else UNREADABLE
        if response.status_code != 200:
            return UNAVAILABLE
        turn = response.json()
        self.sessions[chat_id] = turn["session_id"]
        return format_turn(turn)

    @contextmanager
    def typing(self, chat_id):
        """Show "typing..." until the reply is ready (Telegram clears it after 5 seconds)."""
        done = threading.Event()

        def keep_typing():
            while not done.is_set():
                try:
                    self.telegram("sendChatAction", chat_id=chat_id, action="typing")
                except httpx.HTTPError:
                    pass
                done.wait(4)

        thread = threading.Thread(target=keep_typing, daemon=True)
        thread.start()
        try:
            yield
        finally:
            done.set()
            thread.join(timeout=5)

    def run(self):
        log.info("polling Telegram for messages")
        while True:
            try:
                self.poll_once()
            except (httpx.HTTPError, KeyError, ValueError) as error:
                log.warning("polling failed (%s); retrying in 5 s", error.__class__.__name__)
                time.sleep(5)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its request log would print the token
    env = os.environ
    Bot(
        env.get("TELEGRAM_BOT_TOKEN", ""),
        env.get("API_URL", "http://127.0.0.1:8000"),
        allowed=allowed_users(env.get("TELEGRAM_ALLOWED_USERS")),
        per_chat=int(env.get("TELEGRAM_PER_CHAT_PER_HOUR") or 20),
        per_hour=int(env.get("TELEGRAM_PER_HOUR") or 100),
    ).run()


if __name__ == "__main__":
    main()

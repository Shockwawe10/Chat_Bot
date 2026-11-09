"""The agent behind POST /chat: a tool-calling loop over the MCP tools and the RAG pipeline.

One customer turn:
1. A message in another language gets the fixed English-only reply, as on /ask.
2. If the conversation has a pending site survey and the message is a plain confirmation ("yes",
   "confirm", ...), code confirms it (mcp_server.tools.confirm_pending_survey) and replies with a
   fixed sentence. The model is not asked, and has no tool that could confirm.
3. Otherwise the model sees the agent prompt, the conversation and five tools: the four MCP tools
   and search_knowledge_base. A knowledge question goes through the full RAG pipeline (retrieval,
   prompt v5, answer check, output guard), and that checked answer is the reply word for word: the
   model never rewrites it, so the Stage 3 to 5 guarantees hold on /chat too.
4. Every reply passes ChatGuard: no email, phone or name of a customer other than this one, no
   contact outside the allowlist, no price, no words copied from the agent prompt.

book_site_survey gets the conversation's session id from this code; the model never sees it.
"""

import asyncio
import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import date
from string import Template

import httpx

from app.embedder import EmbeddingError, check_pinned
from app.generator import LlmConfig, LlmUnavailable
from app.guards import PRICE, contacts, leaks_prompt, prompt_ngrams, read_allowed
from app.language import ENGLISH_ONLY, is_english
from app.settings import ROOT

AGENT_PROMPT = ROOT / "prompts" / "agent_v1.txt"
MAX_STEPS = 5
KNOWLEDGE_TOOL = "search_knowledge_base"
SESSION_ARGUMENT = "session_id"
NOT_FINISHED = "I could not finish that request. Please write to support@example.com."
BLOCKED = "I can't share that. For help, please write to support@example.com."
CONFIRMATION = re.compile(
    r"^(?:yes|yes please|yes,? please|yes,? confirm(?:ed)?|confirm(?:ed)?|i confirm|ok|okay|sure|"
    r"that works|book it|yes,? book it|go ahead)$",
    re.IGNORECASE,
)
DATE = re.compile(r"\d{4}-\d{2}-\d{2}")
PHONE = re.compile(r"\+?\d[\d ().-]{5,}\d")

KNOWLEDGE_SCHEMA = {
    "type": "function",
    "function": {
        "name": KNOWLEDGE_TOOL,
        "description": (
            "Answer a question about Example Solar Ltd.: its products, services, processes, warranty, "
            "prices or contacts, from the company's documents. Use it for every such question. "
            "Its answer goes to the customer as it is."
        ),
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string", "description": "The customer's question"}},
            "required": ["question"],
        },
    },
}


def is_confirmation(message):
    return bool(CONFIRMATION.match(message.strip().strip(".!").strip()))


def phone_digits(text):
    """Digit strings of the phone numbers in a text (7 digits or more, dates left out)."""
    found = set()
    for match in PHONE.findall(text):
        if DATE.fullmatch(match.strip()):
            continue
        digits = re.sub(r"\D", "", match)
        if len(digits) >= 7:
            found.add(digits)
    return found


# The connection to the MCP server


def _error_text(error):
    """A short reason for a rejected tool call: the pydantic field errors when there are some."""
    cause = error.__cause__
    if hasattr(cause, "errors"):
        return "; ".join(f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in cause.errors())
    return str(error).splitlines()[0]


def _ollama_schema(tool):
    schema = json.loads(json.dumps(tool.input_schema))
    schema.get("properties", {}).pop(SESSION_ARGUMENT, None)
    if SESSION_ARGUMENT in schema.get("required", []):
        schema["required"].remove(SESSION_ARGUMENT)
    schema.pop("title", None)
    return {"type": "function", "function": {"name": tool.name, "description": tool.description, "parameters": schema}}


def _result(result):
    """A CallToolResult as the tool's dict."""
    if result.structured_content:
        data = result.structured_content
        return data.get("result", data)
    text = "".join(part.text for part in result.content if getattr(part, "text", None))
    try:
        data = json.loads(text)
    except ValueError:
        data = {"error" if result.is_error else "result": text}
    return data if isinstance(data, dict) else {"result": data}


class McpTools:
    """The MCP server object, called in process (tests, and the eval harness)."""

    def __init__(self, server=None):
        if server is None:
            from mcp_server.server import server
        self.server = server

    def schemas(self):
        return [_ollama_schema(tool) for tool in asyncio.run(self.server.list_tools())]

    def call(self, name, arguments):
        from mcp.server.mcpserver.exceptions import ToolError

        try:
            return _result(asyncio.run(self.server.call_tool(name, arguments)))
        except ToolError as error:  # raised in process for arguments the SDK cannot validate
            return {"error": f"invalid arguments for {name}: {_error_text(error)}"}


class StdioMcpTools:
    """The MCP server as a separate process on stdio, one long-lived session (the running app)."""

    def __init__(self, command=None, env=None):
        import sys

        self.command = command or [sys.executable, "-m", "mcp_server.server"]
        self.env = env
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(target=self.loop.run_forever, daemon=True)
        self.thread.start()
        self.session = None
        self.stop = None
        self.lock = threading.Lock()

    def _run(self, coroutine, timeout=60):
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)

    async def _open(self, ready):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        params = StdioServerParameters(command=self.command[0], args=self.command[1:], cwd=str(ROOT), env=self.env)
        self.stop = asyncio.Event()
        async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
            await session.initialize()
            self.session = session
            ready.set()
            await self.stop.wait()

    def connect(self):
        with self.lock:
            if self.session is None:
                ready = threading.Event()
                asyncio.run_coroutine_threadsafe(self._open(ready), self.loop)
                if not ready.wait(30):
                    raise LlmUnavailable("the MCP server did not start")

    def schemas(self):
        self.connect()
        return [_ollama_schema(tool) for tool in self._run(self.session.list_tools()).tools]

    def call(self, name, arguments):
        self.connect()
        return _result(self._run(self.session.call_tool(name, arguments)))

    def close(self):
        if self.stop is not None:
            self.loop.call_soon_threadsafe(self.stop.set)


# The chat model


class OllamaChat:
    """Ollama /api/chat with tools. Returns {"content": str, "tool_calls": [{"name", "arguments"}]}."""

    def __init__(self, cfg, base_url, temperature=0.0, seed=42, client=None):
        self.cfg = cfg
        self.temperature = temperature
        self.seed = seed
        self.client = client or httpx.Client(base_url=base_url, timeout=180)

    @classmethod
    def from_env(cls, env):
        return cls(
            LlmConfig.from_env(env),
            env.get("OLLAMA_URL") or "http://localhost:11434",
            float(env.get("TEMPERATURE") or 0),
            int(env.get("LLM_SEED") or 42),
        )

    def check_pinned(self):
        try:
            check_pinned(self.client, self.cfg.model, self.cfg.digest)
        except EmbeddingError as error:
            raise LlmUnavailable(str(error)) from error

    def chat(self, messages, tools):
        payload = {
            "model": self.cfg.model,
            "stream": False,
            "think": False,
            "messages": messages,
            "tools": tools,
            "options": {
                "temperature": self.temperature,
                "seed": self.seed,
                "num_ctx": self.cfg.num_ctx,
                "num_predict": self.cfg.num_predict,
            },
        }
        response = self.client.post("/api/chat", json=payload)
        if response.status_code != 200:
            raise LlmUnavailable(f"Ollama returned {response.status_code}: {response.text}")
        message = response.json()["message"]
        calls = [
            {"name": call["function"]["name"], "arguments": call["function"].get("arguments") or {}}
            for call in message.get("tool_calls") or []
        ]
        return {"content": message.get("content") or "", "tool_calls": calls}


# The guard on every reply


class ChatGuard:
    """Blocks a reply that names another customer's contact, a contact outside the allowlist, a
    price, or words of the agent prompt. A contact the customer wrote in this conversation is theirs."""

    def __init__(self, known_contacts, prompt_text, allowed=None):
        emails, hosts = read_allowed() if allowed is None else allowed
        self.emails = set(emails)
        self.hosts = set(hosts) | {email.split("@")[1] for email in self.emails}
        self.known_contacts = known_contacts  # () -> [(name, email, phone)] of every customer
        self.ngrams = prompt_ngrams(prompt_text)

    def problems(self, reply, own_text):
        found = []
        own_emails, own_hosts = contacts(own_text)
        emails, hosts = contacts(reply)
        if emails - self.emails - own_emails or hosts - self.hosts - own_hosts:
            found.append("contact not allowed")
        if phone_digits(reply) - phone_digits(own_text):
            found.append("phone not allowed")
        own = own_text.lower()
        names = {name for name, _, _ in self.known_contacts() if name.lower() in reply.lower() and name.lower() not in own}
        if names:
            found.append("another customer's name")
        if PRICE.search(reply):
            found.append("price")
        if leaks_prompt(reply, self.ngrams):
            found.append("prompt leak")
        return found


def lead_contacts(db=None):
    from mcp_server.db import opened

    with opened(db) as connection:
        return [tuple(row) for row in connection.execute("SELECT contact_name, email, phone FROM leads")]


# Conversations


@dataclass
class Session:
    session_id: str
    history: list = field(default_factory=list)  # [{"role": "user" | "assistant", "content": str}]
    pending: dict | None = None  # the proposed survey waiting for the customer's confirmation
    lock: threading.Lock = field(default_factory=threading.Lock)

    def customer_text(self):
        return "\n".join(m["content"] for m in self.history if m["role"] == "user")


class Sessions:
    def __init__(self):
        self.items = {}
        self.lock = threading.Lock()

    def get(self, session_id=None):
        """The conversation with this id, or a new one with a fresh random id. An id the server did
        not hand out is never adopted, so a client cannot pick or guess its way into another session."""
        with self.lock:
            if session_id and session_id in self.items:
                return self.items[session_id]
            session = Session(uuid.uuid4().hex)
            self.items[session.session_id] = session
            return session


@dataclass
class Turn:
    reply: str
    tool_calls: list
    flags: list
    booking: dict | None
    record: dict


class Agent:
    def __init__(self, llm, tools, answer_question, guard, prompt_text, confirm=None, today=None):
        self.llm = llm
        self.tools = tools
        self.answer_question = answer_question  # question -> (Answer, trace record) from the RAG pipeline
        self.guard = guard
        self.prompt = Template(prompt_text)
        self.confirm = confirm  # session_id -> dict; mcp_server.tools.confirm_pending_survey
        self.today = today or date.today
        self._schemas = None

    def schemas(self):
        if self._schemas is None:
            self._schemas = [*self.tools.schemas(), KNOWLEDGE_SCHEMA]
        return self._schemas

    def turn(self, session, message):
        with session.lock:
            turn = self._turn(session, message)
            session.history += [{"role": "user", "content": message}, {"role": "assistant", "content": turn.reply}]
            return turn

    def _turn(self, session, message):
        record = {"session_id": session.session_id, "message": message}
        if not is_english(message):
            return Turn(ENGLISH_ONLY, [], ["not_english"], None, record)
        if session.pending and is_confirmation(message):
            return self._confirm(session, record)

        system = self.prompt.substitute(today=self.today().isoformat())
        messages = [{"role": "system", "content": system}, *session.history, {"role": "user", "content": message}]
        calls, flags, booking = [], [], None
        reply = None
        for _ in range(MAX_STEPS):
            answer = self.llm.chat(messages, self.schemas())
            if not answer["tool_calls"]:
                reply = answer["content"].strip() or NOT_FINISHED
                if not answer["content"].strip():
                    flags.append("empty_reply")
                break
            messages.append({"role": "assistant", "content": answer["content"], "tool_calls": [
                {"function": {"name": c["name"], "arguments": c["arguments"]}} for c in answer["tool_calls"]
            ]})
            for call in answer["tool_calls"]:
                name, arguments = call["name"], dict(call["arguments"])
                if name == KNOWLEDGE_TOOL:
                    question = str(arguments.get("question") or message)
                    result, rag_record = self.answer_question(question)
                    calls.append({"name": name, "arguments": {"question": question}, "result": {"answer": result.answer, "abstained": result.abstained}})
                    record["knowledge"] = rag_record
                    reply = result.answer
                    break
                if name == "book_site_survey":
                    arguments.pop(SESSION_ARGUMENT, None)
                    result = self.tools.call(name, {**arguments, SESSION_ARGUMENT: session.session_id})
                    if result.get("status") == "pending":
                        session.pending = result
                        booking = {k: result[k] for k in ("survey_id", "project_id", "survey_date", "status")}
                elif name in {schema["function"]["name"] for schema in self.schemas()}:
                    result = self.tools.call(name, arguments)
                else:
                    result = {"error": f"there is no tool called {name}"}
                calls.append({"name": name, "arguments": arguments, "result": result})
                messages.append({"role": "tool", "tool_name": name, "content": json.dumps(result, ensure_ascii=False)})
            if reply is not None:
                break
        else:
            reply = NOT_FINISHED
            flags.append("too_many_steps")

        problems = self.guard.problems(reply, session.customer_text() + "\n" + message)
        if problems:
            record["guard"] = problems
            record["blocked_reply"] = reply
            reply = BLOCKED
            flags = sorted({*flags, "output_blocked"})
        record["tool_calls"] = calls
        return Turn(reply, calls, flags, booking, record)

    def _confirm(self, session, record):
        result = self.confirm(session.session_id)
        session.pending = None
        record["confirmation"] = result
        if "error" in result:
            return Turn(NOT_FINISHED, [], ["confirmation_failed"], None, record)
        reply = f"Your site survey for project {result['project_id']} is booked for {result['survey_date']}."
        booking = {k: result[k] for k in ("survey_id", "project_id", "survey_date", "status")}
        return Turn(reply, [], ["confirmed_by_customer"], booking, record)

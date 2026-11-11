"""A stand-in for POST /chat, so the browser tests need no model, index or database.

    uvicorn tests.e2e.stub_api:app --port 8765

It answers from a script, keyed on words in the message, and builds every reply with the real
app.api.ChatRequest and ChatResponse models: a change to the /chat contract breaks these tests too.
"""

from fastapi import FastAPI, HTTPException

from app.api import ChatRequest, ChatResponse

app = FastAPI(title="stub /chat")
SESSION = "stub0session0id"
LONG = " ".join(f"Sentence {n} of a long answer about mounting systems." for n in range(1, 61))
WARRANTY_SOURCE = {"doc_id": "warranty", "heading_path": "Warranty > Warranty periods", "chunk_id": "warranty:0:aa"}


def reply(text, booking=None, sources=()):
    return ChatResponse(
        session_id=SESSION, reply=text, tool_calls=[], flags=[], booking=booking, sources=list(sources), total_ms=12.0
    )


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    message = request.message.lower()
    if "fail" in message:
        raise HTTPException(503, "service unavailable: Ollama is down")
    if message == "yes":
        booking = {"survey_id": 1, "project_id": "P-1008", "survey_date": "2026-11-12", "status": "confirmed"}
        return reply("Your site survey for project P-1008 is booked for 2026-11-12.", booking)
    if "book" in message:
        booking = {"survey_id": 1, "project_id": "P-1008", "survey_date": "2026-11-12", "status": "pending"}
        return reply('I can propose 2026-11-12 for P-1008. Please reply "yes" to confirm.', booking)
    if "long version" in message:  # not just "long": "How long is the warranty?" must get the warranty answer
        return reply(LONG)
    if "warranty" in message:
        return reply("Products have a 15-year warranty, and installation has a 5-year warranty.", sources=[WARRANTY_SOURCE])
    return reply("How can I help with your solar mounting project?")

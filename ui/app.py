"""The chat window (Stage 7): a Streamlit page in front of POST /chat.

    make ui                                   # http://localhost:8501, talks to API_URL (default http://127.0.0.1:8000)

It keeps the conversation's session id, so a site survey proposed in one message can be confirmed
by the customer's "yes" in the next. Each answer shows the passages it cited; a proposed survey is
shown as waiting for the customer's yes, a confirmed one as booked. API errors become a plain
message, never a stack trace. Parts the browser tests look for carry stable keys
(st-key-reply-N, st-key-sources-N, st-key-booking-N, st-key-error-N).
"""

import os

import httpx
import streamlit as st

API_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")
TIMEOUT_S = 180
MAX_CHARS = 1000  # the API's limit (app/api.py, MAX_QUESTION_CHARS)
UNAVAILABLE = "The assistant is unavailable right now. Please try again in a minute, or write to support@example.com."
TOO_LONG = f"Your message is too long. Please keep it under {MAX_CHARS} characters."


def ask(message, session_id):
    """(reply dict, error text): exactly one of them is set."""
    try:
        response = httpx.post(f"{API_URL}/chat", json={"message": message, "session_id": session_id}, timeout=TIMEOUT_S)
    except httpx.HTTPError:
        return None, UNAVAILABLE
    if response.status_code == 422:
        return None, TOO_LONG if len(message) > MAX_CHARS else "That message could not be read. Please try again."
    if response.status_code != 200:
        return None, UNAVAILABLE
    return response.json(), None


def show_answer(index, turn):
    with st.container(key=f"reply-{index}"):
        st.markdown(turn["reply"])
    booking = turn.get("booking")
    if booking:
        with st.container(key=f"booking-{index}"):
            if booking["status"] == "confirmed":
                st.success(f"Site survey booked: project {booking['project_id']} on {booking['survey_date']}.")
            else:
                st.info(
                    f"Proposed site survey: project {booking['project_id']} on {booking['survey_date']}. "
                    'It is not booked until you reply "yes".'
                )
    if turn.get("sources"):
        with st.container(key=f"sources-{index}"), st.expander(f"Sources ({len(turn['sources'])})"):
            for source in turn["sources"]:
                st.markdown(f"- **{source['doc_id']}**: {source['heading_path']}")


def main():
    st.set_page_config(page_title="Example Solar support", page_icon="☀️")
    st.title("Example Solar support")
    st.caption("Answers come from the company's documents. A site survey is booked only after you confirm it.")
    state = st.session_state
    state.setdefault("session_id", None)
    state.setdefault("turns", [])

    if st.button("New conversation", key="new"):
        state.session_id, state.turns = None, []

    for index, turn in enumerate(state.turns):
        with st.chat_message("user"):
            st.markdown(turn["message"])
        with st.chat_message("assistant"):
            if turn.get("error"):
                with st.container(key=f"error-{index}"):
                    st.error(turn["error"])
            else:
                show_answer(index, turn)

    message = st.chat_input("Ask about products, projects or site surveys", max_chars=MAX_CHARS)
    if message and message.strip():
        with st.spinner("Thinking..."):
            reply, error = ask(message.strip(), state.session_id)
        if reply:
            state.session_id = reply["session_id"]
            state.turns.append({"message": message.strip(), **reply})
        else:
            state.turns.append({"message": message.strip(), "error": error})
        st.rerun()


main()

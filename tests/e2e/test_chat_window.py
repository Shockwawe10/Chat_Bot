"""Browser tests of the chat window (ui/app.py) against the stand-in API: make e2e.

The roadmap's cases: happy path, empty input, long answer, API error, sources displayed; plus the
booking confirmation, the API being down, and a new conversation.
"""

import re

import pytest
from playwright.sync_api import Page, expect

pytestmark = pytest.mark.e2e
UNAVAILABLE = "The assistant is unavailable right now"


def send(page: Page, text: str):
    box = page.get_by_test_id("stChatInputTextArea")
    box.fill(text)
    box.press("Enter")


def open_chat(page: Page, url: str):
    page.goto(url)
    expect(page.get_by_role("heading", name="Sunny, your solar helper")).to_be_visible(timeout=30_000)


def test_happy_path_shows_the_question_and_the_answer(page: Page, chat_url):
    open_chat(page, chat_url)
    send(page, "How long is the warranty?")
    expect(page.locator(".st-key-reply-0")).to_contain_text("15-year warranty", timeout=30_000)
    expect(page.get_by_test_id("stChatMessage").first).to_contain_text("How long is the warranty?")


def test_the_question_shows_at_once_while_the_answer_is_on_its_way(page: Page, chat_url):
    open_chat(page, chat_url)
    send(page, "Please answer slowly")
    expect(page.get_by_test_id("stChatMessage").first).to_contain_text("Please answer slowly", timeout=2_000)
    expect(page.locator(".st-key-reply-0")).to_have_count(0)
    expect(page.locator(".st-key-reply-0")).to_contain_text("Here is the slow answer.", timeout=30_000)
    expect(page.get_by_test_id("stChatMessage").first).to_contain_text("Please answer slowly")


def test_sources_are_displayed_under_the_answer(page: Page, chat_url):
    open_chat(page, chat_url)
    send(page, "Tell me about the warranty")
    sources = page.locator(".st-key-sources-0")
    expect(sources).to_contain_text("Sources (1)", timeout=30_000)
    sources.get_by_text("Sources (1)").click()
    expect(sources).to_contain_text("Warranty > Warranty periods")


def test_an_answer_without_sources_shows_no_sources_box(page: Page, chat_url):
    open_chat(page, chat_url)
    send(page, "Hello")
    expect(page.locator(".st-key-reply-0")).to_be_visible(timeout=30_000)
    expect(page.locator(".st-key-sources-0")).to_have_count(0)


def test_empty_input_sends_nothing(page: Page, chat_url):
    open_chat(page, chat_url)
    box = page.get_by_test_id("stChatInputTextArea")
    box.fill("   ")
    box.press("Enter")
    page.wait_for_timeout(1500)
    expect(page.get_by_test_id("stChatMessage")).to_have_count(0)


def test_a_long_answer_is_shown_in_full(page: Page, chat_url):
    open_chat(page, chat_url)
    send(page, "Give me the long version")
    reply = page.locator(".st-key-reply-0")
    expect(reply).to_contain_text("Sentence 1 of a long answer", timeout=30_000)
    expect(reply).to_contain_text("Sentence 60 of a long answer")


def test_an_api_error_becomes_a_plain_message(page: Page, chat_url):
    open_chat(page, chat_url)
    send(page, "Please fail now")
    error = page.locator(".st-key-error-0")
    expect(error).to_contain_text(UNAVAILABLE, timeout=30_000)
    expect(page.locator("body")).not_to_contain_text("Traceback")
    expect(page.locator("body")).not_to_contain_text("Ollama is down")


def test_an_api_that_is_down_becomes_the_same_plain_message(page: Page, chat_url_without_api):
    open_chat(page, chat_url_without_api)
    send(page, "Hello?")
    expect(page.locator(".st-key-error-0")).to_contain_text(UNAVAILABLE, timeout=30_000)


def test_a_booking_waits_for_yes_and_then_shows_as_booked(page: Page, chat_url):
    open_chat(page, chat_url)
    send(page, "Can you book a site survey for P-1008?")
    proposed = page.locator(".st-key-booking-0")
    expect(proposed).to_contain_text('It is not booked until you reply "yes"', timeout=30_000)
    send(page, "yes")
    expect(page.locator(".st-key-booking-1")).to_contain_text("Site survey booked: project P-1008 on 2026-11-12", timeout=30_000)


def test_new_conversation_clears_the_chat(page: Page, chat_url):
    open_chat(page, chat_url)
    send(page, "Hello")
    expect(page.locator(".st-key-reply-0")).to_be_visible(timeout=30_000)
    page.get_by_role("button", name=re.compile("New conversation")).click()
    expect(page.get_by_test_id("stChatMessage")).to_have_count(0, timeout=15_000)

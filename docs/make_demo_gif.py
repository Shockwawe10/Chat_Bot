"""Record the README's demo GIF from the running Docker demo: python docs/make_demo_gif.py

    make docker-up                      # first: the demo on http://127.0.0.1:8501
    python docs/make_demo_gif.py        # writes docs/demo.gif

Playwright opens the chat window, types a product question and a project-status question, and
takes screenshots as it goes. The wait for each answer (10 to 30 s on the 4 GB GPU) is cut to a
short "Thinking..." frame; the answers themselves are real and unedited. Pillow (installed with
streamlit, pinned in requirements.txt because this script imports it) builds the GIF.
"""

import io
import sys
import time
from pathlib import Path

from PIL import Image
from playwright.sync_api import expect, sync_playwright

URL = "http://127.0.0.1:8501"
OUT = Path(__file__).resolve().parent / "demo.gif"
QUESTIONS = ["Which fasteners does RF-2 use, and why those?", "What is the status of project P-1001?"]
VIEWPORT = {"width": 900, "height": 760}
WIDTH = 720  # the GIF's width; height keeps the viewport's ratio
TYPE_DELAY_MS = 35
FRAME_EVERY_CHARS = 4


class Recorder:
    """Screenshots with how long each one shows in the GIF, in milliseconds."""

    def __init__(self, page):
        self.page, self.frames = page, []

    def shot(self, show_ms):
        self.frames.append((self.page.screenshot(), show_ms))


def type_visibly(page, recorder, text):
    box = page.get_by_test_id("stChatInputTextArea")
    box.click()
    for start in range(0, len(text), FRAME_EVERY_CHARS):
        box.press_sequentially(text[start:start + FRAME_EVERY_CHARS], delay=TYPE_DELAY_MS)
        recorder.shot(90)
    recorder.shot(400)
    box.press("Enter")


def wait_for_reply(page, recorder, index):
    reply = page.locator(f".st-key-reply-{index}")
    page.wait_for_timeout(600)
    recorder.shot(1200)  # the question sent, the assistant working
    start = time.time()
    expect(reply).to_be_visible(timeout=300_000)
    page.wait_for_timeout(500)
    print(f"answer {index + 1} took {time.time() - start:.1f} s (shown as about 1 s in the GIF)")
    return reply


def record():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport=VIEWPORT)
        page.goto(URL)
        expect(page.get_by_role("heading", name="Example Solar support")).to_be_visible(timeout=60_000)
        recorder = Recorder(page)
        recorder.shot(1500)

        type_visibly(page, recorder, QUESTIONS[0])
        wait_for_reply(page, recorder, 0)
        recorder.shot(2500)
        sources = page.locator(".st-key-sources-0")
        if sources.count():
            sources.get_by_text("Sources", exact=False).first.click()
            page.wait_for_timeout(600)
            recorder.shot(3500)

        type_visibly(page, recorder, QUESTIONS[1])
        wait_for_reply(page, recorder, 1)
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(400)
        recorder.shot(4500)
        browser.close()
    return recorder.frames


def build_gif(frames, out=OUT):
    images, durations = [], []
    for png, show_ms in frames:
        image = Image.open(io.BytesIO(png)).convert("RGB")
        image = image.resize((WIDTH, round(image.height * WIDTH / image.width)), Image.LANCZOS)
        images.append(image.quantize(colors=128, method=Image.Quantize.MEDIANCUT))
        durations.append(show_ms)
    images[0].save(out, save_all=True, append_images=images[1:], duration=durations, loop=0, optimize=True)
    return out


def main():
    frames = record()
    out = build_gif(frames, Path(sys.argv[1]) if len(sys.argv) > 1 else OUT)
    seconds = sum(ms for _, ms in frames) / 1000
    print(f"wrote {out}: {len(frames)} frames, {seconds:.1f} s, {out.stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()

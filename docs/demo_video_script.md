# Demo video: shot list and narration

A 3 to 5 minute screen recording for the README (Stage 8). It shows a question in the chat window, an eval run and a red CI after a bad change, plus the browser tests. Every chat scene below was tried on the Docker demo on 2026-11-11 and gave the answer shown.

## Before recording (not filmed)

1. Start Docker Desktop and the desktop Ollama, then in Git Bash: `make docker-up`. Restart it right before recording (`make docker-down`, then `make docker-up`) so the demo data is fresh: a survey booked in a rehearsal stays booked until a restart.
2. Warm the models up: ask the chat window one question and wait for the answer, so the first filmed answer is not slowed by loading.
3. Open these, each in its own tab or window:
   - the README on GitHub (top of the page, with the GIF)
   - the chat window: http://127.0.0.1:8501
   - the canary pull request: https://github.com/Shockwawe10/Chat_Bot/pull/7, on its Checks tab
   - a Git Bash terminal in the project folder, with a large font (Ctrl and + a few times)
4. Recording: Windows Game Bar (Win+Alt+R to start and stop) or OBS. Close notifications (Focus assist on). Use a headset microphone if you have one.
5. Answers take 10 to 30 seconds. Keep talking during the wait, or cut the wait out when editing.

## Scenes (about 4 minutes)

### 1. What this is (20 s)

**Show:** the README top with the GIF.

**Say:** "This is a support chatbot for a made-up solar mounting company. The chatbot is simple on purpose. The project is about testing it: measuring its answers, attacking it, and stopping bad changes in CI. Everything runs on my laptop, on a 4 GB GPU."

### 2. The chat window (75 s)

**Show:** the chat window. Type each message, press Enter.

1. `Which fasteners does RF-2 use, and why those?`
   Expected: stainless steel A4 fasteners, because RF-2 is rated for corrosivity category C4. Open **Sources (3)**.
   **Say:** "Every answer comes from the company's documents, and it shows which ones. Each sentence is checked against those documents by a second model before it goes out."
2. `Please book a site survey for project P-1008 on 2026-11-16.`
   Expected: "A site survey is proposed … Please reply "yes" to confirm", and a blue box: proposed, not booked.
3. `yes`
   Expected: "Your site survey for project P-1008 is booked for 2026-11-16", and the box turns green.
   **Say:** "The agent uses tools on a small company database. It can only propose a booking. Only the customer's own 'yes' confirms it, and that step is in code the model cannot call."
4. `What is the email address of the contact for project P-1001?`
   Expected: a refusal, no contact details.
   **Say:** "It never gives out another customer's details. The agent is tested with 22 attacks, including this kind, and none of them works."

### 3. An eval run (60 s)

**Show:** the terminal.

```bash
make eval-smoke
```

It runs 21 questions and takes about 5 minutes. Film the start, pause the recording, and resume when the summary prints (`errors: 0`, the behaviour lines, `written: reports/runs/...json`).

**Say:** "This is the smoke eval: 21 questions from a golden dataset, each answer scored by code. Refusals, numbers, out-of-scope questions. The committed run is checked by CI on every push, case by case, against an accepted reference. If one answer gets worse, the build fails."

### 4. A red CI after a bad change (45 s)

**Show:** pull request #7, Checks tab, the failed run and the failing step.

**Say:** "To prove the gates work, I opened a pull request with a deliberately broken prompt. CI failed, exactly on the gates I predicted. It also showed two weaknesses in my own tests, which are fixed now and listed in the README's Findings."

### 5. The browser tests (30 s)

**Show:** the terminal, then the browser windows that open.

```bash
python -m pytest tests/e2e -m e2e --headed --slowmo 400
```

**Say:** "And the chat window has its own tests. Playwright opens a real browser and uses the window like a person would: ten tests, against a stand-in API, on every push."

### 6. Close (20 s)

**Show:** the README, scroll to Findings.

**Say:** "The README lists what I found along the way, including one defect that is still open. The full write-up of each stage is in the repository. Thanks for watching."

## After recording

- Trim the waits and keep it under 5 minutes.
- Upload it (YouTube "Unlisted" works) and send me the link. I'll add it to the README and tick the roadmap item.
- Before uploading, check the recording shows nothing private: browser bookmarks, other tabs, notifications, your desktop or file paths you do not want public.

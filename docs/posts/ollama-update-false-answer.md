*Draft by Claude Code, for me to edit before publishing. Every number is from `reports/drift.md` and the saved runs it names.*

# A runtime update made my chatbot say something false, and every test passed

I'm building a small RAG support chatbot as a QA portfolio project. The chatbot is simple on purpose; the point is the testing around it: a golden dataset, a fact-checker on every answer, and CI gates that fail the build when quality drops.

Between two evaluation runs a day apart, I changed nothing. Same code, same prompt, same index, same settings. Even the models were pinned by digest, so the weights could not change.

4 of the 52 answers changed anyway.

Three were harmless rewordings. The fourth was not. The question was about corrosion categories. The night before, the bot had refused it: the fact-checker had blocked an incomplete answer. The next day it answered that the company's systems are rated for "C1 to C5 and CX". The knowledge base says the opposite: "The company does not offer any system for category CX."

**What changed was the runtime.** Ollama, which serves the models, had updated itself from 0.40.14 to 0.40.15. I found it only because every run records the Ollama version in its manifest.

**Why nothing caught it:**

- **The fact-checker missed the "not".** It's a small model (bespoke-minicheck, 7B) that checks each sentence against the retrieved passages. The passages contain "CX" and the same words around it, and it said "Yes".
- **The gates measure rates and required facts, not every sentence.** This question has no required number or keyword, so no gate looked at it. Over-refusal, out-of-scope answers, numeric fidelity and citations all passed.
- **One metric even improved.** Refusal accuracy went from 0.75 to 0.77, because a question that should be answered was now answered. Wrongly.

**What I changed:**

- **The runtime is now pinned like the models.** A run that CI checks refuses to start on any Ollama version except the pinned one, and CI refuses a committed run made on another. An update now has to be installed on purpose, measured as an experiment, and adopted only if the answers hold.
- **I wrote it down as an open defect, not a fixed one.** The pinned version is 0.40.15, the one that produced the false answer, and the fact-checker's blind spot for negation is still there. Pinning didn't make the answer right. It made changes visible and deliberate.

**What I took from it:**

1. In an LLM system, the program that runs the model is part of the model. Pin it and record it.
2. A metric can improve while an answer gets worse. Read the answers that changed, not only the scores.
3. A checker trained to spot unsupported sentences can still be fooled by a reversed "not", when the passages contain the same words.

The project, with the run files and the write-up: https://github.com/Shockwawe10/Chat_Bot

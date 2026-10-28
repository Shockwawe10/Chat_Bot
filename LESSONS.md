# Lessons

Written by /aar-loop after each session's After Action Review. Read this file before starting a new task in this project. Every entry should be concrete and checkable, never vague.

## 2026-10-28 -- Plain 'qwen3:4b' on Ollama is the thinking variant (same ID 359d7dd4bcda as 'qwen3:4b-thinking-2507-q4_K_M'); use 'qwen3:4b-instruct' (ID 0edcdef34593) for direct answers. Before recommending an Ollama tag, compare its ID on ollama.com/library/<model>/tags against the -thinking and -instruct tags, then send one real prompt.
- Expected: qwen3:4b with think=false would answer in about 1 second with no reasoning text.
- Actual: It wrote about 550 words of reasoning before 'Question 1: C5', took about 30 s, and the reasoning text came back inside the answer.
- Why: think=false is ignored by the thinking-only 2507 weights behind the plain tag. I recommended the tag from the model page, which did not say how to disable thinking, without checking.
- tags: ollama,models,fix-applied

## 2026-10-28 -- A model's download size is not its GPU footprint: run 'ollama ps' after the first call and report the CPU/GPU split before saying a model fits. qwen3:4b-instruct is 2.5 GB on disk but loaded as 3.5 GB at 4096 context and ran 34%/66% CPU/GPU on a 4 GB RTX 3050 Ti.
- Expected: A 2.5 GB model fits fully inside 4 GB of GPU memory.
- Actual: ollama ps showed 34% of the model on the CPU; speed was still about 24 tokens/s.
- Why: The runtime adds KV cache for the context window, and other programs already used part of the 4 GB (562 MiB in use at idle).
- tags: ollama,gpu,fix-applied

## 2026-10-28 -- For long multi-file content use the Write tool, not one Bash heredoc batch; when a batch fails with a shell parse error, 'ls' the target folder before retrying to see what exists. A heredoc batch of 7 product files failed with 'unexpected EOF while looking for matching quote' (cause not diagnosed).
- Expected: 7 product files written by one Bash command, like the previous batch of 12.
- Actual: The shell rejected the whole command at parse time and wrote none of the 7 files; the 12 files from the earlier batch were intact.
- Why: Parse errors abort the command before any line runs. I did not find the offending character, so the next attempt used 7 separate Write calls instead.
- tags: bash,files,logged-only

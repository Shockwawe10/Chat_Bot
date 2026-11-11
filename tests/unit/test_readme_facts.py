"""The README's settings, models and Quick start match .env.example.

In Stage 8 the README was found to have drifted for several stages: the Configuration table had
the old judge, TOP_K 5 and prompt v2, Quick start pulled phi4-mini instead of bespoke-minicheck,
and the Local models table still named phi4-mini as the judge (LESSONS.md, 2026-11-11). Nothing
read the README. These tests do: a change to .env.example now fails make test until the README
says the same.
"""

import re

import pytest
from dotenv import dotenv_values

from app.settings import ROOT

ENV = dotenv_values(ROOT / ".env.example")
README = (ROOT / "README.md").read_bytes().decode("utf-8").replace("\r\n", "\n")


def section(text, heading):
    """The lines under a heading, up to the next heading of the same or a higher level.

    Lines inside ``` code blocks are never headings: a shell comment such as "# Stage 0" is not.
    """
    lines = text.split("\n")
    level = len(heading.split(" ")[0])
    start = lines.index(heading) + 1
    in_code, body = False, []
    for line in lines[start:]:
        if line.startswith("```"):
            in_code = not in_code
        elif not in_code and re.match(rf"#{{1,{level}}} ", line):
            break
        body.append(line)
    return "\n".join(body)


def table_rows(text):
    return [[cell.strip() for cell in line.strip("|").split("|")] for line in text.splitlines()
            if line.startswith("| ") and not line.startswith("| ---")]


def config_values(text):
    """{setting: example value} from the README's Configuration table; digests have no example."""
    values = {}
    for cells in table_rows(section(text, "## Configuration")):
        keys = re.findall(r"`([A-Z_]+)`", cells[0])
        examples = re.findall(r"`([^`]+)`", cells[1])
        named = [key for key in keys if not key.endswith("_DIGEST")]
        values.update({key: None for key in keys if key.endswith("_DIGEST")})
        values.update({key: examples[i] if i < len(examples) else "" for i, key in enumerate(named)})
    return values


def pulled_models(text):
    return set(re.findall(r"^ollama pull (\S+)", section(text, "## Quick start"), re.MULTILINE))


def model_for(text, heading, marker):
    """The model in the first column-2 code span of the row of `heading`'s table that mentions `marker`."""
    for cells in table_rows(section(text, heading)):
        if marker in " ".join(cells):
            return re.findall(r"`([^`]+)`", cells[1])[0]
    raise AssertionError(f"no row mentioning {marker} under {heading}")


def drift(text):
    """Every way the README disagrees with .env.example, as readable lines."""
    problems = []
    table = config_values(text)
    for key, value in ENV.items():
        if key not in table:
            problems.append(f"Configuration table has no row for {key}")
        elif not key.endswith("_DIGEST") and table[key] != (value or ""):
            problems.append(f"Configuration table says {key} = {table[key]!r}, .env.example says {value!r}")
    wanted = {ENV["LLM_MODEL"], ENV["ANSWER_CHECK_MODEL"], ENV["JUDGE_MODEL"], ENV["EMBEDDING_MODEL"]}
    if pulled_models(text) != wanted:
        problems.append(f"Quick start pulls {sorted(pulled_models(text))}, the app uses {sorted(wanted)}")
    checks = [
        ("### Models", "app/generator.py", "LLM_MODEL"),
        ("### Models", "app/agent.py", "LLM_MODEL"),
        ("### Models", "app/embedder.py", "EMBEDDING_MODEL"),
        ("### Models", "app/checker.py", "ANSWER_CHECK_MODEL"),
        ("### Models", "evals/judge.py", "JUDGE_MODEL"),
        ("### Local models", "Chatbot", "LLM_MODEL"),
        ("### Local models", "Answer check and judge", "JUDGE_MODEL"),
        ("### Local models", "Embeddings", "EMBEDDING_MODEL"),
    ]
    for heading, marker, key in checks:
        try:
            model = model_for(text, heading, marker)
        except (AssertionError, ValueError, IndexError) as error:
            problems.append(f"{heading}: {error}")
            continue
        if model != ENV[key]:
            problems.append(f"{heading} row '{marker}' names {model}, .env.example's {key} is {ENV[key]}")
    return problems


def test_the_readme_says_what_env_example_says():
    assert drift(README) == []


@pytest.mark.parametrize(
    "old, new, expected",
    [
        ("`CHUNK_MIN`, `TOP_K` |", "`CHUNK_MIN` |", "no row for TOP_K"),
        ("`500`, `800`, `100`, `8`", "`500`, `800`, `100`, `5`", "TOP_K = '5'"),
        ("ollama pull bespoke-minicheck:7b", "ollama pull phi4-mini:3.8b", "Quick start pulls"),
        ("| Answer check and judge | `bespoke-minicheck:7b`", "| Answer check and judge | `phi4-mini:3.8b`", "Local models row"),
        ("```bash\nollama pull", "```bash\n# the models\nollama pull", None),
    ],
)
def test_each_kind_of_drift_found_in_stage_8_fails(old, new, expected):
    """And a shell comment in a code block is not taken for a heading (expected None: no drift)."""
    assert old in README
    problems = drift(README.replace(old, new, 1))
    if expected is None:
        assert problems == []
    else:
        assert any(expected in problem for problem in problems)

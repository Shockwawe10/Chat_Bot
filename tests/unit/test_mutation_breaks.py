"""Every break in evals/mutation_check.py still finds its text in the current code.

A break whose text no longer matches stops the whole mutation check, but a run with --only skips
it. On 2026-11-10 four breaks had gone stale unnoticed, one of them since Stage 5, because code
they target was reformatted or moved. This test fails on the day a break goes stale, in make test.
"""

import pytest

from evals.mutation_check import BREAKS


def file_text(path):
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


@pytest.mark.parametrize("name", sorted(BREAKS))
def test_the_break_still_matches_its_file(name):
    for path, old, new in BREAKS[name]:
        assert old != new, f"{name}: the break changes nothing"
        assert old in file_text(path), f"{name}: its text is no longer in {path.name}; update the break to the current code"

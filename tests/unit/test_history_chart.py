"""The metric history chart (evals/history_chart.py): a true picture of evals/history.csv."""

import re

from evals import history_chart
from evals.history_chart import CHART, HISTORY, PANELS, changes, read_history, render
from evals.run_evals import write_outputs


def row(run_id, **values):
    base = {"run_id": run_id, "timestamp": "2026-11-0" + run_id[-1] + "T10:00:00+00:00", "prompt_version": "v5", "top_k": "8"}
    return {**base, **values}


def test_the_committed_chart_is_drawn_from_the_committed_history():
    """CI fails when one changes without the other: run python -m evals.history_chart."""
    committed = CHART.read_bytes().replace(b"\r\n", b"\n").decode("utf-8")
    assert committed == render(read_history(HISTORY))


def test_every_run_is_one_point_in_every_panel_with_its_value_in_the_hover_text():
    rows = [row("r1", hit_rate="0.5", latency_p95_ms="4642.9"), row("r2", hit_rate="0.95", latency_p95_ms="27651.6")]
    svg = render(rows)
    assert svg.count("<circle") == 2 * len([p for p in PANELS if p[0] in ("hit_rate", "latency_p95_ms")])
    assert "Run 1 (r1): Hit rate 0.50" in svg and "Run 2 (r2): Hit rate 0.95" in svg
    assert "Run 2 (r2): Latency p95 27.7 s" in svg


def test_a_point_sits_at_its_value_on_the_shared_rate_scale():
    """0.5 is half way up, even when it is the highest value: rates are never stretched to fill the panel."""
    svg = render([row("r1", hit_rate="0.0"), row("r2", hit_rate="0.5")])
    zero, half = [float(y) for y in re.findall(r'<circle class="dot" cx="[\d.]+" cy="([\d.]+)"', svg)][:2]
    assert zero - half == (history_chart.PANEL_H - history_chart.TOP - history_chart.BOTTOM) / 2


def test_a_missing_value_is_left_out_not_drawn_as_zero():
    svg = render([row("r1", hit_rate="0.8"), row("r2", hit_rate="")])
    assert "Run 2 (r2): Hit rate" not in svg and "Run 1 (r1): Hit rate 0.80" in svg


def test_a_setup_change_is_marked_and_named():
    rows = [row("r1", prompt_version="v2", top_k="5"), row("r2"), row("r3")]
    assert changes(rows) == {1: "prompt v2→v5, top-k 5→8"}
    svg = render(rows)
    assert svg.count('class="rule"') == len(PANELS)
    assert "before run 2: prompt v2→v5, top-k 5→8" in svg


def test_the_real_history_marks_the_stage_3_setup():
    assert changes(read_history(HISTORY)).get(2) == "prompt v2→v5, top-k 5→8"


def test_a_full_dev_run_redraws_the_chart_and_an_experiment_does_not(tmp_path):
    report = {
        "run_id": "r1", "system": "pipeline", "split": "dev", "smoke": False, "experiment": "",
        "metrics": {"hit_rate": 0.9, "latency_p95_ms": 1000.0},
    }
    write_outputs({**report, "experiment": "x", "run_id": "e1"}, [], tmp_path, tmp_path / "history.csv")
    assert not (tmp_path / "history.svg").exists()
    write_outputs(report, [], tmp_path, tmp_path / "history.csv")
    assert "Run 1 (r1): Hit rate 0.90" in (tmp_path / "history.svg").read_text(encoding="utf-8")

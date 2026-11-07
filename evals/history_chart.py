"""Draw evals/history.csv as reports/history.svg: one small panel per metric, one point per full dev run.

Run from the repository root: python -m evals.history_chart
run_evals redraws it after every full dev run, and CI checks that the committed chart matches
the committed history (tests/unit/test_history_chart.py). No plotting package: the SVG is
written by hand, so the chart adds no dependency.

The chart is a picture of the CSV, which stays the table view. A dashed line marks the runs
where the prompt, model, top-k, chunk size or embedding model changed, so a jump is not read as drift.
"""

import csv
import sys
from html import escape

from app.settings import ROOT

HISTORY = ROOT / "evals" / "history.csv"
CHART = ROOT / "reports" / "history.svg"

# (column, title, note, scale): rates share the 0 to 1 scale; latency gets its own panel.
PANELS = [
    ("hit_rate", "Hit rate", "gold passage among the retrieved", "rate"),
    ("over_refusal_rate", "Over-refusal", "lower is better", "rate"),
    ("numeric_fidelity", "Numeric fidelity", "required numbers in the answer", "rate"),
    ("refusal_accuracy", "Refusal accuracy", "refused exactly when it should", "rate"),
    ("behaviour_accuracy", "Behaviour accuracy", "did what the case expects", "rate"),
    ("latency_p95_ms", "Latency p95", "seconds; depends on the machine", "seconds"),
]
CHANGES = [("prompt_version", "prompt"), ("llm_model", "model"), ("top_k", "top-k"), ("chunk_size", "chunk"), ("embedding_model", "embedding")]

COLUMNS, PANEL_W, PANEL_H, HEADER, FOOTER = 3, 300, 190, 56, 30
LEFT, RIGHT, TOP, BOTTOM = 40, 46, 44, 30

STYLE = """
  .surface { fill: #fcfcfb; }
  .title { fill: #0b0b0b; font: 600 13px system-ui, -apple-system, "Segoe UI", sans-serif; }
  .note, .tick, .value, .change { font: 11px system-ui, -apple-system, "Segoe UI", sans-serif; }
  .note { fill: #52514e; }
  .tick { fill: #898781; font-variant-numeric: tabular-nums; }
  .value { fill: #0b0b0b; font-variant-numeric: tabular-nums; }
  .change { fill: #52514e; }
  .grid { stroke: #e1e0d9; stroke-width: 1; }
  .axis { stroke: #c3c2b7; stroke-width: 1; }
  .rule { stroke: #898781; stroke-width: 1; stroke-dasharray: 3 3; }
  .line { fill: none; stroke: #2a78d6; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
  .dot { fill: #2a78d6; stroke: #fcfcfb; stroke-width: 2; }
  @media (prefers-color-scheme: dark) {
    .surface { fill: #1a1a19; }
    .title, .value { fill: #f0efec; }
    .note, .change { fill: #c3c2b7; }
    .grid { stroke: #2c2c2a; }
    .axis { stroke: #383835; }
    .line { stroke: #3987e5; }
    .dot { fill: #3987e5; stroke: #1a1a19; }
  }
"""


def read_history(path=HISTORY):
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def value(row, column):
    text = row.get(column) or ""
    if not text:
        return None
    number = float(text)
    return number / 1000 if column == "latency_p95_ms" else number


def changes(rows):
    """{run index: "prompt v2→v5, top-k 5→8"} for each run whose setup differs from the run before."""
    found = {}
    for i in range(1, len(rows)):
        parts = [
            f"{label} {rows[i - 1][column]}→{rows[i][column]}"
            for column, label in CHANGES
            if rows[i - 1].get(column) != rows[i].get(column)
        ]
        if parts:
            found[i] = ", ".join(parts)
    return found


def fmt(number, scale):
    return f"{number:.1f} s" if scale == "seconds" else f"{number:.2f}"


def panel(rows, column, title, note, scale, x0, y0, changed):
    values = [value(row, column) for row in rows]
    known = [v for v in values if v is not None]
    top = 1.0 if scale == "rate" else max(10.0, -(-max(known, default=0) // 10) * 10)
    width, height = PANEL_W - LEFT - RIGHT, PANEL_H - TOP - BOTTOM
    left, base = x0 + LEFT, y0 + TOP + height

    def x(i):
        return left + (width * i / (len(rows) - 1) if len(rows) > 1 else width / 2)

    def y(v):
        return base - height * v / top

    out = [
        f'<text class="title" x="{x0 + 8}" y="{y0 + 18}">{escape(title)}</text>',
        f'<text class="note" x="{x0 + 8}" y="{y0 + 33}">{escape(note)}</text>',
    ]
    for tick in (0, top / 2, top):
        label = f"{tick:.0f}" if scale == "seconds" else f"{tick:g}"
        out.append(f'<line class="{"axis" if tick == 0 else "grid"}" x1="{left}" x2="{left + width}" y1="{y(tick):.1f}" y2="{y(tick):.1f}"/>')
        out.append(f'<text class="tick" x="{left - 6}" y="{y(tick) + 4:.1f}" text-anchor="end">{label}</text>')
    for i, row in enumerate(rows):
        out.append(f'<text class="tick" x="{x(i):.1f}" y="{base + 16}" text-anchor="middle">{i + 1}</text>')
    for i in changed:
        middle = (x(i - 1) + x(i)) / 2
        out.append(f'<line class="rule" x1="{middle:.1f}" x2="{middle:.1f}" y1="{y0 + TOP - 4}" y2="{base}"/>')
    points = [(x(i), y(v)) for i, v in enumerate(values) if v is not None]
    if len(points) > 1:
        out.append('<polyline class="line" points="' + " ".join(f"{px:.1f},{py:.1f}" for px, py in points) + '"/>')
    for i, v in enumerate(values):
        if v is None:
            continue
        tip = f"Run {i + 1} ({rows[i]['run_id']}): {title} {fmt(v, scale)}"
        out.append(f'<circle class="dot" cx="{x(i):.1f}" cy="{y(v):.1f}" r="4"><title>{escape(tip)}</title></circle>')
    labelled = [i for i, v in enumerate(values) if v is not None]
    for i in sorted({labelled[0], labelled[-1]}) if labelled else ():
        # The last value to the right of its point, the first above its point (clear of the y ticks).
        dx, dy = (8, 4) if i == labelled[-1] else (2, -10)
        out.append(
            f'<text class="value" x="{x(i) + dx:.1f}" y="{y(values[i]) + dy:.1f}">{fmt(values[i], scale)}</text>'
        )
    return out


def render(rows):
    """The chart as SVG text. Same history, same bytes."""
    changed = changes(rows)
    panel_rows = -(-len(PANELS) // COLUMNS)
    width = COLUMNS * PANEL_W
    height = HEADER + panel_rows * PANEL_H + FOOTER
    first = rows[0]["timestamp"][:10] if rows else ""
    last = rows[-1]["timestamp"][:10] if rows else ""
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="t d">',
        '<title id="t">Eval history</title>',
        f'<desc id="d">Metrics of {len(rows)} full dev runs from {first} to {last}, from evals/history.csv.</desc>',
        f"<style>{STYLE}</style>",
        f'<rect class="surface" width="{width}" height="{height}" rx="8"/>',
        f'<text class="title" x="8" y="22">Full dev runs, {first} to {last} ({len(rows)} runs, x axis: run number)</text>',
    ]
    notes = [f"before run {i + 1}: {text}" for i, text in changed.items()]
    out.append(
        f'<text class="change" x="8" y="40">Dashed line = the setup changed{": " + "; ".join(notes) if notes else ""}</text>'
    )
    for n, (column, title, note, scale) in enumerate(PANELS):
        x0 = (n % COLUMNS) * PANEL_W
        y0 = HEADER + (n // COLUMNS) * PANEL_H
        out.extend(panel(rows, column, title, note, scale, x0, y0, changed))
    out.append(f'<text class="note" x="8" y="{height - 10}">Source: evals/history.csv. Hover a point for its run id.</text>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def write(history=HISTORY, chart=CHART):
    chart.parent.mkdir(parents=True, exist_ok=True)
    chart.write_text(render(read_history(history)), encoding="utf-8", newline="\n")
    return chart


def main():
    path = write()
    print(f"written: {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

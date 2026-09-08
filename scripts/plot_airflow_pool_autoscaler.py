#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sweeplib.plot_style import (  # noqa: E402
    LINE_COLOR_PRIMARY,
    LINE_COLOR_SECONDARY,
    apply_plot_fontsizes,
    configure_headless_matplotlib,
    single_column_figure_size,
)


def load_events(path: Path) -> list[dict[str, Any]]:
    events = []
    for line_number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        event = json.loads(raw)
        if not isinstance(event, dict):
            raise ValueError(f"Expected JSON object at {path}:{line_number}")
        events.append(event)
    if not events:
        raise ValueError(f"No autoscaler events found in {path}")
    return events


def plot_events(events_path: Path, output_path: Path) -> Path:
    events = load_events(events_path)
    elapsed_minutes = [float(event["elapsed_seconds"]) / 60.0 for event in events]
    pool_slots = [int(event.get("next_pool_slots", event["pool_slots"])) for event in events]
    completion_percent = []
    for event in events:
        total = int(event.get("total_batches", 0))
        succeeded = int(event.get("succeeded_batches", 0))
        completion_percent.append(100.0 * succeeded / total if total > 0 else 0.0)

    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_plot_fontsizes(plt=plt)
    fig, progress_ax = plt.subplots(figsize=single_column_figure_size())
    pool_ax = progress_ax.twinx()
    progress_ax.plot(
        elapsed_minutes,
        completion_percent,
        color=LINE_COLOR_PRIMARY,
        marker="o",
        label="Completed batches",
    )
    pool_ax.step(
        elapsed_minutes,
        pool_slots,
        where="post",
        color=LINE_COLOR_SECONDARY,
        label="Pool slots",
    )
    for x, event in zip(elapsed_minutes, events, strict=True):
        if event.get("decision") == "scale":
            progress_ax.axvline(x, color=LINE_COLOR_SECONDARY, alpha=0.25, linewidth=0.8)

    progress_ax.set_xlabel("Elapsed time [min]")
    progress_ax.set_ylabel("Completed batches [%]", color=LINE_COLOR_PRIMARY)
    pool_ax.set_ylabel("Airflow pool slots", color=LINE_COLOR_SECONDARY)
    progress_ax.set_ylim(0.0, 100.0)
    pool_ax.set_ylim(bottom=0.0)
    progress_ax.grid(True, alpha=0.3)
    fig.tight_layout()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Plot an Airflow pool autoscaler timeline.")
    parser.add_argument("--events-jsonl", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()
    events_path = args.events_jsonl.resolve()
    output_path = args.output.resolve() if args.output else events_path.with_name("autoscaler_timeline.pdf")
    print(plot_events(events_path, output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

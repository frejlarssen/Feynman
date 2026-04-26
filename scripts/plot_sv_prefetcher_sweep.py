#!/usr/bin/env python3
"""Plot parameter sweeps from scripts/run_sv_prefetcher_sweep.py summary.csv."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from sweeplib.plotting import (
    default_plot_output_path,
    load_xy_from_summary,
    render_sweep_plot,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot sweep results produced by run_sv_prefetcher_sweep.py"
    )
    parser.add_argument("--summary-csv", required=True, help="Path to summary.csv")
    parser.add_argument("--y-column", default="total_full_s")
    parser.add_argument("--mode", choices=["scatter", "meanstd"], default="meanstd")
    parser.add_argument("--include-failures", action="store_true")
    parser.add_argument("--output", default="", help="PNG path. Default: next to summary.csv")
    parser.add_argument("--title", default="", help="Optional plot title.")
    return parser.parse_args()


def infer_vary_label(summary_path: Path) -> str:
    metadata_path = summary_path.parent / "sweep_metadata.json"
    if not metadata_path.exists():
        return "varied_value"
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "varied_value"
    vary = payload.get("config", {}).get("vary", "")
    return vary if isinstance(vary, str) and vary else "varied_value"


def main() -> int:
    args = parse_args()
    summary_path = Path(args.summary_csv).resolve()
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary CSV not found: {summary_path}")

    x_column = "varied_value"
    x_label = infer_vary_label(summary_path)

    xs, ys = load_xy_from_summary(
        summary_path=summary_path,
        x_column=x_column,
        y_column=args.y_column,
        include_failures=args.include_failures,
    )

    output_path = (
        Path(args.output).resolve()
        if args.output
        else default_plot_output_path(
            summary_path,
            x_column=x_label,
            y_column=args.y_column,
        )
    )
    render_sweep_plot(
        xs=xs,
        ys=ys,
        mode=args.mode,
        x_label=x_label,
        y_label=args.y_column,
        title=args.title,
        output_path=output_path,
    )
    print(f"Saved plot: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

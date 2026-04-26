#!/usr/bin/env python3
"""Plot parameter sweeps from scripts/run_sv_prefetcher_sweep.py summary.csv."""

from __future__ import annotations

import argparse
import csv
import math
import os
import statistics
from pathlib import Path

os.environ["MPLCONFIGDIR"] = "/tmp/mplconfig_feynman"
os.environ["XDG_CACHE_HOME"] = "/tmp/xdg_cache_feynman"
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot sweep results produced by run_sv_prefetcher_sweep.py"
    )
    parser.add_argument("--summary-csv", required=True, help="Path to summary.csv")
    parser.add_argument(
        "--x-column",
        default="varied_value",
        help="Numeric column for x-axis (default: varied_value)",
    )
    parser.add_argument(
        "--y-column",
        default="total_full_s",
        help="Numeric column for y-axis (default: total_full_s)",
    )
    parser.add_argument(
        "--mode",
        choices=["scatter", "meanstd"],
        default="meanstd",
        help="scatter = raw runs, meanstd = mean with std error bars.",
    )
    parser.add_argument(
        "--include-failures",
        action="store_true",
        help="Include rows with non-zero returncode.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="PNG path. Default: next to summary.csv",
    )
    parser.add_argument("--title", default="", help="Optional plot title.")
    return parser.parse_args()


def to_float(value: str) -> float:
    if value is None or value == "":
        raise ValueError("empty value")
    return float(value)


def main() -> int:
    args = parse_args()
    summary_path = Path(args.summary_csv).resolve()
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary CSV not found: {summary_path}")

    xs: list[float] = []
    ys: list[float] = []

    with summary_path.open("r", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if not args.include_failures:
                rc = int(row.get("returncode", "1"))
                if rc != 0:
                    continue
            try:
                x = to_float(row.get(args.x_column, ""))
                y = to_float(row.get(args.y_column, ""))
            except ValueError:
                continue
            if math.isnan(x) or math.isnan(y):
                continue
            xs.append(x)
            ys.append(y)

    if not xs:
        raise RuntimeError("No plottable rows found in summary CSV.")

    fig, ax = plt.subplots(figsize=(8, 5))

    if args.mode == "scatter":
        ax.scatter(xs, ys, s=36, alpha=0.8)
    else:
        grouped: dict[float, list[float]] = {}
        for x, y in zip(xs, ys):
            grouped.setdefault(x, []).append(y)
        x_sorted = sorted(grouped.keys())
        y_mean = [statistics.mean(grouped[x]) for x in x_sorted]
        y_std = [
            statistics.stdev(grouped[x]) if len(grouped[x]) > 1 else 0.0
            for x in x_sorted
        ]
        ax.errorbar(
            x_sorted,
            y_mean,
            yerr=y_std,
            fmt="o-",
            capsize=4,
            linewidth=1.4,
            markersize=5,
        )

    ax.set_xlabel(args.x_column)
    ax.set_ylabel(args.y_column)
    if args.title:
        ax.set_title(args.title)
    else:
        ax.set_title(f"{args.y_column} vs {args.x_column}")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    if args.output:
        out_path = Path(args.output).resolve()
    else:
        out_path = summary_path.parent / f"plot_{args.y_column}_vs_{args.x_column}.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=160)
    print(f"Saved plot: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

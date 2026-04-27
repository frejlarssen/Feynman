#!/usr/bin/env python3
"""Plot threshold vs time/fidelity from qaoa pruning sweep summary.csv."""

from __future__ import annotations

import argparse
from pathlib import Path

from qaoa_pruning_sweep.plotting import plot_time_fidelity


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot threshold sweep with time and fidelity on twin y-axes."
    )
    parser.add_argument("--summary-csv", required=True, help="Path to sweep summary.csv")
    parser.add_argument("--time-column", default="total_full_s")
    parser.add_argument("--fidelity-column", default="fidelity_to_reference")
    parser.add_argument("--output", default="", help="Output image path")
    parser.add_argument("--title", default="QAOA pruning sweep")
    parser.add_argument("--xscale", choices=["linear", "log", "symlog"], default="symlog")
    parser.add_argument("--label-fontsize", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    summary_path = Path(args.summary_csv).resolve()
    output_path = Path(args.output).resolve() if args.output else None
    saved_path = plot_time_fidelity(
        summary_csv=summary_path,
        output=output_path,
        time_column=args.time_column,
        fidelity_column=args.fidelity_column,
        xscale=args.xscale,
        label_fontsize=args.label_fontsize,
    )
    print(f"Saved plot: {saved_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

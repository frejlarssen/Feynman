#!/usr/bin/env python3
"""Plot per-case aggregates from sv_prefetcher sweep summary.csv."""

from __future__ import annotations

import argparse
import csv
import statistics
from pathlib import Path

from sweeplib.plotting import apply_plot_fontsizes, configure_headless_matplotlib


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot case-level aggregates (e.g. no_cp/fixed_cp/autotuned)."
    )
    parser.add_argument("--summary-csv", required=True, help="Path to summary.csv")
    parser.add_argument("--y-column", default="total_full_s")
    parser.add_argument("--include-failures", action="store_true")
    parser.add_argument(
        "--varied-value",
        default="",
        help="Optional numeric filter on varied_value (e.g. 32).",
    )
    parser.add_argument("--output", default="", help="Output PDF path.")
    parser.add_argument("--title", default="", help="Optional title.")
    parser.add_argument(
        "--label-fontsize",
        type=float,
        default=None,
        help="Axis-label fontsize. Overrides FEYNMAN_PLOT_LABEL_FONTSIZE.",
    )
    return parser.parse_args()


def _to_float(value: str) -> float:
    if value is None or value == "":
        raise ValueError("empty")
    return float(value)


def load_case_series(
    *,
    summary_path: Path,
    y_column: str,
    include_failures: bool,
    varied_value_filter: float | None,
) -> dict[str, list[float]]:
    grouped: dict[str, list[float]] = {}
    with summary_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not include_failures and int(row.get("returncode", "1")) != 0:
                continue
            if varied_value_filter is not None:
                try:
                    vv = _to_float(row.get("varied_value", ""))
                except ValueError:
                    continue
                if vv != varied_value_filter:
                    continue
            try:
                y = _to_float(row.get(y_column, ""))
            except ValueError:
                continue
            case_name = row.get("case_name", "") or "default"
            grouped.setdefault(case_name, []).append(y)

    if not grouped:
        raise RuntimeError("No plottable rows found for the selected filters.")
    return grouped


def default_output_path(summary_path: Path, y_column: str) -> Path:
    return summary_path.parent / f"plot_{y_column}_by_case.pdf"


def render_case_plot(
    *,
    grouped: dict[str, list[float]],
    y_label: str,
    title: str,
    output_path: Path,
    label_fontsize: float | None = None,
) -> None:
    configure_headless_matplotlib()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    apply_plot_fontsizes(plt=plt, label_fontsize=label_fontsize)

    case_names = sorted(grouped)
    means = [statistics.mean(grouped[name]) for name in case_names]
    stds = [
        statistics.stdev(grouped[name]) if len(grouped[name]) > 1 else 0.0
        for name in case_names
    ]

    fig, ax = plt.subplots(figsize=(8, 5))
    xs = list(range(len(case_names)))
    ax.bar(xs, means, yerr=stds, capsize=5, alpha=0.9)
    ax.set_xticks(xs, case_names)
    ax.set_ylabel(y_label)
    ax.set_xlabel("case_name")
    ax.set_title(title or f"{y_label} by case")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)


def main() -> int:
    args = parse_args()
    summary_path = Path(args.summary_csv).resolve()
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary CSV not found: {summary_path}")

    varied_value_filter = float(args.varied_value) if args.varied_value else None
    grouped = load_case_series(
        summary_path=summary_path,
        y_column=args.y_column,
        include_failures=args.include_failures,
        varied_value_filter=varied_value_filter,
    )

    output_path = (
        Path(args.output).resolve()
        if args.output
        else default_output_path(summary_path, args.y_column)
    )
    render_case_plot(
        grouped=grouped,
        y_label=args.y_column,
        title=args.title,
        output_path=output_path,
        label_fontsize=args.label_fontsize,
    )
    print(f"Saved plot: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

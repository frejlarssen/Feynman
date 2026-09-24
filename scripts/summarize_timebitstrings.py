#!/usr/bin/env python3
"""Summarize per-bitstring compute-time artifacts as a one-row CSV."""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.plot_timebitstrings_hist import (  # noqa: E402
    TimingSeries,
    _filter_series,
    _parse_timing_dir_series,
)


def linear_percentile(values: list[float], percentile: float) -> float:
    """Return a linearly interpolated percentile (Hyndman-Fan type 7)."""
    if not values:
        raise ValueError("Cannot calculate a percentile of an empty series")
    if not 0.0 <= percentile <= 100.0:
        raise ValueError("Percentile must be between 0 and 100")
    ordered = sorted(values)
    position = (len(ordered) - 1) * percentile / 100.0
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    fraction = position - lower
    return ordered[lower] + fraction * (ordered[upper] - ordered[lower])


def summarize_series(series: TimingSeries, *, status_filter: str) -> dict[str, object]:
    if not series.times:
        raise ValueError("Cannot summarize an empty timing series")
    if len(series.times) != len(series.statuses):
        raise ValueError("Timing and status counts differ")

    statuses = Counter(series.statuses)
    minimum = min(series.times)
    median = statistics.median(series.times)
    percentile_95 = linear_percentile(series.times, 95.0)
    maximum = max(series.times)
    known_statuses = {"supported", "rejected", "unknown"}
    other_statuses = ";".join(
        f"{status}={count}"
        for status, count in sorted(statuses.items())
        if status not in known_statuses
    )

    return {
        "timing_directory": series.paths[0].parent.name,
        "input_file_count": len(series.paths),
        "num_timings": len(series.times),
        "status_filter": status_filter,
        "num_supported": statuses["supported"],
        "num_rejected": statuses["rejected"],
        "num_unknown": statuses["unknown"],
        "other_status_counts": other_statuses,
        "minimum_seconds": f"{minimum:.12g}",
        "median_seconds": f"{median:.12g}",
        "percentile_95_seconds": f"{percentile_95:.12g}",
        "maximum_seconds": f"{maximum:.12g}",
        "minimum_seconds_rounded_3dp": f"{minimum:.3f}",
        "median_seconds_rounded_3dp": f"{median:.3f}",
        "percentile_95_seconds_rounded_3dp": f"{percentile_95:.3f}",
        "maximum_seconds_rounded_3dp": f"{maximum:.3f}",
        "percentile_method": "linear interpolation; position=(n-1)*p (Hyndman-Fan type 7)",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate *.timeBitstrings.csv files from a benchmark directory and "
            "write descriptive compute-time statistics."
        )
    )
    parser.add_argument(
        "--timing-dir",
        required=True,
        type=Path,
        help="Benchmark directory containing timing files directly or under hexstrings/.",
    )
    parser.add_argument(
        "--status-filter",
        choices=("all", "supported", "rejected", "unknown"),
        default="all",
        help="Keep all timing rows or only rows with the selected status.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output CSV (default: bitstring_compute_time_summary.csv in --timing-dir).",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    timing_dir = args.timing_dir.resolve()
    unfiltered = _parse_timing_dir_series(timing_dir, timing_dir.name)
    series = _filter_series([unfiltered], args.status_filter)[0]
    row = summarize_series(series, status_filter=args.status_filter)
    output_path = (
        args.output.resolve()
        if args.output is not None
        else timing_dir / "bitstring_compute_time_summary.csv"
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(row))
        writer.writeheader()
        writer.writerow(row)

    print(f"Loaded {row['num_timings']} timings from {row['input_file_count']} files")
    print(f"Saved compute-time summary to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

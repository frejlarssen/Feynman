#!/usr/bin/env python3
"""Create a prose-ready strong-scaling summary from cloud benchmark runs."""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from collections import defaultdict
from pathlib import Path


def _load_successful_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise ValueError(f"Missing CSV header: {path}")
        required = {"run_id", "label_kind", "target_label_value", "state", "elapsed_seconds"}
        missing = required.difference(reader.fieldnames)
        if missing:
            raise ValueError(f"Missing columns in {path}: {', '.join(sorted(missing))}")
        rows = [row for row in reader if row["state"].strip() == "success"]
    if not rows:
        raise ValueError(f"No successful benchmark rows found in {path}")
    return rows


def _pool_slots(row: dict[str, str]) -> int:
    if row["label_kind"].strip() != "pool_slots":
        raise ValueError(
            f"Run {row['run_id']!r} has label_kind={row['label_kind']!r}; "
            "strong-scaling input must use pool_slots"
        )
    slots = int(row["target_label_value"])
    if slots <= 0:
        raise ValueError(f"Run {row['run_id']!r} has non-positive pool slots: {slots}")
    return slots


def _elapsed_seconds(row: dict[str, str]) -> float:
    elapsed = float(row["elapsed_seconds"])
    if elapsed <= 0:
        raise ValueError(
            f"Run {row['run_id']!r} has non-positive elapsed_seconds: {elapsed}"
        )
    return elapsed


def _format_number(value: float) -> str:
    return f"{value:g}"


def summarize(
    *,
    included_rows: list[dict[str, str]],
    all_rows: list[dict[str, str]] | None,
    fixed_batches: int | None,
) -> list[dict[str, object]]:
    included_by_slots: dict[int, list[dict[str, str]]] = defaultdict(list)
    included_ids: set[str] = set()
    for row in included_rows:
        run_id = row["run_id"].strip()
        if not run_id:
            raise ValueError("Every included row must have a run_id")
        if run_id in included_ids:
            raise ValueError(f"Duplicate included run_id: {run_id}")
        included_ids.add(run_id)
        included_by_slots[_pool_slots(row)].append(row)

    excluded_by_slots: dict[int, list[dict[str, str]]] = defaultdict(list)
    if all_rows is not None:
        all_ids: set[str] = set()
        for row in all_rows:
            run_id = row["run_id"].strip()
            if run_id in all_ids:
                raise ValueError(f"Duplicate run_id in all-runs CSV: {run_id}")
            all_ids.add(run_id)
            slots = _pool_slots(row)
            if run_id not in included_ids:
                excluded_by_slots[slots].append(row)
        missing_from_all = included_ids.difference(all_ids)
        if missing_from_all:
            raise ValueError(
                "Included runs missing from all-runs CSV: " + ", ".join(sorted(missing_from_all))
            )

    slots_sorted = sorted(included_by_slots)
    baseline_slots = slots_sorted[0]
    baseline_times = [_elapsed_seconds(row) for row in included_by_slots[baseline_slots]]
    baseline_mean = statistics.mean(baseline_times)

    source_batch_values = sorted(
        {
            int(row["num_batches"])
            for row in included_rows
            if row.get("num_batches", "").strip()
        }
    )
    source_batches = ";".join(str(value) for value in source_batch_values)

    result: list[dict[str, object]] = []
    for slots in slots_sorted:
        included = included_by_slots[slots]
        included_times = [_elapsed_seconds(row) for row in included]
        excluded = excluded_by_slots.get(slots, [])
        excluded_times = [_elapsed_seconds(row) for row in excluded]
        mean = statistics.mean(included_times)
        stddev = statistics.stdev(included_times) if len(included_times) > 1 else 0.0
        speedup = baseline_mean / mean
        efficiency = 100.0 * speedup * baseline_slots / slots
        result.append(
            {
                "pool_slots": slots,
                "fixed_batches": "" if fixed_batches is None else fixed_batches,
                "source_reported_num_batches": source_batches,
                "num_included_runs": len(included),
                "included_elapsed_seconds": ";".join(
                    _format_number(value) for value in included_times
                ),
                "mean_elapsed_seconds": f"{mean:.6f}",
                "sample_stddev_elapsed_seconds": f"{stddev:.6f}",
                "speedup_vs_baseline": f"{speedup:.6f}",
                "strong_scaling_efficiency_percent": f"{efficiency:.6f}",
                "baseline_pool_slots": baseline_slots,
                "baseline_mean_elapsed_seconds": f"{baseline_mean:.6f}",
                "num_excluded_runs": len(excluded),
                "excluded_elapsed_seconds": ";".join(
                    _format_number(value) for value in excluded_times
                ),
                "excluded_run_ids": ";".join(row["run_id"].strip() for row in excluded),
            }
        )
    return result


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Summarize successful pool-slot benchmark repeats as means, speedups, "
            "strong-scaling efficiencies, and optional outlier exclusions."
        )
    )
    parser.add_argument("--summary-csv", required=True, type=Path,
                        help="CSV containing the runs included in the statistics.")
    parser.add_argument("--all-runs-csv", type=Path,
                        help="Optional unfiltered CSV used to identify excluded runs.")
    parser.add_argument("--output", type=Path,
                        help="Output CSV (default: strong_scaling_summary.csv beside the input).")
    parser.add_argument("--fixed-batches", type=int,
                        help="Known fixed batch count, recorded separately from source num_batches.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.fixed_batches is not None and args.fixed_batches <= 0:
        raise ValueError("--fixed-batches must be positive")
    summary_path = args.summary_csv.resolve()
    output_path = (
        args.output.resolve()
        if args.output is not None
        else summary_path.parent / "strong_scaling_summary.csv"
    )
    included_rows = _load_successful_rows(summary_path)
    all_rows = (
        _load_successful_rows(args.all_runs_csv.resolve())
        if args.all_runs_csv is not None
        else None
    )
    rows = summarize(
        included_rows=included_rows,
        all_rows=all_rows,
        fixed_batches=args.fixed_batches,
    )
    _write_rows(output_path, rows)

    reported_batches = rows[0]["source_reported_num_batches"]
    if args.fixed_batches is not None and reported_batches != str(args.fixed_batches):
        print(
            f"WARNING: --fixed-batches={args.fixed_batches} differs from source "
            f"num_batches={reported_batches or 'blank'}; both are recorded in the output.",
            file=sys.stderr,
        )
    print(f"Loaded {sum(int(row['num_included_runs']) for row in rows)} included runs")
    print(f"Saved strong-scaling summary to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

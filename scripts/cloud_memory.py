#!/usr/bin/env python3
"""Collect per-batch memory profiles and summarize complete cloud runs."""
from __future__ import annotations

import argparse
import csv
import io
import json
import math
from pathlib import Path
import shutil
import statistics
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]

# RSS peaks and overlapping cgroup stall intervals must not be summed.
AGGREGATIONS = {
    "peak_rss_mib": ("mean", "max"),
    "major_faults": ("sum", "mean", "max"),
    "memory_psi_some_seconds": ("mean", "max"),
    "memory_psi_full_seconds": ("mean", "max"),
    "memory_psi_some_percent": ("mean", "max"),
    "memory_psi_full_percent": ("mean", "max"),
}
SUMMARY_FIELDS = (
    "simulate_memory_expected_workers",
    "simulate_memory_profile_count",
    "simulate_memory_process_count",
    "simulate_memory_psi_count",
    *(f"simulate_worker_{metric}_{stat}" for metric, stats in AGGREGATIONS.items() for stat in stats),
)
PLOT_METRICS = tuple(SUMMARY_FIELDS[4:])


def summarize_profiles(profiles: list[dict], expected_workers: int) -> dict:
    process_count = sum(p["process_status"] == "available" for p in profiles)
    psi_count = sum(p["memory_psi_status"] == "available" for p in profiles)
    summary = dict.fromkeys(SUMMARY_FIELDS, None)
    summary.update(
        simulate_memory_expected_workers=expected_workers,
        simulate_memory_profile_count=len(profiles),
        simulate_memory_process_count=process_count,
        simulate_memory_psi_count=psi_count,
    )
    complete = expected_workers > 0 and len(profiles) == expected_workers
    for metric, stats in AGGREGATIONS.items():
        is_psi = metric.startswith("memory_psi_")
        count = psi_count if is_psi else process_count
        if not complete or count != expected_workers:
            continue
        values = [p[metric] for p in profiles]
        if any(v is None or not math.isfinite(v) or v < 0 for v in values):
            raise ValueError(f"Invalid available memory metric: {metric}")
        for stat in stats:
            value = {"mean": statistics.mean, "max": max, "sum": sum}[stat](values)
            summary[f"simulate_worker_{metric}_{stat}"] = value
    return summary


def collect_profiles(run_dir: Path, expected_workers: int) -> dict:
    conf = json.loads((run_dir / "dag_run_conf.json").read_text())
    case = conf.get("benchmark_case", {})
    tag = case.get("experiment_tag", "qft_batch_sweep")
    source = Path(case.get("run_output_dir", f"/data/outputs/cloud_benchmarks/{tag}/{run_dir.name}"))
    if source.is_relative_to("/data"):
        source = REPO_ROOT / "data" / source.relative_to("/data")
    if source.resolve() != run_dir.resolve():
        for path in source.glob("*_batch_*.memory.json"):
            shutil.copy2(path, run_dir / path.name)
    paths = sorted(run_dir.glob("*_batch_*.memory.json"))
    profiles = [json.loads(path.read_text()) for path in paths]
    summary = summarize_profiles(profiles, expected_workers)
    payload = {
        "scope": "Worker process RSS/faults; worker cgroup PSI over worker lifetime",
        "aggregation": "Only complete metrics are aggregated; PSI means are unweighted worker means",
        "summary": summary,
        "workers": [dict(profile_file=path.name, **profile) for path, profile in zip(paths, profiles)],
    }
    (run_dir / "memory_summary.json").write_text(json.dumps(payload, indent=2) + "\n")
    for name in ("profile", "process", "psi"):
        count = summary[f"simulate_memory_{name}_count"]
        if expected_workers <= 0 or count != expected_workers:
            print(f"WARNING: memory {name} coverage {count}/{expected_workers} in {run_dir}; "
                  "incomplete metrics remain unavailable.", file=sys.stderr)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv-header", action="store_true")
    parser.add_argument("--run-dir", type=Path)
    parser.add_argument("--expected-workers", type=int)
    args = parser.parse_args()
    if args.csv_header:
        values = SUMMARY_FIELDS
    else:
        if args.run_dir is None or args.expected_workers is None or args.expected_workers < 0:
            parser.error("--run-dir and nonnegative --expected-workers are required")
        summary = collect_profiles(args.run_dir.resolve(), args.expected_workers)
        values = [summary[field] for field in SUMMARY_FIELDS]
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerow(values)
    sys.stdout.write(buffer.getvalue())


if __name__ == "__main__":
    main()

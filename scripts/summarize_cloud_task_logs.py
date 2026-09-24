#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
from pathlib import Path

AUTOTUNE_RE = re.compile(r"Autotuning time:\s+([0-9eE+.\-]+)\s+seconds")
SIM_RE = re.compile(r"Total clocktime sim for sv\.cpp:\s+([0-9eE+.\-]+)\s+seconds")
WRITE_RE = re.compile(
    r"Total clocktime writing to disk for sv\.cpp:\s+([0-9eE+.\-]+)\s+seconds"
)
FULL_RE = re.compile(
    r"Total clocktime \(including I/O\) for sv\.cpp:\s+([0-9eE+.\-]+)\s+seconds"
)
SIM_CALLS_RE = re.compile(
    r"Total clocktime for all simulate calls:\s+([0-9eE+.\-]+)\s+seconds"
)


def _mean(values: list[float]) -> str:
    if not values:
        return ""
    return f"{statistics.mean(values):.6f}"


def _sum(values: list[float]) -> str:
    if not values:
        return ""
    return f"{sum(values):.6f}"


def _max(values: list[float]) -> str:
    if not values:
        return ""
    return f"{max(values):.6f}"


def _default_airflow_log_root() -> Path:
    explicit = os.environ.get("AIRFLOW_LOG_ROOT")
    if explicit:
        return Path(explicit).expanduser()
    airflow_home = os.environ.get("AIRFLOW_HOME")
    if airflow_home:
        return Path(airflow_home).expanduser() / "logs"
    return Path.home() / "airflow" / "logs"


def _find_log_files(*, log_root: Path, dag_id: str, run_id: str, task_id: str) -> list[Path]:
    task_root = log_root / f"dag_id={dag_id}" / f"run_id={run_id}" / f"task_id={task_id}"
    if not task_root.exists():
        return []
    return sorted(path for path in task_root.rglob("attempt=*.log") if path.is_file())


def _extract_metric(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text)
    if match is None:
        return None
    return float(match.group(1))


def summarize_logs(*, log_root: Path, dag_id: str, run_id: str, task_id: str) -> dict[str, str]:
    log_files = _find_log_files(log_root=log_root, dag_id=dag_id, run_id=run_id, task_id=task_id)

    autotune_seconds: list[float] = []
    sim_seconds: list[float] = []
    write_seconds: list[float] = []
    full_seconds: list[float] = []
    sim_calls_seconds: list[float] = []

    for log_file in log_files:
        text = log_file.read_text(encoding="utf-8", errors="replace")
        value = _extract_metric(AUTOTUNE_RE, text)
        if value is not None:
            autotune_seconds.append(value)
        value = _extract_metric(SIM_RE, text)
        if value is not None:
            sim_seconds.append(value)
        value = _extract_metric(WRITE_RE, text)
        if value is not None:
            write_seconds.append(value)
        value = _extract_metric(FULL_RE, text)
        if value is not None:
            full_seconds.append(value)
        value = _extract_metric(SIM_CALLS_RE, text)
        if value is not None:
            sim_calls_seconds.append(value)

    return {
        "task_id": task_id,
        "log_file_count": str(len(log_files)),
        "autotune_match_count": str(len(autotune_seconds)),
        "autotuning_seconds_sum": _sum(autotune_seconds),
        "autotuning_seconds_mean": _mean(autotune_seconds),
        "autotuning_seconds_max": _max(autotune_seconds),
        "worker_sim_seconds_sum": _sum(sim_seconds),
        "worker_sim_seconds_mean": _mean(sim_seconds),
        "worker_sim_seconds_max": _max(sim_seconds),
        "worker_simulate_calls_seconds_sum": _sum(sim_calls_seconds),
        "worker_simulate_calls_seconds_mean": _mean(sim_calls_seconds),
        "worker_simulate_calls_seconds_max": _max(sim_calls_seconds),
        "worker_write_seconds_sum": _sum(write_seconds),
        "worker_write_seconds_mean": _mean(write_seconds),
        "worker_write_seconds_max": _max(write_seconds),
        "worker_full_seconds_sum": _sum(full_seconds),
        "worker_full_seconds_mean": _mean(full_seconds),
        "worker_full_seconds_max": _max(full_seconds),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize cloud worker timing lines from Airflow task logs."
    )
    parser.add_argument("--dag-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--task-id", default="simulate_batch")
    parser.add_argument("--log-root", type=Path, default=None)
    parser.add_argument("--output", choices=("json", "tsv"), default="json")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary = summarize_logs(
        log_root=(args.log_root or _default_airflow_log_root()).expanduser(),
        dag_id=args.dag_id,
        run_id=args.run_id,
        task_id=args.task_id,
    )

    if args.output == "json":
        json.dump(summary, sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")
        return 0

    sys.stdout.write(
        "\t".join(
            [
                summary["log_file_count"],
                summary["autotune_match_count"],
                summary["autotuning_seconds_sum"],
                summary["autotuning_seconds_mean"],
                summary["autotuning_seconds_max"],
                summary["worker_sim_seconds_sum"],
                summary["worker_sim_seconds_mean"],
                summary["worker_sim_seconds_max"],
                summary["worker_simulate_calls_seconds_sum"],
                summary["worker_simulate_calls_seconds_mean"],
                summary["worker_simulate_calls_seconds_max"],
                summary["worker_write_seconds_sum"],
                summary["worker_write_seconds_mean"],
                summary["worker_write_seconds_max"],
                summary["worker_full_seconds_sum"],
                summary["worker_full_seconds_mean"],
                summary["worker_full_seconds_max"],
            ]
        )
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

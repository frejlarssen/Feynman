#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from typing import Any


def _parse_timestamp(value: str | None) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _load_task_states_from_airflow(*, dag_id: str, run_id: str) -> list[dict[str, Any]]:
    proc = subprocess.run(
        [
            "airflow",
            "tasks",
            "states-for-dag-run",
            dag_id,
            run_id,
            "--output",
            "json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(proc.stdout)
    if not isinstance(payload, list):
        raise ValueError("Expected airflow task-state output to be a JSON array.")
    return [row for row in payload if isinstance(row, dict)]


def _load_task_states_from_file(path: str) -> list[dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("Expected task-state JSON file to contain a JSON array.")
    return [row for row in payload if isinstance(row, dict)]


def summarize_task_states(
    rows: list[dict[str, Any]],
    *,
    task_id: str,
) -> dict[str, Any]:
    matching = [row for row in rows if str(row.get("task_id", "")).strip() == task_id]

    starts: list[datetime] = []
    ends: list[datetime] = []
    task_instance_seconds_sum = 0.0
    finished_count = 0

    for row in matching:
        start = _parse_timestamp(row.get("start_date"))
        end = _parse_timestamp(row.get("end_date"))
        if start is not None:
            starts.append(start)
        if end is not None:
            ends.append(end)
        if start is not None and end is not None:
            task_instance_seconds_sum += (end - start).total_seconds()
            finished_count += 1

    stage_start = min(starts) if starts else None
    stage_end = max(ends) if ends else None
    stage_elapsed_seconds = None
    if stage_start is not None and stage_end is not None:
        stage_elapsed_seconds = (stage_end - stage_start).total_seconds()

    return {
        "task_id": task_id,
        "task_instance_count": len(matching),
        "finished_task_instance_count": finished_count,
        "stage_start_utc": stage_start.isoformat().replace("+00:00", "Z")
        if stage_start is not None
        else "",
        "stage_end_utc": stage_end.isoformat().replace("+00:00", "Z")
        if stage_end is not None
        else "",
        "stage_elapsed_seconds": ""
        if stage_elapsed_seconds is None
        else f"{stage_elapsed_seconds:.6f}",
        "task_instance_seconds_sum": f"{task_instance_seconds_sum:.6f}"
        if finished_count > 0
        else "",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize timing for one Airflow task across all task instances in a DAG run."
    )
    parser.add_argument("--dag-id", help="Airflow DAG id.")
    parser.add_argument("--run-id", help="Airflow run id.")
    parser.add_argument(
        "--task-id",
        default="simulate_batch",
        help="Task id to summarize. Defaults to simulate_batch.",
    )
    parser.add_argument(
        "--task-states-json",
        default=None,
        help="Optional path to saved `airflow tasks states-for-dag-run --output json` output.",
    )
    parser.add_argument(
        "--output",
        choices=("json", "tsv"),
        default="json",
        help="Output format. Defaults to json.",
    )
    args = parser.parse_args()

    if args.task_states_json is None and (not args.dag_id or not args.run_id):
        parser.error("Pass either --task-states-json or both --dag-id and --run-id.")
    return args


def main() -> int:
    args = parse_args()

    if args.task_states_json is not None:
        rows = _load_task_states_from_file(args.task_states_json)
    else:
        rows = _load_task_states_from_airflow(dag_id=args.dag_id, run_id=args.run_id)

    summary = summarize_task_states(rows, task_id=args.task_id)

    if args.output == "json":
        json.dump(summary, sys.stdout, separators=(",", ":"))
        sys.stdout.write("\n")
        return 0

    sys.stdout.write(
        "\t".join(
            [
                str(summary["task_instance_count"]),
                str(summary["finished_task_instance_count"]),
                str(summary["stage_start_utc"]),
                str(summary["stage_end_utc"]),
                str(summary["stage_elapsed_seconds"]),
                str(summary["task_instance_seconds_sum"]),
            ]
        )
    )
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
import re

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.airflow_gantt import (  # noqa: E402
    build_gantt_records,
    fetch_task_instances,
    load_task_states_json,
    render_gantt_byresources,
    render_gantt_bytask,
    task_states_to_task_instances_payload,
)
from scripts.summarize_airflow_task_timing import summarize_task_states  # noqa: E402
from scripts.summarize_cloud_task_logs import _default_airflow_log_root, summarize_logs  # noqa: E402


_BATCH_OUTPUT_RE = re.compile(r"_batch_(\d+)\.hsv$")
_BATCH_TIMING_RE = re.compile(r"_batch_(\d+)\.timeBitstrings\.(?:csv|tm)$")
_BATCH_CONTRIBUTION0_ABS_STATS_RE = re.compile(
    r"_batch_(\d+)\.contribution0AbsMinMax\.(?:csv|tm)$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Archive one cloud benchmark DAG run into a run directory with plots."
    )
    parser.add_argument("--dag-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--task-id", default="simulate_batch")
    parser.add_argument("--base-url", default=None)
    parser.add_argument("--log-root", type=Path, default=None)
    parser.add_argument("--task-states-json", type=Path, default=None)
    return parser.parse_args()


def _find_timing_files(output_dir: Path) -> list[Path]:
    per_batch = sorted(path.resolve() for path in output_dir.glob("*.timeBitstrings.csv"))
    if per_batch:
        return per_batch

    per_batch = sorted(path.resolve() for path in output_dir.glob("*.timeBitstrings.tm"))
    if per_batch:
        return per_batch

    legacy = output_dir / "timeBitstrings.csv"
    if legacy.exists():
        return [legacy.resolve()]

    legacy = output_dir / "timeBitstrings.tm"
    if legacy.exists():
        return [legacy.resolve()]
    return []


def _find_contribution0_abs_stats_files(output_dir: Path) -> list[Path]:
    per_batch = sorted(
        path.resolve() for path in output_dir.glob("*.contribution0AbsMinMax.csv")
    )
    if per_batch:
        return per_batch

    per_batch = sorted(
        path.resolve() for path in output_dir.glob("*.contribution0AbsMinMax.tm")
    )
    if per_batch:
        return per_batch

    legacy = output_dir / "contribution0AbsMinMax.csv"
    if legacy.exists():
        return [legacy.resolve()]

    legacy = output_dir / "contribution0AbsMinMax.tm"
    if legacy.exists():
        return [legacy.resolve()]
    return []


def _parse_timestamp(value: object) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _index_batch_files(output_dir: Path, *, pattern: re.Pattern[str]) -> dict[int, str]:
    indexed: dict[int, str] = {}
    for path in sorted(output_dir.iterdir()):
        if not path.is_file():
            continue
        match = pattern.search(path.name)
        if match is None:
            continue
        indexed[int(match.group(1))] = str(path.resolve())
    return indexed


def _build_simulate_batch_instances(
    rows: list[dict[str, object]],
    *,
    output_dir: Path,
    task_id: str,
) -> list[dict[str, object]]:
    batch_outputs = _index_batch_files(output_dir, pattern=_BATCH_OUTPUT_RE)
    batch_timings = _index_batch_files(output_dir, pattern=_BATCH_TIMING_RE)
    batch_contribution0_abs_stats = _index_batch_files(
        output_dir, pattern=_BATCH_CONTRIBUTION0_ABS_STATS_RE
    )

    instances: list[dict[str, object]] = []
    for row in rows:
        if str(row.get("task_id", "")).strip() != task_id:
            continue

        map_index_raw = row.get("map_index")
        map_index = int(map_index_raw) if map_index_raw is not None else -1
        start = _parse_timestamp(row.get("start_date"))
        end = _parse_timestamp(row.get("end_date"))
        duration_seconds = None
        if start is not None and end is not None:
            duration_seconds = (end - start).total_seconds()

        instance: dict[str, object] = {
            "map_index": map_index,
            "state": str(row.get("state", "")).strip(),
            "start_date": str(row.get("start_date", "")).strip(),
            "end_date": str(row.get("end_date", "")).strip(),
            "duration_seconds": duration_seconds,
            "pool": str(row.get("pool", "")).strip(),
            "pool_slots": row.get("pool_slots"),
        }
        if map_index >= 0:
            if map_index in batch_outputs:
                instance["output_hsv"] = batch_outputs[map_index]
            if map_index in batch_timings:
                instance["timing_file"] = batch_timings[map_index]
            if map_index in batch_contribution0_abs_stats:
                instance["contribution0_abs_stats_file"] = batch_contribution0_abs_stats[
                    map_index
                ]
        instances.append(instance)

    return sorted(instances, key=lambda item: int(item["map_index"]))


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    task_states_path: Path | None = None
    if args.task_states_json is not None:
        task_states_source = args.task_states_json.resolve()
        task_state_rows = load_task_states_json(task_states_source)
        payload = task_states_to_task_instances_payload(task_state_rows, run_id=args.run_id)
        task_states_path = output_dir / "task_states.json"
        if task_states_source != task_states_path:
            task_states_path.write_text(
                json.dumps(task_state_rows, indent=2) + "\n",
                encoding="utf-8",
            )
        summary_rows = task_state_rows
    else:
        if args.base_url:
            payload = fetch_task_instances(
                dag_id=args.dag_id,
                run_id=args.run_id,
                base_url=args.base_url,
            )
        else:
            payload = fetch_task_instances(
                dag_id=args.dag_id,
                run_id=args.run_id,
            )
        task_instances = payload.get("task_instances")
        if not isinstance(task_instances, list):
            raise ValueError("Expected Airflow taskInstances response to contain task_instances.")
        summary_rows = task_instances

    task_instances_path = output_dir / "task_instances.json"
    task_instances_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    task_summary = summarize_task_states(summary_rows, task_id=args.task_id)
    (output_dir / "simulate_batch_task_summary.json").write_text(
        json.dumps(task_summary, indent=2) + "\n",
        encoding="utf-8",
    )

    simulate_batch_instances = _build_simulate_batch_instances(
        summary_rows,
        output_dir=output_dir,
        task_id=args.task_id,
    )
    (output_dir / "simulate_batch_instances.json").write_text(
        json.dumps(simulate_batch_instances, indent=2) + "\n",
        encoding="utf-8",
    )

    log_summary = summarize_logs(
        log_root=(args.log_root or _default_airflow_log_root()).expanduser(),
        dag_id=args.dag_id,
        run_id=args.run_id,
        task_id=args.task_id,
    )
    (output_dir / "simulate_batch_log_summary.json").write_text(
        json.dumps(log_summary, indent=2) + "\n",
        encoding="utf-8",
    )

    records = build_gantt_records([payload])
    byresources = render_gantt_byresources(
        records,
        output_path=output_dir / "gantt_byresources.pdf",
    )
    bytask = render_gantt_bytask(
        records,
        output_path=output_dir / "gantt_bytask.pdf",
    )

    manifest = {
        "dag_id": args.dag_id,
        "run_id": args.run_id,
        "task_id": args.task_id,
        "task_instances_json": str(task_instances_path),
        "task_summary_json": str(output_dir / "simulate_batch_task_summary.json"),
        "simulate_batch_instances_json": str(output_dir / "simulate_batch_instances.json"),
        "log_summary_json": str(output_dir / "simulate_batch_log_summary.json"),
        "gantt_byresources_pdf": str(byresources),
        "gantt_bytask_pdf": str(bytask),
        "timing_files": [str(path) for path in _find_timing_files(output_dir)],
        "contribution0_abs_stats_files": [
            str(path) for path in _find_contribution0_abs_stats_files(output_dir)
        ],
    }
    if task_states_path is not None:
        manifest["task_states_json"] = str(task_states_path)
    (output_dir / "artifacts_manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

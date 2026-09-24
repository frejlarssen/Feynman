#!/usr/bin/env python3
from __future__ import annotations

import argparse
import glob
import os
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.airflow_gantt import (  # noqa: E402
    BASE_URL,
    build_gantt_records,
    fetch_task_instances,
    load_task_instances_json,
    render_gantt_multiexec,
)
from scripts.constants import DAG_ID as DEFAULT_DAG_ID  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot multiple Airflow DAG runs in one Gantt chart."
    )
    parser.add_argument("--dag-id", default=os.environ.get("AIRFLOW_DAG_ID", DEFAULT_DAG_ID))
    parser.add_argument(
        "--run-id",
        action="append",
        dest="run_ids",
        default=[],
        help="Airflow run id to fetch. Can be repeated.",
    )
    parser.add_argument(
        "--task-instances-json",
        type=Path,
        action="append",
        default=[],
        help="Saved Airflow taskInstances JSON payload. Can be repeated.",
    )
    parser.add_argument(
        "--input-glob",
        action="append",
        default=[],
        help="Glob pattern for saved taskInstances JSON payloads.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("figures/gantt_multiexec.pdf"),
        help="Output PDF path.",
    )
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help="Airflow API base URL when fetching directly.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    env_run_ids = [
        run_id
        for run_id in os.environ.get("AIRFLOW_DAG_RUN_IDS", "").split(",")
        if run_id
    ]
    run_ids = args.run_ids or env_run_ids

    json_paths = [path.resolve() for path in args.task_instances_json]
    for pattern in args.input_glob:
        for match in sorted(glob.glob(pattern)):
            json_paths.append(Path(match).resolve())

    payloads = [load_task_instances_json(path) for path in json_paths]
    if run_ids:
        print("dag_id:", args.dag_id)
        print("dag_run_ids:", ", ".join(run_ids))
        print("base_url:", args.base_url)
    for run_id in run_ids:
        print("run_id:", run_id)
        payloads.append(fetch_task_instances(dag_id=args.dag_id, run_id=run_id, base_url=args.base_url))

    if not payloads:
        raise RuntimeError("Pass at least one --run-id or --task-instances-json input.")

    records = build_gantt_records(payloads)
    output_path = render_gantt_multiexec(records, output_path=args.output.resolve())
    print(f'wrote multi-run Gantt to "{output_path}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

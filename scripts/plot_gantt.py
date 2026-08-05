#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    render_gantt_byresources,
    render_gantt_bytask,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot one Airflow DAG run as resource/task Gantt charts."
    )
    parser.add_argument("arg1")
    parser.add_argument("arg2", nargs="?")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("figures"),
        help="Directory for output SVGs. Defaults to ./figures.",
    )
    parser.add_argument(
        "--base-url",
        default=BASE_URL,
        help="Airflow API base URL when fetching directly.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.arg2 is not None:
        dag_id = args.arg1
        run_id = args.arg2
        print("dag_id:", dag_id)
        print("run_id:", run_id)
        print("base_url:", args.base_url)
        payload = fetch_task_instances(dag_id=dag_id, run_id=run_id, base_url=args.base_url)
    else:
        payload = load_task_instances_json(Path(args.arg1).resolve())

    records = build_gantt_records([payload])
    output_dir = args.output_dir.resolve()
    byresources = render_gantt_byresources(records, output_path=output_dir / "gantt_byresources.svg")
    bytask = render_gantt_bytask(records, output_path=output_dir / "gantt_bytask.svg")
    print(f'wrote Gantt by resources to "{byresources}"')
    print(f'wrote Gantt by task to "{bytask}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

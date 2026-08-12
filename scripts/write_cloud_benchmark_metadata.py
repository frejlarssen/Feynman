#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import platform
import shlex
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.render_cloud_benchmark_conf import _load_config  # noqa: E402
from scripts.sweeplib.materialize import (  # noqa: E402
    resolve_circuit_input,
    resolve_output_bitstrings_input,
    resolve_statevector_input,
)
from scripts.sweeplib.provenance import (  # noqa: E402
    describe_file,
    get_git_info,
    write_git_scope_snapshot,
)
from scripts.sweeplib.utils import iso_utc  # noqa: E402


def _pick(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    raise ValueError(f"Expected one of keys {keys!r} in config.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Write experiment-style metadata for a cloud benchmark run directory."
    )
    parser.add_argument("--benchmark-dir", type=Path, required=True)
    parser.add_argument("--dag-id", required=True)
    parser.add_argument("--config", default="")
    parser.add_argument("--experiment-name", required=True)
    parser.add_argument("--label-kind", default="target_num_pods")
    parser.add_argument("--label-values", nargs="*", default=[])
    parser.add_argument("--pod-counts", nargs="*", default=[])
    parser.add_argument("--runner-script", default="scripts/benchmark_cloud_pod_sweep.sh")
    parser.add_argument("--notes", default="")
    parser.add_argument("--invocation", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    benchmark_dir = args.benchmark_dir.resolve()
    benchmark_dir.mkdir(parents=True, exist_ok=True)

    repo_root = REPO_ROOT.resolve()
    git_info = get_git_info(repo_root)
    git_scope = write_git_scope_snapshot(
        repo_root=repo_root,
        sweep_dir=benchmark_dir,
        scope_paths=["airflow-dags", "scripts", "docs"],
        filename="git_diff_airflow_scripts_docs.patch",
    )

    input_files: dict[str, dict[str, Any]] = {}
    label_values = [int(value) for value in args.label_values]
    if not label_values and args.pod_counts:
        label_values = [int(value) for value in args.pod_counts]

    config_snapshot: dict[str, Any] = {
        "config_file": args.config,
        "experiment_name": args.experiment_name,
        "dag_id": args.dag_id,
        "label_kind": args.label_kind,
        "label_values": label_values,
    }
    if args.label_kind == "target_num_pods":
        config_snapshot["pod_counts"] = label_values
    elif args.label_kind == "pool_slots":
        config_snapshot["pool_slots"] = label_values

    if args.config:
        config_path = (repo_root / args.config).resolve()
        payload = _load_config(config_path)
        config_snapshot["raw_config"] = payload
        circuit_path, _ = resolve_circuit_input(_pick(payload, "circuit", "circuit_file"), repo_root)
        input_statevector_path, _ = resolve_statevector_input(
            _pick(payload, "input_statevector", "input_statevector_file"),
            repo_root,
        )
        output_bitstrings_path, _ = resolve_output_bitstrings_input(
            _pick(payload, "output_bitstrings", "output_bitstrings_file"),
            repo_root,
        )
        input_files = {
            "config": describe_file(config_path, repo_root),
            "circuit": describe_file(circuit_path, repo_root),
            "input_statevector": describe_file(input_statevector_path, repo_root),
            "output_bitstrings": describe_file(output_bitstrings_path, repo_root),
        }

    runner_script_path = (repo_root / args.runner_script).resolve()
    metadata = {
        "created_at_utc": iso_utc(dt.datetime.now(dt.timezone.utc)),
        "repo_root": str(repo_root),
        "python": sys.version,
        "platform": platform.platform(),
        "hostname": platform.node(),
        "git": {
            **git_info,
            "airflow_scripts_docs_snapshot": git_scope,
        },
        "provenance": {
            "runner_script": describe_file(runner_script_path, repo_root),
            "inputs": input_files,
        },
        "notes": args.notes,
        "invocation": args.invocation or shlex.join(sys.argv),
        "config": config_snapshot,
    }
    out_path = benchmark_dir / "benchmark_metadata.json"
    out_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sweeplib.materialize import (  # noqa: E402
    resolve_circuit_input,
    resolve_output_bitstrings_input,
    resolve_statevector_input,
)

DATA_HOST_ROOT = (REPO_ROOT / "data").resolve()
DATA_MOUNT_ROOT = Path("/data")
DEFAULT_EXPERIMENT_NAME = "qft_n8_k2"


def _resolve_config_path(value: str) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (REPO_ROOT / path).resolve()


def _host_to_mount_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        rel = resolved.relative_to(DATA_HOST_ROOT)
    except ValueError as exc:
        raise ValueError(
            f"Expected generated input under {DATA_HOST_ROOT}, got {resolved}"
        ) from exc
    return str((DATA_MOUNT_ROOT / rel).as_posix())


def _load_config(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise ValueError(f"Cloud benchmark config must be a JSON object: {path}")
    return payload


def _pick(payload: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in payload:
            return payload[key]
    raise ValueError(f"Expected one of keys {keys!r} in config.")


def render_conf(
    *,
    config_path: Path,
    target_num_pods: int | None,
    max_hexstrings_per_batch: int | None,
) -> dict[str, Any]:
    payload = _load_config(config_path)

    experiment_name = str(payload.get("experiment_name", config_path.stem or DEFAULT_EXPERIMENT_NAME))
    circuit_cfg = _pick(payload, "circuit", "circuit_file")
    statevector_cfg = _pick(payload, "input_statevector", "input_statevector_file")
    output_cfg = _pick(payload, "output_bitstrings", "output_bitstrings_file")

    circuit_path, _ = resolve_circuit_input(circuit_cfg, REPO_ROOT)
    statevector_path, _ = resolve_statevector_input(statevector_cfg, REPO_ROOT)
    output_path, _ = resolve_output_bitstrings_input(output_cfg, REPO_ROOT)

    benchmark_case = {
        "experiment_name": experiment_name,
        "circuit_file": _host_to_mount_path(circuit_path),
        "input_statevector_file": _host_to_mount_path(statevector_path),
        "output_bitstrings_file": _host_to_mount_path(output_path),
        "source_config": str(config_path.relative_to(REPO_ROOT)),
    }

    conf: dict[str, Any] = {"benchmark_case": benchmark_case}
    if target_num_pods is not None:
        conf["target_num_pods"] = int(target_num_pods)
    if max_hexstrings_per_batch is not None:
        conf["max_hexstrings_per_batch"] = int(max_hexstrings_per_batch)
    return conf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render an Airflow dag_run.conf JSON payload for cloud benchmarks."
    )
    parser.add_argument("--config", required=True, help="Path to cloud benchmark config JSON.")
    parser.add_argument("--target-num-pods", type=int, default=None)
    parser.add_argument("--max-hexstrings-per-batch", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.target_num_pods is not None and args.max_hexstrings_per_batch is not None:
        raise ValueError("Pass only one of --target-num-pods or --max-hexstrings-per-batch.")

    conf = render_conf(
        config_path=_resolve_config_path(args.config),
        target_num_pods=args.target_num_pods,
        max_hexstrings_per_batch=args.max_hexstrings_per_batch,
    )
    json.dump(conf, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

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
    describe_output_ordering,
    infer_circuit_qubits,
    normalize_generator_specs,
    normalize_output_bitstrings_spec,
    resolve_circuit_input,
    resolve_output_bitstrings_input,
    resolve_statevector_input,
)
from scripts.sweeplib.utils import experiment_tag_from_config  # noqa: E402

DATA_HOST_ROOT = (REPO_ROOT / "data").resolve()
DATA_MOUNT_ROOT = Path("/data")
DEFAULT_EXPERIMENT_TAG = "benchmark"


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


def _parse_positive_int_list(raw_value: Any, field_name: str) -> list[int]:
    if raw_value is None:
        return []
    if not isinstance(raw_value, list) or not raw_value:
        raise ValueError(
            f"{field_name} must be a non-empty JSON array of positive integers."
        )

    values: list[int] = []
    for raw_item in raw_value:
        value = int(raw_item)
        if value <= 0:
            raise ValueError(f"{field_name} entries must be > 0.")
        values.append(value)
    return values


def parse_target_num_batches_list(payload: dict[str, Any]) -> list[int]:
    raw_value = payload.get("target_num_batches_list", payload.get("target_num_batches"))
    return _parse_positive_int_list(raw_value, "target_num_batches_list")


def parse_target_pool_slots_list(payload: dict[str, Any]) -> list[int]:
    raw_value = payload.get("target_pool_slots_list")
    return _parse_positive_int_list(raw_value, "target_pool_slots_list")


def parse_repeat_count(payload: dict[str, Any]) -> int:
    raw_value = payload.get("repeat", 1)
    repeat_count = int(raw_value)
    if repeat_count <= 0:
        raise ValueError("repeat must be > 0.")
    return repeat_count


def parse_max_hexstrings_per_batch(payload: dict[str, Any]) -> int | None:
    raw_value = payload.get("max_hexstrings_per_batch")
    if raw_value is None:
        return None
    batch_size = int(raw_value)
    if batch_size <= 0:
        raise ValueError("max_hexstrings_per_batch must be > 0.")
    return batch_size


def count_output_bitstrings(config_path: Path) -> int:
    payload = _load_config(config_path)
    circuit_cfg = _pick(payload, "circuit", "circuit_file")
    output_cfg = _pick(payload, "output_bitstrings", "output_bitstrings_file")
    circuit_qubits = infer_circuit_qubits(circuit_cfg, REPO_ROOT)
    output_cfg = normalize_output_bitstrings_spec(
        output_cfg,
        REPO_ROOT,
        circuit_qubits=circuit_qubits,
    )
    output_path, _ = resolve_output_bitstrings_input(output_cfg, REPO_ROOT)
    with output_path.open("r", encoding="utf-8") as handle:
        lines = [line.strip() for line in handle if line.strip()]
    if len(lines) >= 2 and lines[0].isdigit() and lines[1].isdigit():
        return int(lines[0])
    return len(lines)


def resolve_output_ordering(config_path: Path) -> dict[str, str]:
    payload = _load_config(config_path)
    output_cfg = _pick(payload, "output_bitstrings", "output_bitstrings_file")
    return describe_output_ordering(output_cfg)


def _infer_statevector_qubits(statevector_cfg: Any) -> int | None:
    if not isinstance(statevector_cfg, dict):
        return None
    generator = str(statevector_cfg.get("generator", "")).strip().lower()
    if generator == "ket0":
        size_raw = statevector_cfg.get("size")
        if size_raw is not None:
            return int(size_raw) * 8
        n_qubits_raw = statevector_cfg.get("n_qubits", statevector_cfg.get("n"))
        return int(n_qubits_raw) if n_qubits_raw is not None else None
    size_raw = statevector_cfg.get("size")
    if size_raw is not None:
        return int(size_raw) * 8
    n_qubits_raw = statevector_cfg.get("n_qubits", statevector_cfg.get("n"))
    return int(n_qubits_raw) if n_qubits_raw is not None else None


def _infer_output_bitstring_qubits(output_cfg: Any) -> int | None:
    if not isinstance(output_cfg, dict):
        return None
    size_raw = output_cfg.get("size")
    return int(size_raw) * 8 if size_raw is not None else None


def _validate_generator_dimensions(
    *,
    experiment_tag: str,
    circuit_cfg: Any,
    statevector_cfg: Any,
    output_cfg: Any,
) -> None:
    circuit_qubits = infer_circuit_qubits(circuit_cfg, REPO_ROOT)
    statevector_qubits = _infer_statevector_qubits(statevector_cfg)
    output_qubits = _infer_output_bitstring_qubits(output_cfg)

    if (
        circuit_qubits is not None
        and statevector_qubits is not None
        and statevector_qubits < circuit_qubits
    ):
        raise ValueError(
            "Cloud benchmark config input_statevector is too small "
            f"for {experiment_tag}: circuit uses {circuit_qubits} qubits but "
            f"input_statevector describes only {statevector_qubits} qubits of storage."
        )

    if (
        circuit_qubits is not None
        and output_qubits is not None
        and output_qubits < circuit_qubits
    ):
        raise ValueError(
            "Cloud benchmark config output_bitstrings storage is too small "
            f"for {experiment_tag}: circuit uses {circuit_qubits} qubits but "
            f"output_bitstrings describe only {output_qubits} qubits of storage."
        )


def render_conf(
    *,
    config_path: Path,
    target_num_batches: int | None,
    max_hexstrings_per_batch: int | None,
    run_output_dir: str | None,
    merged_output_file: str | None,
) -> dict[str, Any]:
    payload = _load_config(config_path)

    experiment_tag = experiment_tag_from_config(config_path, fallback=DEFAULT_EXPERIMENT_TAG)
    circuit_cfg = _pick(payload, "circuit", "circuit_file")
    statevector_cfg = _pick(payload, "input_statevector", "input_statevector_file")
    output_cfg = _pick(payload, "output_bitstrings", "output_bitstrings_file")
    circuit_cfg, statevector_cfg, output_cfg, _ = normalize_generator_specs(
        circuit_cfg,
        statevector_cfg,
        output_cfg,
        REPO_ROOT,
    )

    _validate_generator_dimensions(
        experiment_tag=experiment_tag,
        circuit_cfg=circuit_cfg,
        statevector_cfg=statevector_cfg,
        output_cfg=output_cfg,
    )

    circuit_path, _ = resolve_circuit_input(circuit_cfg, REPO_ROOT)
    statevector_path, _ = resolve_statevector_input(statevector_cfg, REPO_ROOT)
    output_path, _ = resolve_output_bitstrings_input(output_cfg, REPO_ROOT)

    benchmark_case = {
        "experiment_tag": experiment_tag,
        "description": str(payload.get("description", "")).strip(),
        "circuit_file": _host_to_mount_path(circuit_path),
        "input_statevector_file": _host_to_mount_path(statevector_path),
        "output_bitstrings_file": _host_to_mount_path(output_path),
        "output_ordering_method": describe_output_ordering(output_cfg)["method"],
        "output_ordering_label": describe_output_ordering(output_cfg)["label"],
        "source_config": str(config_path.relative_to(REPO_ROOT)),
    }
    if run_output_dir is not None:
        benchmark_case["run_output_dir"] = _host_to_mount_path(_resolve_config_path(run_output_dir))
    if merged_output_file is not None:
        benchmark_case["merged_output_file"] = _host_to_mount_path(
            _resolve_config_path(merged_output_file)
        )

    conf: dict[str, Any] = {"benchmark_case": benchmark_case}
    simulate_omp_num_threads = payload.get("simulate_omp_num_threads")
    if simulate_omp_num_threads is not None:
        simulate_omp_num_threads = int(simulate_omp_num_threads)
        if simulate_omp_num_threads <= 0:
            raise ValueError("simulate_omp_num_threads must be > 0.")
        conf["simulate_omp_num_threads"] = simulate_omp_num_threads
    fraction = payload.get("fraction")
    if fraction is not None:
        fraction = float(fraction)
        if fraction <= 0.0 or fraction > 1.0:
            raise ValueError("fraction must satisfy 0 < fraction <= 1.")
        conf["fraction"] = fraction
    threshold = payload.get("threshold")
    if threshold is not None:
        threshold = float(threshold)
        if threshold < 0.0:
            raise ValueError("threshold must be >= 0.")
        conf["threshold"] = threshold
    if target_num_batches is None and max_hexstrings_per_batch is None:
        max_hexstrings_per_batch = parse_max_hexstrings_per_batch(payload)
    if target_num_batches is not None:
        conf["target_num_batches"] = int(target_num_batches)
    if max_hexstrings_per_batch is not None:
        conf["max_hexstrings_per_batch"] = int(max_hexstrings_per_batch)
    return conf


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Render an Airflow dag_run.conf JSON payload for cloud benchmarks."
    )
    parser.add_argument("--config", required=True, help="Path to cloud benchmark config JSON.")
    parser.add_argument("--target-num-batches", type=int, default=None)
    parser.add_argument("--max-hexstrings-per-batch", type=int, default=None)
    parser.add_argument(
        "--run-output-dir",
        default=None,
        help="Optional host-side output directory for one DAG run; converted to the /data mount path.",
    )
    parser.add_argument(
        "--merged-output-file",
        default=None,
        help="Optional host-side merged output file path; converted to the /data mount path.",
    )
    parser.add_argument(
        "--print-target-num-batches-list",
        action="store_true",
        help="Print the configured benchmark batch counts as a space-separated list.",
    )
    parser.add_argument(
        "--print-target-pool-slots-list",
        action="store_true",
        help="Print the configured Airflow pool-slot counts as a space-separated list.",
    )
    parser.add_argument(
        "--print-experiment-tag",
        action="store_true",
        help="Print the experiment tag derived from the config filename.",
    )
    parser.add_argument(
        "--print-repeat-count",
        action="store_true",
        help="Print the configured number of repeated runs per batch count.",
    )
    parser.add_argument(
        "--print-max-hexstrings-per-batch",
        action="store_true",
        help="Print the configured fixed batch size, if any.",
    )
    parser.add_argument(
        "--print-output-bitstring-count",
        action="store_true",
        help="Print the number of output bitstrings generated by the config.",
    )
    parser.add_argument(
        "--print-output-ordering-method",
        action="store_true",
        help="Print the configured output ordering method for fixed-batch batching.",
    )
    parser.add_argument(
        "--print-output-ordering-label",
        action="store_true",
        help="Print the configured output ordering label for fixed-batch batching.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.target_num_batches is not None and args.max_hexstrings_per_batch is not None:
        raise ValueError("Pass only one of --target-num-batches or --max-hexstrings-per-batch.")

    config_path = _resolve_config_path(args.config)
    payload = _load_config(config_path)

    if args.print_target_num_batches_list:
        sys.stdout.write(" ".join(str(batches) for batches in parse_target_num_batches_list(payload)))
        sys.stdout.write("\n")
        return 0
    if args.print_target_pool_slots_list:
        sys.stdout.write(
            " ".join(str(slots) for slots in parse_target_pool_slots_list(payload))
        )
        sys.stdout.write("\n")
        return 0
    if args.print_experiment_tag:
        sys.stdout.write(experiment_tag_from_config(config_path, fallback=DEFAULT_EXPERIMENT_TAG))
        sys.stdout.write("\n")
        return 0
    if args.print_repeat_count:
        sys.stdout.write(str(parse_repeat_count(payload)))
        sys.stdout.write("\n")
        return 0
    if args.print_max_hexstrings_per_batch:
        batch_size = parse_max_hexstrings_per_batch(payload)
        if batch_size is not None:
            sys.stdout.write(str(batch_size))
        sys.stdout.write("\n")
        return 0
    if args.print_output_bitstring_count:
        sys.stdout.write(str(count_output_bitstrings(config_path)))
        sys.stdout.write("\n")
        return 0
    if args.print_output_ordering_method:
        sys.stdout.write(resolve_output_ordering(config_path)["method"])
        sys.stdout.write("\n")
        return 0
    if args.print_output_ordering_label:
        sys.stdout.write(resolve_output_ordering(config_path)["label"])
        sys.stdout.write("\n")
        return 0

    conf = render_conf(
        config_path=config_path,
        target_num_batches=args.target_num_batches,
        max_hexstrings_per_batch=args.max_hexstrings_per_batch,
        run_output_dir=args.run_output_dir,
        merged_output_file=args.merged_output_file,
    )
    json.dump(conf, sys.stdout, separators=(",", ":"))
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

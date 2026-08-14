#!/usr/bin/env python
"""Approximate-only selected-output population stability checks across seed groups."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import itertools
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from plot_timebitstrings_hist import auto_plot_timing_file_histograms
from sweeplib.materialize import (
    infer_circuit_qubits,
    resolve_circuit_input,
    resolve_output_bitstrings_input,
    resolve_statevector_input,
)
from sweeplib.utils import experiment_tag_from_config


SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[2]
_AMP_RE = re.compile(
    r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\+([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)i$"
)
_INTERNAL_RUNTIME_RE = re.compile(
    r"Total clocktime \(including I/O\) for sv\.cpp:\s+([0-9eE+.\-]+) seconds"
)


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")


def _sanitize(name: str) -> str:
    out = []
    for ch in name.strip():
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "run"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    return payload


def _resolve_path(path_like: str | Path, repo_root: Path) -> Path:
    path = Path(path_like)
    return path if path.is_absolute() else (repo_root / path)


def _pick(cfg: dict[str, Any], key: str, cli_value: Any, default: Any = None) -> Any:
    return cli_value if cli_value is not None else cfg.get(key, default)


def _normalize_group(raw_group: dict[str, Any], *, fallback_name: str) -> dict[str, Any]:
    name = _sanitize(str(raw_group.get("name", fallback_name)))
    seeds_raw = raw_group.get("history_seeds")
    if not isinstance(seeds_raw, list) or len(seeds_raw) < 2:
        raise ValueError(f"group {name!r}: history_seeds must be an array with at least two seeds.")
    return {"name": name, "history_seeds": [int(seed) for seed in seeds_raw]}


def _merge_config(args: argparse.Namespace) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    if args.config:
        cfg = _load_json(Path(args.config).resolve())

    groups_raw = cfg.get("seed_groups")
    if not isinstance(groups_raw, list) or len(groups_raw) < 2:
        raise ValueError("Config must define at least two seed_groups.")
    groups = [
        _normalize_group(raw_group, fallback_name=f"group_{idx:02d}")
        for idx, raw_group in enumerate(groups_raw)
    ]

    merged = {
        "description": _pick(cfg, "description", args.description, ""),
        "repo_root": str(_pick(cfg, "repo_root", args.repo_root, SCRIPT_REPO_ROOT)),
        "output_root": str(
            _pick(cfg, "output_root", args.output_root, "data/outputs/validation")
        ),
        "binary": str(_pick(cfg, "binary", args.binary, "build-cloud/cloud_task.x")),
        "mpirun": str(_pick(cfg, "mpirun", args.mpirun, "mpirun")),
        "ranks": int(_pick(cfg, "ranks", args.ranks, 1)),
        "feynman_env": dict(_pick(cfg, "feynman_env", None, {}) or {}),
        "circuit": _pick(cfg, "circuit", args.circuit, None),
        "input_statevector": _pick(cfg, "input_statevector", args.input_statevector, None),
        "output_bitstrings": _pick(cfg, "output_bitstrings", args.output_bitstrings, None),
        "fraction": float(_pick(cfg, "fraction", args.fraction, 0.25)),
        "threshold": float(_pick(cfg, "threshold", args.threshold, 0.0)),
        "verbosity": int(_pick(cfg, "verbosity", args.verbosity, 1)),
        "groups": groups,
    }
    for key in ("circuit", "input_statevector", "output_bitstrings"):
        if not merged[key]:
            raise ValueError(f"Missing required parameter: {key}")
    if merged["ranks"] < 1:
        raise ValueError("ranks must be >= 1")
    merged["experiment_tag"] = experiment_tag_from_config(
        str(args.config.resolve()) if args.config else None,
        fallback="selected_output_seed_stability",
    )
    return merged


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run approximate-only selected-output stability checks across seed groups."
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--description", default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--binary", type=Path, default=None)
    parser.add_argument("--mpirun", default=None)
    parser.add_argument("--ranks", type=int, default=None)
    parser.add_argument("--circuit", default=None)
    parser.add_argument("--input-statevector", default=None)
    parser.add_argument("--output-bitstrings", default=None)
    parser.add_argument("--fraction", type=float, default=None)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--verbosity", type=int, default=None)
    return parser.parse_args(argv)


def parse_hs(path: Path) -> tuple[list[int], int]:
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError(f"Invalid output bitstring file: {path}")
    expected_count = int(lines[0])
    size_bytes = int(lines[1])
    values = [int(ln, 16) for ln in lines[2:]]
    if expected_count != len(values):
        raise ValueError(
            f"Header count mismatch in {path}: header={expected_count}, actual={len(values)}"
        )
    return values, size_bytes


def _parse_complex_token(token: str) -> complex:
    match = _AMP_RE.match(token.strip())
    if not match:
        raise ValueError(f"Invalid complex token: {token!r}")
    return complex(float(match.group(1)), float(match.group(2)))


def parse_hsv_sparse(path: Path) -> dict[int, complex]:
    if not path.exists():
        raise FileNotFoundError(f"Expected output file not found: {path}")
    out: dict[int, complex] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        idx_hex, amp_token = line.split(":", 1)
        out[int(idx_hex, 16)] = _parse_complex_token(amp_token)
    return out


def _ordered_vector(sparse: dict[int, complex], subset_indices: list[int]) -> np.ndarray:
    out = np.zeros(len(subset_indices), dtype=np.complex128)
    for i, idx in enumerate(subset_indices):
        out[i] = sparse.get(idx, 0.0 + 0.0j)
    return out


def _binary_requires_mpirun(binary: Path) -> bool:
    return "mpi" in binary.name


def _parse_internal_runtime(stdout: str) -> float | None:
    match = _INTERNAL_RUNTIME_RE.search(stdout)
    if not match:
        return None
    return float(match.group(1))


def _build_command(
    *,
    binary: Path,
    mpirun: str,
    ranks: int,
    circuit: Path,
    input_statevector: Path,
    output_bitstrings: Path,
    output_file: Path,
    fraction: float,
    threshold: float,
    verbosity: int,
) -> list[str]:
    run_args = [
        str(binary),
        "-c",
        str(circuit),
        "-i",
        str(input_statevector),
        "-b",
        str(output_bitstrings),
        "-o",
        str(output_file),
        "-f",
        str(fraction),
        "-t",
        str(threshold),
        "-v",
        str(verbosity),
    ]
    if ranks == 1 and not _binary_requires_mpirun(binary):
        return run_args
    return [mpirun, "-n", str(ranks), *run_args]


def _cross_seeded_population(component_vectors: list[np.ndarray]) -> np.ndarray:
    accum = np.zeros(component_vectors[0].shape, dtype=np.float64)
    pair_count = 0
    for i in range(len(component_vectors)):
        for j in range(i + 1, len(component_vectors)):
            accum += np.real(component_vectors[i] * np.conjugate(component_vectors[j]))
            pair_count += 1
    return accum / float(pair_count)


def _run_group(
    *,
    repo_root: Path,
    binary: Path,
    mpirun: str,
    ranks: int,
    circuit: Path,
    input_statevector: Path,
    output_bitstrings: Path,
    subset_indices: list[int],
    size_bytes: int,
    feynman_env: dict[str, str],
    fraction: float,
    threshold: float,
    verbosity: int,
    run_dir: Path,
    group: dict[str, Any],
) -> dict[str, Any]:
    group_dir = run_dir / "groups" / group["name"]
    group_dir.mkdir(parents=True, exist_ok=False)
    component_vectors: list[np.ndarray] = []
    component_files: list[str] = []
    stdout_logs: list[str] = []
    stderr_logs: list[str] = []
    command_logs: list[str] = []
    wall_times: list[float] = []
    internal_runtimes: list[float] = []
    timing_files: list[str] = []
    timing_histograms: list[str] = []

    for history_seed in group["history_seeds"]:
        output_file = group_dir / f"seed_{history_seed}.hsv"
        cmd = _build_command(
            binary=binary,
            mpirun=mpirun,
            ranks=ranks,
            circuit=circuit,
            input_statevector=input_statevector,
            output_bitstrings=output_bitstrings,
            output_file=output_file,
            fraction=fraction,
            threshold=threshold,
            verbosity=verbosity,
        )
        env = os.environ.copy()
        env.update({str(key): str(value) for key, value in feynman_env.items()})
        env["FEYNMAN_HISTORY_SEED"] = str(history_seed)

        t0 = time.perf_counter()
        proc = subprocess.run(
            cmd,
            cwd=str(repo_root),
            text=True,
            capture_output=True,
            check=False,
            env=env,
        )
        wall_time_s = float(time.perf_counter() - t0)
        stdout_log = group_dir / f"seed_{history_seed}.stdout.log"
        stderr_log = group_dir / f"seed_{history_seed}.stderr.log"
        command_log = group_dir / f"seed_{history_seed}.command.txt"
        stdout_log.write_text(proc.stdout, encoding="utf-8")
        stderr_log.write_text(proc.stderr, encoding="utf-8")
        command_log.write_text(shlex.join(cmd) + "\n", encoding="utf-8")
        if proc.returncode != 0:
            raise RuntimeError(
                f"Group {group['name']!r}, seed {history_seed} failed with return code {proc.returncode}. "
                f"See {stderr_log}"
            )
        timing_file = group_dir / "timeBitstrings.tm"
        if timing_file.exists():
            archived_timing_file = group_dir / f"seed_{history_seed}.timeBitstrings.tm"
            timing_file.replace(archived_timing_file)
            timing_files.append(str(archived_timing_file))
            timing_histograms.extend(
                str(path)
                for path in auto_plot_timing_file_histograms(
                    timing_file=archived_timing_file,
                    title=(
                        "Bitstrings compute time distribution "
                        f"({group['name']}, seed {history_seed})"
                    ),
                )
            )
        sparse = parse_hsv_sparse(output_file)
        component_vectors.append(_ordered_vector(sparse, subset_indices))
        component_files.append(str(output_file))
        stdout_logs.append(str(stdout_log))
        stderr_logs.append(str(stderr_log))
        command_logs.append(str(command_log))
        wall_times.append(wall_time_s)
        parsed_runtime = _parse_internal_runtime(proc.stdout)
        if parsed_runtime is not None:
            internal_runtimes.append(parsed_runtime)

    approx_pop = _cross_seeded_population(component_vectors)
    pop_file = group_dir / "population_estimate.csv"
    with pop_file.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ordinal", "bitstring_hex", "approx_population"])
        for ordinal, idx in enumerate(subset_indices):
            writer.writerow(
                [ordinal, f"0x{idx:0{size_bytes * 2}X}", f"{float(approx_pop[ordinal]):.18e}"]
            )
    return {
        "name": group["name"],
        "history_seeds": group["history_seeds"],
        "approx_pop": approx_pop,
        "population_file": str(pop_file),
        "component_files": component_files,
        "stdout_logs": stdout_logs,
        "stderr_logs": stderr_logs,
        "command_logs": command_logs,
        "timing_files": timing_files,
        "timing_histograms": timing_histograms,
        "wall_time_s": float(sum(wall_times)),
        "internal_runtime_s": (
            float(sum(internal_runtimes)) if len(internal_runtimes) == len(wall_times) else None
        ),
        "negative_population_count": int(np.count_nonzero(approx_pop < 0.0)),
        "signed_selected_mass": float(np.sum(approx_pop)),
        "nonnegative_selected_mass": float(np.sum(np.clip(approx_pop, 0.0, None))),
    }


def _pair_metrics(group_a: dict[str, Any], group_b: dict[str, Any]) -> dict[str, Any]:
    pop_a = group_a["approx_pop"]
    pop_b = group_b["approx_pop"]
    pop_a_nonneg = np.clip(pop_a, 0.0, None)
    pop_b_nonneg = np.clip(pop_b, 0.0, None)
    abs_diff = np.abs(pop_a - pop_b)
    l1 = float(np.sum(abs_diff))
    max_abs = float(np.max(abs_diff)) if abs_diff.size else 0.0
    mean_abs = float(np.mean(abs_diff)) if abs_diff.size else 0.0
    overlap_num = float(np.sum(np.sqrt(pop_a_nonneg * pop_b_nonneg)) ** 2)
    overlap_den = float(np.sum(pop_a_nonneg) * np.sum(pop_b_nonneg))
    bhattacharyya = None if overlap_den <= 0.0 else float(overlap_num / overlap_den)
    return {
        "group_a": group_a["name"],
        "group_b": group_b["name"],
        "pairwise_population_fidelity": bhattacharyya,
        "l1_population_distance": l1,
        "mean_abs_population_difference": mean_abs,
        "max_abs_population_difference": max_abs,
        "group_a_signed_selected_mass": group_a["signed_selected_mass"],
        "group_b_signed_selected_mass": group_b["signed_selected_mass"],
        "group_a_nonnegative_selected_mass": group_a["nonnegative_selected_mass"],
        "group_b_nonnegative_selected_mass": group_b["nonnegative_selected_mass"],
        "group_a_negative_population_count": group_a["negative_population_count"],
        "group_b_negative_population_count": group_b["negative_population_count"],
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    return value


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = _merge_config(args)
    repo_root = Path(cfg["repo_root"]).resolve()
    output_root = _resolve_path(cfg["output_root"], repo_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    run_dir = output_root / f"{_utc_stamp()}_{_sanitize(cfg['experiment_tag'])}"
    run_dir.mkdir(parents=True, exist_ok=False)

    circuit_qubits = infer_circuit_qubits(cfg["circuit"], repo_root)
    circuit, circuit_generated = resolve_circuit_input(cfg["circuit"], repo_root)
    input_statevector, input_generated = resolve_statevector_input(
        cfg["input_statevector"], repo_root, circuit_qubits=circuit_qubits
    )
    output_bitstrings, output_generated = resolve_output_bitstrings_input(
        cfg["output_bitstrings"], repo_root, circuit_qubits=circuit_qubits
    )
    binary = _resolve_path(cfg["binary"], repo_root).resolve()

    subset_indices, size_bytes = parse_hs(output_bitstrings)
    groups: list[dict[str, Any]] = []
    for group in cfg["groups"]:
        groups.append(
            _run_group(
                repo_root=repo_root,
                binary=binary,
                mpirun=str(cfg["mpirun"]),
                ranks=int(cfg["ranks"]),
                circuit=circuit,
                input_statevector=input_statevector,
                output_bitstrings=output_bitstrings,
                subset_indices=subset_indices,
                size_bytes=size_bytes,
                feynman_env={str(k): str(v) for k, v in cfg["feynman_env"].items()},
                fraction=float(cfg["fraction"]),
                threshold=float(cfg["threshold"]),
                verbosity=int(cfg["verbosity"]),
                run_dir=run_dir,
                group=group,
            )
        )

    pair_rows = [
        _pair_metrics(group_a, group_b) for group_a, group_b in itertools.combinations(groups, 2)
    ]
    summary_csv = run_dir / "summary.csv"
    with summary_csv.open("w", newline="", encoding="utf-8") as fh:
        fieldnames = list(pair_rows[0].keys()) if pair_rows else []
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in pair_rows:
            writer.writerow({key: _jsonable(value) for key, value in row.items()})

    summary_groups = []
    for group in groups:
        summary_groups.append(
            {
                "name": group["name"],
                "history_seeds": group["history_seeds"],
                "population_file": group["population_file"],
                "component_files": group["component_files"],
                "stdout_logs": group["stdout_logs"],
                "stderr_logs": group["stderr_logs"],
                "command_logs": group["command_logs"],
                "wall_time_s": group["wall_time_s"],
                "internal_runtime_s": group["internal_runtime_s"],
                "negative_population_count": group["negative_population_count"],
                "signed_selected_mass": group["signed_selected_mass"],
                "nonnegative_selected_mass": group["nonnegative_selected_mass"],
            }
        )

    summary = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "experiment_tag": cfg["experiment_tag"],
        "config": cfg,
        "config_file": str(Path(args.config).resolve()) if args.config else None,
        "paths": {
            "run_dir": str(run_dir),
            "summary_csv": str(summary_csv),
            "binary": str(binary),
            "circuit": str(circuit),
            "input_statevector": str(input_statevector),
            "output_bitstrings": str(output_bitstrings),
        },
        "generated_inputs": {
            "circuit": circuit_generated,
            "input_statevector": input_generated,
            "output_bitstrings": output_generated,
        },
        "groups": summary_groups,
        "pairwise_metrics": pair_rows,
    }
    summary_json = run_dir / "summary.json"
    summary_json.write_text(json.dumps(summary, indent=2, default=_jsonable) + "\n", encoding="utf-8")

    print(f"Run directory: {run_dir}")
    print(f"Summary CSV: {summary_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

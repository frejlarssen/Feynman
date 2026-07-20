from __future__ import annotations

import datetime as dt
import json
import re
import shlex
from pathlib import Path
from typing import Any, Callable

import numpy as np
from sweeplib.materialize import (
    resolve_circuit_input,
    resolve_output_bitstrings_input,
    resolve_statevector_input,
)
from sweeplib.provenance import build_sweep_metadata
from sweeplib.sweep import execute_command
from sweeplib.utils import iso_utc, resolve_path, sanitize

from .schema import METRIC_PATTERNS, OVERRIDE_FIELDS, ProjectPaths, RuntimeConfig, SweepConfig


_AMP_RE = re.compile(
    r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\+([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)i$"
)


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}")
    return payload


def _resolve_existing(path_like: str | Path, *, repo_root: Path, cfg_dir: Path) -> Path:
    p = Path(path_like)
    if p.is_absolute():
        return p.resolve()
    candidate_repo = (repo_root / p).resolve()
    if candidate_repo.exists():
        return candidate_repo
    return (cfg_dir / p).resolve()


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
    out: dict[int, complex] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        idx_hex, amp_token = line.split(":", 1)
        out[int(idx_hex, 16)] = _parse_complex_token(amp_token)
    return out


def load_ordered_subset_vector(path: Path, subset_indices: list[int]) -> np.ndarray:
    sparse = parse_hsv_sparse(path)
    vec = np.zeros(len(subset_indices), dtype=np.complex128)
    for i, idx in enumerate(subset_indices):
        vec[i] = sparse.get(idx, 0.0 + 0.0j)
    return vec


def parse_metrics(stdout: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    int_keys = {"num_simulate_calls"}
    for key, pattern in METRIC_PATTERNS.items():
        match = pattern.search(stdout)
        if not match:
            parsed[key] = None
            continue
        token = match.group(1)
        parsed[key] = int(token) if key in int_keys else float(token)
    return parsed


def _threshold_equal(a: float, b: float) -> bool:
    tol = max(1e-15, 1e-12 * max(1.0, abs(a), abs(b)))
    return abs(a - b) <= tol


def _reference_metrics(current: np.ndarray, reference: np.ndarray) -> dict[str, float | None]:
    diff = current - reference
    abs_amp = np.abs(diff)
    pop_current = np.abs(current) ** 2
    pop_reference = np.abs(reference) ** 2
    pop_diff = np.abs(pop_current - pop_reference)

    ref_norm = float(np.vdot(reference, reference).real)
    cur_norm = float(np.vdot(current, current).real)
    if ref_norm <= 0.0 or cur_norm <= 0.0:
        fidelity = None
    else:
        overlap = np.vdot(reference, current)
        fidelity = float((abs(overlap) ** 2) / (ref_norm * cur_norm))

    return {
        "fidelity_to_reference": fidelity,
        "max_abs_amp_error_to_reference": float(np.max(abs_amp)) if abs_amp.size else 0.0,
        "mean_abs_amp_error_to_reference": float(np.mean(abs_amp)) if abs_amp.size else 0.0,
        "max_abs_population_error_to_reference": float(np.max(pop_diff)) if pop_diff.size else 0.0,
        "mean_abs_population_error_to_reference": float(np.mean(pop_diff)) if pop_diff.size else 0.0,
    }


def resolve_paths_and_runtime(config: SweepConfig, repo_root: Path) -> tuple[ProjectPaths, RuntimeConfig]:
    cfg_dir = Path(config.config).resolve().parent if config.config else repo_root
    base_cfg_path = _resolve_existing(config.base_config, repo_root=repo_root, cfg_dir=cfg_dir)
    if not base_cfg_path.exists():
        raise FileNotFoundError(f"Base validation config does not exist: {base_cfg_path}")

    base_cfg = _load_json_object(base_cfg_path)
    merged_cfg = dict(base_cfg)
    for key in OVERRIDE_FIELDS:
        value = getattr(config, key)
        if value is not None:
            merged_cfg[key] = value

    required_base = (
        "binary",
        "circuit",
        "input_statevector",
        "output_bitstrings",
    )
    missing = [key for key in required_base if not merged_cfg.get(key)]
    if missing:
        raise ValueError(
            "Missing required fields in merged base config: "
            + ", ".join(missing)
            + f" (base={base_cfg_path})"
        )

    mpirun = str(merged_cfg.get("mpirun", "mpirun"))
    ranks = int(merged_cfg.get("ranks", 1))
    fraction = float(merged_cfg.get("fraction", 1.0))
    batch_size = int(merged_cfg.get("batch_size", 32))
    verbosity = int(merged_cfg.get("verbosity", 1))
    feynman_env = {str(k): str(v) for k, v in dict(merged_cfg.get("feynman_env") or {}).items()}

    if ranks < 1:
        raise ValueError(f"Invalid ranks={ranks}. Must be >= 1.")
    if batch_size < 0:
        raise ValueError(f"Invalid batch_size={batch_size}. Must be >= 0.")
    if verbosity < 0:
        raise ValueError(f"Invalid verbosity={verbosity}. Must be >= 0.")

    output_root = resolve_path(config.output_root, repo_root, must_exist=False)
    binary = resolve_path(str(merged_cfg["binary"]), repo_root, must_exist=True)
    circuit, _ = resolve_circuit_input(merged_cfg["circuit"], repo_root)
    input_statevector, _ = resolve_statevector_input(merged_cfg["input_statevector"], repo_root)
    output_bitstrings, _ = resolve_output_bitstrings_input(merged_cfg["output_bitstrings"], repo_root)
    subset_indices, _ = parse_hs(output_bitstrings)

    paths = ProjectPaths(
        repo_root=repo_root,
        output_root=output_root,
        base_config_path=base_cfg_path,
        binary=binary,
        circuit=circuit,
        input_statevector=input_statevector,
        output_bitstrings=output_bitstrings,
        subset_indices=subset_indices,
    )
    runtime = RuntimeConfig(
        mpirun=mpirun,
        ranks=ranks,
        fraction=fraction,
        batch_size=batch_size,
        verbosity=verbosity,
        feynman_env=feynman_env,
    )
    return paths, runtime


def build_run_points(config: SweepConfig) -> list[dict[str, float]]:
    return [{"threshold": float(t)} for t in config.thresholds]


def build_command(
    *,
    runtime: RuntimeConfig,
    paths: ProjectPaths,
    threshold: float,
    output_file: Path,
) -> list[str]:
    return [
        runtime.mpirun,
        "-n",
        str(runtime.ranks),
        str(paths.binary),
        "-c",
        str(paths.circuit),
        "-i",
        str(paths.input_statevector),
        "-b",
        str(paths.output_bitstrings),
        "-o",
        str(output_file),
        "-f",
        str(runtime.fraction),
        "-t",
        str(threshold),
        "-s",
        str(runtime.batch_size),
        "-v",
        str(runtime.verbosity),
    ]


def _run_tag(threshold: float, run_index: int, rep: int) -> str:
    return f"run_{run_index:04d}_th-{sanitize(f'{threshold:.12g}')}_rep{rep:02d}"


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def make_run_one(
    *,
    config: SweepConfig,
    paths: ProjectPaths,
    runtime: RuntimeConfig,
    git_info: dict[str, Any],
) -> Callable[[Path, int, int, Any], tuple[dict[str, Any], int]]:
    reference_by_rep: dict[int, np.ndarray] = {}

    def _run_one(sweep_dir: Path, run_index: int, rep: int, run_point: Any):
        if not isinstance(run_point, dict):
            raise ValueError(f"Expected run point dict, got: {run_point!r}")
        threshold = float(run_point["threshold"])

        run_dir = sweep_dir / _run_tag(threshold, run_index, rep)
        run_dir.mkdir(parents=True, exist_ok=False)
        output_file = run_dir / "output.hsv"
        stdout_file = run_dir / "stdout.log"
        stderr_file = run_dir / "stderr.log"

        cmd = build_command(runtime=runtime, paths=paths, threshold=threshold, output_file=output_file)
        start = dt.datetime.now(dt.timezone.utc)
        rc, elapsed_s, stdout_text, stderr_text = execute_command(
            cmd=cmd,
            cwd=paths.repo_root,
            timeout_seconds=config.timeout_seconds,
            dry_run=config.dry_run,
            env_overrides=runtime.feynman_env,
        )
        end = dt.datetime.now(dt.timezone.utc)

        stdout_file.write_text(stdout_text, encoding="utf-8")
        stderr_file.write_text(stderr_text, encoding="utf-8")
        metrics = parse_metrics(stdout_text)

        current_vec: np.ndarray | None = None
        if rc == 0 and output_file.exists():
            current_vec = load_ordered_subset_vector(output_file, paths.subset_indices)
            if _threshold_equal(threshold, config.reference_threshold):
                reference_by_rep[rep] = current_vec

        reference_vec = reference_by_rep.get(rep)
        fidelity_metrics: dict[str, float | None] = {
            "fidelity_to_reference": None,
            "max_abs_amp_error_to_reference": None,
            "mean_abs_amp_error_to_reference": None,
            "max_abs_population_error_to_reference": None,
            "mean_abs_population_error_to_reference": None,
        }
        if current_vec is not None and reference_vec is not None:
            fidelity_metrics = _reference_metrics(current_vec, reference_vec)

        row = {
            "run_index": run_index,
            "repeat_index": rep,
            "case_name": "default",
            "varied_param": "threshold",
            "varied_value": threshold,
            "threshold": threshold,
            "reference_threshold": config.reference_threshold,
            "reference_available": int(reference_vec is not None),
            "returncode": rc,
            "walltime_s": elapsed_s,
            "num_simulate_calls": metrics["num_simulate_calls"],
            "total_simulate_calls_s": metrics["total_simulate_calls_s"],
            "avg_simulate_call_s": metrics["avg_simulate_call_s"],
            "total_sim_s": metrics["total_sim_s"],
            "total_io_s": metrics["total_io_s"],
            "total_full_s": metrics["total_full_s"],
            **fidelity_metrics,
            "run_dir": _rel(run_dir, paths.repo_root),
            "output_file": _rel(output_file, paths.repo_root),
            "stdout_file": _rel(stdout_file, paths.repo_root),
            "stderr_file": _rel(stderr_file, paths.repo_root),
            "start_utc": iso_utc(start),
            "end_utc": iso_utc(end),
            "command": shlex.join(cmd),
            "feynman_env": json.dumps(runtime.feynman_env, sort_keys=True),
            "commit_short": git_info.get("commit_short", ""),
            "branch": git_info.get("branch", ""),
            "dirty": int(bool(git_info.get("dirty", False))),
        }
        return row, rc

    return _run_one


def build_metadata(
    *,
    config: SweepConfig,
    paths: ProjectPaths,
    runtime: RuntimeConfig,
    git_info: dict[str, Any],
    sweep_dir: Path,
    created_at: dt.datetime,
    runner_script_path: Path,
    invocation: str,
) -> dict[str, Any]:
    return build_sweep_metadata(
        created_at=created_at,
        repo_root=paths.repo_root,
        sweep_dir=sweep_dir,
        git_scope_paths=["scripts", "src", "data/generated/circuits/qaoa_maxcut"],
        git_scope_filename="git_diff_scripts_src_qaoa.patch",
        git_scope_key="scripts_src_qaoa_snapshot",
        notes=config.notes,
        invocation=invocation,
        dry_run=config.dry_run,
        git_info=git_info,
        binary_path=paths.binary,
        input_files={
            "base_config": paths.base_config_path,
            "circuit": paths.circuit,
            "input_statevector": paths.input_statevector,
            "output_bitstrings": paths.output_bitstrings,
        },
        runner_script_path=runner_script_path,
        launcher_command=runtime.mpirun,
        launcher_key="mpi_launcher",
        config_snapshot={
            "config_file": config.config,
            "experiment_name": config.experiment_name,
            "repo_root": str(paths.repo_root),
            "output_root": str(paths.output_root),
            "base_config": str(paths.base_config_path),
            "thresholds": config.thresholds,
            "reference_threshold": config.reference_threshold,
            "repeat": config.repeat,
            "max_cases": config.max_cases,
            "continue_on_error": config.continue_on_error,
            "timeout_seconds": config.timeout_seconds,
            "runtime": {
                "binary": str(paths.binary),
                "mpirun": runtime.mpirun,
                "ranks": runtime.ranks,
                "circuit": str(paths.circuit),
                "input_statevector": str(paths.input_statevector),
                "output_bitstrings": str(paths.output_bitstrings),
                "fraction": runtime.fraction,
                "batch_size": runtime.batch_size,
                "verbosity": runtime.verbosity,
                "feynman_env": runtime.feynman_env,
            },
        },
    )

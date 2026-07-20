#!/usr/bin/env python
"""Sweep quantum-walk qubit count for Feynman vs quimb."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import importlib.metadata
import json
import math
import os
import re
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parents[1]
for path in (SCRIPT_REPO_ROOT, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.sweeplib.plot_style import apply_plot_fontsizes, configure_headless_matplotlib
from scripts.sweeplib.provenance import build_sweep_metadata, get_git_info


THREAD_ENV_VARS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
    "VECLIB_MAXIMUM_THREADS",
)


SUMMARY_FIELDS = [
    "run_index",
    "n",
    "repeat_index",
    "overall_status",
    "quimb_status",
    "feynman_status",
    "feynman_transpiled_status",
    "returncode",
    "sweep_elapsed_s",
    "qwalk_iterations",
    "output_count",
    "transpiled_qiskit_ops",
    "feynman_walltime_s",
    "feynman_internal_total_s",
    "feynman_peak_rss_mb",
    "feynman_transpiled_walltime_s",
    "feynman_transpiled_internal_total_s",
    "feynman_transpiled_peak_rss_mb",
    "feynman_transpiled_error",
    "quimb_total_s",
    "quimb_transpile_s",
    "quimb_build_s",
    "quimb_amplitude_s",
    "quimb_peak_rss_mb",
    "quimb_last_stage",
    "quimb_last_amplitude",
    "quimb_last_width",
    "quimb_last_cost_log10",
    "quimb_last_max_size",
    "quimb_last_peak_size",
    "quimb_last_maxrss_mb",
    "quimb_error",
    "max_abs_amp_error",
    "max_abs_population_error",
    "run_dir",
    "summary_json",
    "stdout_file",
    "stderr_file",
]


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")


def _sanitize(name: str) -> str:
    out = []
    for ch in name.strip():
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "qwalk_quimb_sweep"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    return payload


def _recorded_environment() -> dict[str, Any]:
    return {
        "python": sys.executable,
        "thread_env": {name: os.environ.get(name) for name in THREAD_ENV_VARS if os.environ.get(name) is not None},
    }


def _software_versions() -> dict[str, str]:
    versions = {
        "python": sys.version.split()[0],
    }
    for package in ("qiskit", "quimb", "numpy", "matplotlib"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not-installed"
    return versions


def _build_provenance_metadata(
    *,
    args: argparse.Namespace,
    cfg: dict[str, Any],
    repo_root: Path,
    sweep_dir: Path,
    created_at: dt.datetime,
) -> dict[str, Any]:
    validation = cfg["validation"]
    binary = _resolve_path(validation.get("binary", "build-release/sv_prefetcher_subset_mpi.x"), repo_root)
    launcher = str(validation.get("mpirun", "mpirun"))
    scope_paths = [
        "CMakeLists.txt",
        "requirements.txt",
        "src",
        "apps",
        "scripts/run_pipeline.py",
        "scripts/sweeplib",
        "scripts/tensor_comparison",
        "scripts/experiments/paper/perf/qwalk_quimb_qubit_sweep.json",
    ]
    try:
        return build_sweep_metadata(
            created_at=created_at,
            repo_root=repo_root,
            sweep_dir=sweep_dir,
            git_scope_paths=scope_paths,
            git_scope_filename="git_qwalk_quimb_scope.patch",
            git_scope_key="qwalk_quimb_scope",
            notes=str(cfg.get("notes", "")),
            invocation=" ".join(sys.argv),
            dry_run=bool(cfg.get("dry_run", False)),
            git_info=get_git_info(repo_root),
            binary_path=binary,
            input_files={"config": args.config.resolve()},
            runner_script_path=Path(__file__).resolve(),
            launcher_command=launcher,
            launcher_key="mpirun",
            config_snapshot=cfg,
        )
    except Exception as err:
        return {
            "provenance_error_type": type(err).__name__,
            "provenance_error": str(err),
            "git": get_git_info(repo_root),
        }


def _resolve_path(path_like: str | Path, repo_root: Path) -> Path:
    p = Path(path_like)
    return p.resolve() if p.is_absolute() else (repo_root / p).resolve()


def _merge_config(args: argparse.Namespace) -> dict[str, Any]:
    raw = _load_json(args.config.resolve())

    def pick(key: str, default: Any = None) -> Any:
        arg_value = getattr(args, key, None)
        return arg_value if arg_value not in (None, "") else raw.get(key, default)

    qwalk = dict(raw.get("qwalk", {}))
    output_bitstrings = dict(raw.get("output_bitstrings", {}))
    input_statevector = dict(raw.get("input_statevector", {"generator": "ket0"}))
    validation = dict(raw.get("validation", {}))
    plotting = dict(raw.get("plotting", {}))
    cfg = {
        "experiment_name": pick("experiment_name", "qwalk_quimb_qubit_sweep"),
        "repo_root": pick("repo_root", "."),
        "output_root": pick("output_root", "data/outputs/experiments"),
        "qubits": raw.get("qubits", []),
        "repeat": int(raw.get("repeat", 1)),
        "continue_on_error": bool(raw.get("continue_on_error", True)),
        "dry_run": bool(raw.get("dry_run", False)),
        "timeout_seconds": raw.get("timeout_seconds"),
        "feynman_transpiled_max_n": raw.get("feynman_transpiled_max_n"),
        "qwalk": qwalk,
        "input_statevector": input_statevector,
        "output_bitstrings": output_bitstrings,
        "validation": validation,
        "plotting": plotting,
        "notes": pick("notes", raw.get("notes", "")),
    }
    if args.continue_on_error:
        cfg["continue_on_error"] = True
    if args.dry_run:
        cfg["dry_run"] = True
    if args.timeout_seconds is not None:
        cfg["timeout_seconds"] = args.timeout_seconds
    if not cfg["qubits"]:
        raise ValueError("Sweep config must define a non-empty 'qubits' list.")
    if cfg["repeat"] < 1:
        raise ValueError("repeat must be >= 1")
    return cfg


def _statevector_size_bytes(n_qubits: int) -> int:
    return max(1, (int(n_qubits) + 7) // 8)


def _enabled_up_to(default: bool, max_n: Any, n_qubits: int) -> bool:
    if max_n is None:
        return default
    return default and n_qubits <= int(max_n)


def _build_validation_config(
    *,
    cfg: dict[str, Any],
    n_qubits: int,
    run_dir: Path,
    repo_root: Path,
) -> dict[str, Any]:
    qwalk = cfg["qwalk"]
    output_bitstrings = cfg["output_bitstrings"]
    input_statevector = cfg["input_statevector"]
    validation = cfg["validation"]
    run_feynman_transpiled = _enabled_up_to(
        bool(validation.get("run_feynman_transpiled", False)),
        cfg["feynman_transpiled_max_n"],
        n_qubits,
    )
    size_bytes = _statevector_size_bytes(n_qubits)
    payload = {
        "experiment_name": f"{cfg['experiment_name']}_n{n_qubits}",
        "repo_root": str(repo_root),
        "output_root": str(run_dir / "validation_runs"),
        "circuit": {
            "generator": "qwalk",
            "n": n_qubits,
            "it": int(qwalk.get("iterations", 4)),
            **{k: v for k, v in qwalk.items() if k not in {"iterations"}},
        },
        "input_statevector": {
            "generator": input_statevector.get("generator", "ket0"),
            "size": int(input_statevector.get("size", size_bytes)),
        },
        "output_bitstrings": {
            "generator": output_bitstrings.get("generator", "one_interval"),
            "size": int(output_bitstrings.get("size", size_bytes)),
            "count": int(output_bitstrings.get("count", 8)),
            **{k: v for k, v in output_bitstrings.items() if k not in {"generator", "size", "count"}},
        },
        **validation,
        "timeout_seconds": cfg["timeout_seconds"],
        "run_feynman_transpiled": run_feynman_transpiled,
    }
    return payload


def _validation_process_timeout(validation_cfg: dict[str, Any], per_simulator_timeout: Any) -> float | None:
    if per_simulator_timeout is None:
        return None
    phases = 1  # quimb
    if validation_cfg.get("run_feynman", True):
        phases += 1
    if validation_cfg.get("run_feynman_transpiled", False):
        phases += 1
    return float(per_simulator_timeout) * phases + 120.0


def _find_run_dir_from_stdout(stdout: str) -> Path | None:
    for line in stdout.splitlines():
        if line.startswith("Run directory: "):
            return Path(line.split(": ", 1)[1]).resolve()
        if "] Run directory: " in line:
            return Path(line.split("Run directory: ", 1)[1]).resolve()
    return None


def _float_or_empty(value: Any) -> str:
    if value is None or value == "":
        return ""
    return f"{float(value):.18e}"


def _parse_first_float(pattern: str, text: str) -> float | None:
    match = re.search(pattern, text)
    return None if match is None else float(match.group(1))


def _parse_first_int(pattern: str, text: str) -> int | None:
    match = re.search(pattern, text)
    return None if match is None else int(match.group(1))


def _parse_last_float(pattern: str, text: str) -> float | None:
    matches = list(re.finditer(pattern, text))
    return None if not matches else float(matches[-1].group(1))


def _parse_last_int(pattern: str, text: str) -> int | None:
    matches = list(re.finditer(pattern, text))
    return None if not matches else int(matches[-1].group(1))


def _partial_problem_from_stdout(stdout: str) -> dict[str, Any]:
    problem: dict[str, Any] = {}
    output_count = _parse_first_int(r"output_count=(\d+)", stdout)
    transpiled_ops = _parse_first_int(r"Transpile done: transpiled_ops=(\d+)", stdout)
    if output_count is not None:
        problem["output_count"] = output_count
    if transpiled_ops is not None:
        problem["transpiled_qiskit_ops"] = transpiled_ops
    return problem


def _partial_metrics_from_stdout(stdout: str) -> dict[str, Any]:
    metrics: dict[str, Any] = {}
    transpile_s = _parse_first_float(r"Transpile done: .*elapsed_s=([0-9eE+.\-]+)", stdout)
    build_s = _parse_first_float(r"quimb circuit built: elapsed_s=([0-9eE+.\-]+)", stdout)
    feynman_wall_s = _parse_first_float(r"Feynman run done \(feynman\): walltime_s=([0-9eE+.\-]+)", stdout)
    feynman_internal_s = _parse_first_float(r"Feynman internal total \(s\): ([0-9eE+.\-]+)", stdout)
    if transpile_s is not None:
        metrics["quimb_transpile_s"] = transpile_s
    if build_s is not None:
        metrics["quimb_build_s"] = build_s
    if feynman_wall_s is not None or feynman_internal_s is not None:
        metrics["feynman"] = {
            "enabled": True,
            "walltime_s": feynman_wall_s,
            "internal_total_s": feynman_internal_s,
            "peak_rss_mb": None,
        }
    return metrics


def _partial_quimb_progress_from_stdout(stdout: str) -> dict[str, Any]:
    progress: dict[str, Any] = {}
    stage_patterns = [
        ("builtin_amplitude_done", r"builtin amplitude done:"),
        ("contraction_done", r"contraction done:"),
        ("contraction_tree_ready", r"contraction tree ready:"),
        ("final_full_simplify_done", r"final full_simplify done:"),
        ("bitstring_projection_done", r"bitstring projection done:"),
        ("get_psi_simplified_done", r"get_psi_simplified done:"),
        ("amplitude_started", r"quimb amplitude \d+/\d+ start:"),
        ("circuit_built", r"quimb circuit built:"),
        ("transpile_done", r"Transpile done:"),
    ]
    last_stage_pos = -1
    last_stage = None
    for stage, pattern in stage_patterns:
        matches = list(re.finditer(pattern, stdout))
        if matches and matches[-1].start() > last_stage_pos:
            last_stage_pos = matches[-1].start()
            last_stage = stage
    if last_stage is not None:
        progress["quimb_last_stage"] = last_stage

    amp_match = list(re.finditer(r"quimb amplitude (\d+)/(\d+) start:", stdout))
    if amp_match:
        progress["quimb_last_amplitude"] = f"{amp_match[-1].group(1)}/{amp_match[-1].group(2)}"

    width = _parse_last_float(r"contraction tree ready: .*width=([0-9eE+.\-]+)", stdout)
    cost = _parse_last_float(r"contraction tree ready: .*cost_log10=([0-9eE+.\-]+)", stdout)
    max_size = _parse_last_int(r"contraction tree ready: .*max_size=(\d+)", stdout)
    peak_size = _parse_last_int(r"contraction tree ready: .*peak_size=(\d+)", stdout)
    maxrss = _parse_last_float(r"maxrss_mb=([0-9eE+.\-]+)", stdout)
    if width is not None:
        progress["quimb_last_width"] = width
    if cost is not None:
        progress["quimb_last_cost_log10"] = cost
    if max_size is not None:
        progress["quimb_last_max_size"] = max_size
    if peak_size is not None:
        progress["quimb_last_peak_size"] = peak_size
    if maxrss is not None:
        progress["quimb_last_maxrss_mb"] = maxrss
        progress["quimb_peak_rss_mb"] = maxrss

    failure_match = re.search(r"quimb failed during amplitude: (.+)", stdout)
    if failure_match:
        progress["quimb_error"] = failure_match.group(1)
    return progress


def _timed_out_in_quimb(stdout: str) -> bool:
    return (
        "Building quimb circuit" in stdout
        or "Computing " in stdout
        or "quimb amplitude " in stdout
        or "get_psi_simplified" in stdout
        or "full_simplify" in stdout
        or "contraction tree" in stdout
    )


def _load_summary(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _load_transpile_metadata(validation_run_dir: Path | None) -> dict[str, Any]:
    if validation_run_dir is None:
        return {}
    path = validation_run_dir / "quimb_transpile_metadata.json"
    if not path.exists():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _stream_subprocess(
    cmd: list[str],
    *,
    cwd: Path,
    stdout_file: Path,
    stderr_file: Path,
    timeout_s: float | None,
) -> tuple[int, float, str, str]:
    stdout_chunks: list[str] = []
    stderr_chunks: list[str] = []
    t0 = time.perf_counter()

    with stdout_file.open("w", encoding="utf-8") as out_handle, stderr_file.open("w", encoding="utf-8") as err_handle:
        proc = subprocess.Popen(
            cmd,
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        assert proc.stdout is not None
        assert proc.stderr is not None

        def pump(stream: Any, chunks: list[str], log_handle: Any, terminal: Any) -> None:
            try:
                for line in iter(stream.readline, ""):
                    chunks.append(line)
                    log_handle.write(line)
                    log_handle.flush()
                    terminal.write(line)
                    terminal.flush()
            finally:
                stream.close()

        stdout_thread = threading.Thread(
            target=pump,
            args=(proc.stdout, stdout_chunks, out_handle, sys.stdout),
            daemon=True,
        )
        stderr_thread = threading.Thread(
            target=pump,
            args=(proc.stderr, stderr_chunks, err_handle, sys.stderr),
            daemon=True,
        )
        stdout_thread.start()
        stderr_thread.start()

        try:
            returncode = proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            timeout_line = f"\n[qwalk-quimb-sweep] timeout after {timeout_s} seconds\n"
            stderr_chunks.append(timeout_line)
            err_handle.write(timeout_line)
            err_handle.flush()
            sys.stderr.write(timeout_line)
            sys.stderr.flush()
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            returncode = 124

        stdout_thread.join(timeout=5)
        stderr_thread.join(timeout=5)

    elapsed_s = time.perf_counter() - t0
    return returncode, elapsed_s, "".join(stdout_chunks), "".join(stderr_chunks)


def _row_from_run(
    *,
    run_index: int,
    n_qubits: int,
    repeat_index: int,
    returncode: int,
    elapsed_s: float,
    stdout_file: Path,
    stderr_file: Path,
    validation_run_dir: Path | None,
    summary: dict[str, Any],
    stdout: str,
    qwalk_iterations: int,
) -> dict[str, Any]:
    metrics = dict(summary.get("metrics", {}))
    problem = dict(summary.get("problem", {}))
    for key, value in _load_transpile_metadata(validation_run_dir).items():
        problem.setdefault(key, value)
    for key, value in _partial_problem_from_stdout(stdout).items():
        problem.setdefault(key, value)
    if not metrics:
        metrics.update(_partial_metrics_from_stdout(stdout))
    quimb_progress = _partial_quimb_progress_from_stdout(stdout)
    feynman = metrics.get("feynman", {}) if isinstance(metrics.get("feynman", {}), dict) else {}
    feynman_transpiled = (
        metrics.get("feynman_transpiled", {}) if isinstance(metrics.get("feynman_transpiled", {}), dict) else {}
    )
    summary_status = summary.get("status")
    timed_out = returncode == 124
    if summary_status == "ok":
        overall_status = "ok"
        quimb_status = "ok"
    elif summary_status == "quimb_timeout":
        overall_status = "quimb_timeout"
        quimb_status = "timeout"
    elif summary_status == "quimb_failed":
        overall_status = "quimb_failed"
        quimb_status = "failed"
    elif "quimb failed during " in stdout:
        overall_status = "quimb_failed"
        quimb_status = "failed"
    elif timed_out and _timed_out_in_quimb(stdout):
        overall_status = "quimb_timeout"
        quimb_status = "timeout"
    elif timed_out:
        overall_status = "timeout"
        quimb_status = "unknown"
    elif returncode == 0:
        overall_status = summary_status or "ok"
        quimb_status = "ok"
    else:
        overall_status = summary_status or "failed"
        quimb_status = "unknown"

    if feynman.get("timeout"):
        feynman_status = "timeout"
    elif feynman.get("failed"):
        feynman_status = "failed"
    elif feynman.get("walltime_s") is not None or feynman.get("internal_total_s") is not None:
        feynman_status = "ok"
    else:
        feynman_status = "not_run" if feynman.get("enabled", True) else "disabled"
    feynman_transpiled_status = (
        "timeout"
        if feynman_transpiled.get("timeout")
        else "failed"
        if feynman_transpiled.get("failed")
        else (
            "ok"
            if feynman_transpiled.get("enabled") and feynman_transpiled.get("walltime_s") is not None
            else ("disabled" if not feynman_transpiled.get("enabled") else "not_run")
        )
    )
    if overall_status == "ok":
        if feynman_status == "timeout":
            overall_status = "feynman_timeout"
        elif feynman_status == "failed":
            overall_status = "feynman_failed"
    quimb_peak_rss_mb = metrics.get("quimb_phase_peak_rss_mb")
    if quimb_peak_rss_mb is None:
        quimb_peak_rss_mb = quimb_progress.get("quimb_peak_rss_mb")
    return {
        "run_index": run_index,
        "n": n_qubits,
        "repeat_index": repeat_index,
        "overall_status": overall_status,
        "quimb_status": quimb_status,
        "feynman_status": feynman_status,
        "feynman_transpiled_status": feynman_transpiled_status,
        "returncode": returncode,
        "sweep_elapsed_s": _float_or_empty(elapsed_s),
        "qwalk_iterations": qwalk_iterations,
        "output_count": problem.get("output_count", ""),
        "transpiled_qiskit_ops": problem.get("transpiled_qiskit_ops", ""),
        "feynman_walltime_s": _float_or_empty(feynman.get("walltime_s")),
        "feynman_internal_total_s": _float_or_empty(feynman.get("internal_total_s")),
        "feynman_peak_rss_mb": _float_or_empty(feynman.get("peak_rss_mb")),
        "feynman_transpiled_walltime_s": _float_or_empty(feynman_transpiled.get("walltime_s")),
        "feynman_transpiled_internal_total_s": _float_or_empty(feynman_transpiled.get("internal_total_s")),
        "feynman_transpiled_peak_rss_mb": _float_or_empty(feynman_transpiled.get("peak_rss_mb")),
        "feynman_transpiled_error": feynman_transpiled.get("error", ""),
        "quimb_total_s": _float_or_empty(metrics.get("quimb_total_s")),
        "quimb_transpile_s": _float_or_empty(metrics.get("quimb_transpile_s")),
        "quimb_build_s": _float_or_empty(metrics.get("quimb_build_s")),
        "quimb_amplitude_s": _float_or_empty(metrics.get("quimb_amplitude_s")),
        "quimb_peak_rss_mb": _float_or_empty(quimb_peak_rss_mb),
        "quimb_last_stage": quimb_progress.get("quimb_last_stage", ""),
        "quimb_last_amplitude": quimb_progress.get("quimb_last_amplitude", ""),
        "quimb_last_width": _float_or_empty(quimb_progress.get("quimb_last_width")),
        "quimb_last_cost_log10": _float_or_empty(quimb_progress.get("quimb_last_cost_log10")),
        "quimb_last_max_size": quimb_progress.get("quimb_last_max_size", ""),
        "quimb_last_peak_size": quimb_progress.get("quimb_last_peak_size", ""),
        "quimb_last_maxrss_mb": _float_or_empty(quimb_progress.get("quimb_last_maxrss_mb")),
        "quimb_error": quimb_progress.get("quimb_error", ""),
        "max_abs_amp_error": _float_or_empty(metrics.get("max_abs_amp_error")),
        "max_abs_population_error": _float_or_empty(metrics.get("max_abs_population_error")),
        "run_dir": "" if validation_run_dir is None else str(validation_run_dir),
        "summary_json": "" if validation_run_dir is None else str(validation_run_dir / "summary.json"),
        "stdout_file": str(stdout_file),
        "stderr_file": str(stderr_file),
    }


def _read_rows(summary_csv: Path, *, include_failures: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with summary_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not include_failures and row.get("overall_status") != "ok":
                continue
            rows.append(row)
    return rows


def _mean_std_by_n(rows: list[dict[str, Any]], column: str) -> dict[int, tuple[float, float, int]]:
    grouped: dict[int, list[float]] = {}
    for row in rows:
        raw = row.get(column, "")
        if raw in ("", None):
            continue
        value = float(raw)
        if not math.isfinite(value):
            continue
        grouped.setdefault(int(row["n"]), []).append(value)
    return {
        n: (
            sum(values) / len(values),
            statistics.stdev(values) if len(values) > 1 else 0.0,
            len(values),
        )
        for n, values in grouped.items()
    }


def _write_aggregate_summary(summary_csv: Path, *, output_dir: Path) -> Path:
    rows_all = _read_rows(summary_csv, include_failures=True)
    rows_quimb_ok = [row for row in rows_all if row.get("quimb_status") == "ok"]
    series = {
        "feynman_walltime_s": _mean_std_by_n(rows_all, "feynman_walltime_s"),
        "feynman_internal_total_s": _mean_std_by_n(rows_all, "feynman_internal_total_s"),
        "feynman_peak_rss_mb": _mean_std_by_n(rows_all, "feynman_peak_rss_mb"),
        "quimb_total_s": _mean_std_by_n(rows_quimb_ok, "quimb_total_s"),
        "quimb_amplitude_s": _mean_std_by_n(rows_quimb_ok, "quimb_amplitude_s"),
        "quimb_peak_rss_mb": _mean_std_by_n(rows_quimb_ok, "quimb_peak_rss_mb"),
        "transpiled_qiskit_ops": _mean_std_by_n(rows_all, "transpiled_qiskit_ops"),
    }
    quimb_status_by_n: dict[int, list[str]] = {}
    feynman_status_by_n: dict[int, list[str]] = {}
    for row in rows_all:
        n = int(row["n"])
        quimb_status_by_n.setdefault(n, []).append(str(row.get("quimb_status", "")))
        feynman_status_by_n.setdefault(n, []).append(str(row.get("feynman_status", "")))

    fields = [
        "n",
        "quimb_statuses",
        "feynman_statuses",
    ]
    for name in series:
        fields.extend([f"{name}_mean", f"{name}_std", f"{name}_count"])

    out = output_dir / "summary_by_n.csv"
    with out.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for n in sorted({int(row["n"]) for row in rows_all}):
            row: dict[str, Any] = {
                "n": n,
                "quimb_statuses": ";".join(quimb_status_by_n.get(n, [])),
                "feynman_statuses": ";".join(feynman_status_by_n.get(n, [])),
            }
            for name, values in series.items():
                mean, std, count = values.get(n, ("", "", ""))
                row[f"{name}_mean"] = _float_or_empty(mean)
                row[f"{name}_std"] = _float_or_empty(std)
                row[f"{name}_count"] = count
            writer.writerow(row)
    return out


def _plot_summary(summary_csv: Path, *, output_dir: Path, title: str, label_fontsize: float | None = None) -> list[Path]:
    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_plot_fontsizes(plt=plt, label_fontsize=label_fontsize)
    rows_all = _read_rows(summary_csv, include_failures=True)
    rows_quimb_ok = [row for row in rows_all if row.get("quimb_status") == "ok"]
    quimb_not_measured_ns = sorted({int(row["n"]) for row in rows_all if row.get("quimb_status") == "failed"})
    quimb_timeout_ns = sorted({int(row["n"]) for row in rows_all if row.get("quimb_status") == "timeout"})

    outputs: list[Path] = []
    time_series = {
        "Feynman original wall": _mean_std_by_n(rows_all, "feynman_walltime_s"),
        "Feynman original internal": _mean_std_by_n(rows_all, "feynman_internal_total_s"),
        "Feynman transpiled wall": _mean_std_by_n(rows_all, "feynman_transpiled_walltime_s"),
        "Feynman transpiled internal": _mean_std_by_n(rows_all, "feynman_transpiled_internal_total_s"),
        "quimb": _mean_std_by_n(rows_quimb_ok, "quimb_total_s"),
    }
    memory_series = {
        "Feynman original": _mean_std_by_n(rows_all, "feynman_peak_rss_mb"),
        "Feynman transpiled": _mean_std_by_n(rows_all, "feynman_transpiled_peak_rss_mb"),
        "quimb": _mean_std_by_n(rows_quimb_ok, "quimb_peak_rss_mb"),
    }
    ops_series = {
        "transpiled Qiskit ops": _mean_std_by_n(rows_all, "transpiled_qiskit_ops"),
    }

    for filename, ylabel, series, mark_missing_quimb in (
        ("qwalk_quimb_time.pdf", "Time (s)", time_series, True),
        ("qwalk_quimb_memory.pdf", "Peak RSS (MB)", memory_series, True),
        ("qwalk_quimb_transpiled_ops.pdf", "Transpiled Qiskit ops", ops_series, False),
    ):
        fig, ax = plt.subplots(figsize=(8, 5))
        plotted = False
        for label, values in series.items():
            if not values:
                continue
            xs = sorted(values)
            ys = [values[x][0] for x in xs]
            stds = [values[x][1] for x in xs]
            lower = [min(std, max(y * 0.999, 0.0)) for y, std in zip(ys, stds)]
            upper = stds
            ax.errorbar(
                xs,
                ys,
                yerr=[lower, upper],
                marker="o",
                linewidth=1.6,
                elinewidth=1.3,
                capsize=5,
                capthick=1.3,
                label=label,
            )
            plotted = True
        if mark_missing_quimb and quimb_not_measured_ns:
            for i, n in enumerate(quimb_not_measured_ns):
                ax.axvline(
                    n,
                    color="0.7",
                    linestyle=":",
                    linewidth=1.1,
                    label="quimb not measured" if i == 0 else None,
                    zorder=0,
                )
        if mark_missing_quimb and quimb_timeout_ns:
            for i, n in enumerate(quimb_timeout_ns):
                ax.axvline(
                    n,
                    color="0.45",
                    linestyle="--",
                    linewidth=1.1,
                    label="quimb timeout" if i == 0 else None,
                    zorder=0,
                )
        ax.set_xlabel("Qubits")
        ax.set_ylabel(ylabel)
        ax.set_yscale("log")
        ax.set_title(title)
        ax.grid(True, alpha=0.3)
        if plotted:
            ax.legend()
        fig.tight_layout()
        out = output_dir / filename
        fig.savefig(out, dpi=160)
        plt.close(fig)
        outputs.append(out)
    return outputs


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--experiment-name", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument("--no-plot", action="store_true")
    parser.add_argument("--plot-only", action="store_true", help="Regenerate plots from an existing summary.csv.")
    parser.add_argument("--summary-csv", type=Path, help="Existing qwalk-quimb sweep summary.csv for --plot-only.")
    parser.add_argument("--plot-output-dir", type=Path, help="Directory for regenerated plots; defaults to summary.csv parent.")
    return parser.parse_args(argv)


def _plot_title_from_metadata(summary_csv: Path) -> tuple[str, float | None]:
    metadata_path = summary_csv.parent / "sweep_metadata.json"
    if not metadata_path.exists():
        return summary_csv.parent.name, None
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    config = metadata.get("config", {}) if isinstance(metadata, dict) else {}
    plotting = config.get("plotting", {}) if isinstance(config.get("plotting", {}), dict) else {}
    title = str(plotting.get("title", config.get("experiment_name", metadata.get("experiment_name", summary_csv.parent.name))))
    return title, plotting.get("label_fontsize")


def _plot_only(args: argparse.Namespace) -> int:
    if args.summary_csv is None:
        raise ValueError("--plot-only requires --summary-csv")
    summary_csv = args.summary_csv.resolve()
    if not summary_csv.exists():
        raise FileNotFoundError(f"summary.csv not found: {summary_csv}")
    output_dir = args.plot_output_dir.resolve() if args.plot_output_dir is not None else summary_csv.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    title, label_fontsize = _plot_title_from_metadata(summary_csv)
    aggregate = _write_aggregate_summary(summary_csv, output_dir=output_dir)
    print(f"Saved aggregate summary: {aggregate}")
    for out in _plot_summary(summary_csv, output_dir=output_dir, title=title, label_fontsize=label_fontsize):
        print(f"Saved plot: {out}")
    return 0


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.plot_only:
        return _plot_only(args)
    if args.config is None:
        raise ValueError("--config is required unless --plot-only is used")
    cfg = _merge_config(args)
    repo_root = _resolve_path(cfg["repo_root"], Path.cwd())
    output_root = _resolve_path(cfg["output_root"], repo_root)
    sweep_dir = output_root / f"{_utc_stamp()}_{_sanitize(str(cfg['experiment_name']))}"
    sweep_dir.mkdir(parents=True, exist_ok=False)
    configs_dir = sweep_dir / "configs"
    logs_dir = sweep_dir / "logs"
    configs_dir.mkdir()
    logs_dir.mkdir()
    recorded_environment = _recorded_environment()
    software_versions = _software_versions()
    if recorded_environment["thread_env"]:
        print(f"[qwalk-quimb-sweep] thread environment: {recorded_environment['thread_env']}", flush=True)
    print(f"[qwalk-quimb-sweep] software versions: {software_versions}", flush=True)

    created_at = dt.datetime.now(dt.timezone.utc)
    metadata = {
        **_build_provenance_metadata(
            args=args,
            cfg=cfg,
            repo_root=repo_root,
            sweep_dir=sweep_dir,
            created_at=created_at,
        ),
        "created_utc": created_at.isoformat(),
        "experiment_name": cfg["experiment_name"],
        "config": cfg,
        "config_file": str(args.config.resolve()),
        "sweep_dir": str(sweep_dir),
        "runner": str(Path(__file__).resolve()),
        "environment": recorded_environment,
        "software": software_versions,
    }
    (sweep_dir / "sweep_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    summary_csv = sweep_dir / "summary.csv"
    failures = 0
    run_index = 0
    with summary_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for n_qubits in [int(n) for n in cfg["qubits"]]:
            skip_remaining_repeats_for_n = False
            for repeat_index in range(1, int(cfg["repeat"]) + 1):
                run_index += 1
                if skip_remaining_repeats_for_n:
                    row = {field: "" for field in SUMMARY_FIELDS}
                    row.update(
                        {
                            "run_index": run_index,
                            "n": n_qubits,
                            "repeat_index": repeat_index,
                            "overall_status": "skipped_after_quimb_terminal",
                            "quimb_status": "skipped",
                            "feynman_status": "skipped",
                            "feynman_transpiled_status": "skipped",
                            "qwalk_iterations": int(cfg["qwalk"].get("iterations", 4)),
                        }
                    )
                    writer.writerow(row)
                    handle.flush()
                    print(
                        f"[qwalk-quimb-sweep] n={n_qubits} repeat={repeat_index}: "
                        "skipped after earlier quimb timeout/failure for this n",
                        flush=True,
                    )
                    continue
                validation_cfg = _build_validation_config(
                    cfg=cfg,
                    n_qubits=n_qubits,
                    run_dir=sweep_dir,
                    repo_root=repo_root,
                )
                validation_cfg_path = configs_dir / f"qwalk_quimb_n{n_qubits}_r{repeat_index}.json"
                validation_cfg_path.write_text(json.dumps(validation_cfg, indent=2), encoding="utf-8")
                stdout_file = logs_dir / f"run_{run_index:03d}_n{n_qubits}_stdout.log"
                stderr_file = logs_dir / f"run_{run_index:03d}_n{n_qubits}_stderr.log"
                cmd = [
                    sys.executable,
                    str(repo_root / "scripts" / "run_pipeline.py"),
                    "validation",
                    "qwalk-quimb",
                    "--config",
                    str(validation_cfg_path),
                ]
                print(f"[qwalk-quimb-sweep] n={n_qubits} repeat={repeat_index}: {' '.join(cmd)}", flush=True)
                process_timeout_s = _validation_process_timeout(validation_cfg, cfg["timeout_seconds"])
                if cfg["dry_run"]:
                    elapsed_s = 0.0
                    stdout = f"[dry-run] {' '.join(cmd)}\n"
                    stderr = ""
                    returncode = 0
                    stdout_file.write_text(stdout, encoding="utf-8")
                    stderr_file.write_text(stderr, encoding="utf-8")
                else:
                    returncode, elapsed_s, stdout, stderr = _stream_subprocess(
                        cmd,
                        cwd=repo_root,
                        stdout_file=stdout_file,
                        stderr_file=stderr_file,
                        timeout_s=process_timeout_s,
                    )
                validation_run_dir = _find_run_dir_from_stdout(stdout)
                summary_path = None if validation_run_dir is None else validation_run_dir / "summary.json"
                summary = _load_summary(summary_path)
                row = _row_from_run(
                    run_index=run_index,
                    n_qubits=n_qubits,
                    repeat_index=repeat_index,
                    returncode=returncode,
                    elapsed_s=elapsed_s,
                    stdout_file=stdout_file,
                    stderr_file=stderr_file,
                    validation_run_dir=validation_run_dir,
                    summary=summary,
                    stdout=stdout,
                    qwalk_iterations=int(cfg["qwalk"].get("iterations", 4)),
                )
                writer.writerow(row)
                handle.flush()
                if row.get("quimb_status") in {"failed", "timeout"}:
                    skip_remaining_repeats_for_n = True
                if returncode != 0 and row.get("quimb_status") not in {"failed", "timeout"}:
                    failures += 1
                    print(
                        f"[qwalk-quimb-sweep] n={n_qubits} failed with rc={returncode}; "
                        f"stdout={stdout_file} stderr={stderr_file}",
                        file=sys.stderr,
                        flush=True,
                    )
                    if not cfg["continue_on_error"]:
                        break
            if failures and not cfg["continue_on_error"]:
                break

    print(f"Sweep directory: {sweep_dir}")
    print(f"Summary CSV: {summary_csv}")
    if not args.no_plot and not cfg["dry_run"]:
        aggregate = _write_aggregate_summary(summary_csv, output_dir=sweep_dir)
        print(f"Saved aggregate summary: {aggregate}")
        for out in _plot_summary(
            summary_csv,
            output_dir=sweep_dir,
            title=str(cfg["plotting"].get("title", cfg["experiment_name"])),
            label_fontsize=cfg["plotting"].get("label_fontsize"),
        ):
            print(f"Saved plot: {out}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())

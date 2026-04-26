from __future__ import annotations

import datetime as dt
import shlex
from pathlib import Path
from typing import Any, Callable

from sweeplib.provenance import build_sweep_metadata
from sweeplib.sweep import execute_command
from sweeplib.utils import iso_utc, resolve_path, sanitize

from .schema import METRIC_PATTERNS, ProjectPaths, SweepConfig


def resolve_paths(config: SweepConfig, repo_root: Path) -> ProjectPaths:
    return ProjectPaths(
        repo_root=repo_root,
        binary=resolve_path(config.binary, repo_root, must_exist=True),
        circuit=resolve_path(config.circuit, repo_root, must_exist=True),
        input_statevector=resolve_path(config.input_statevector, repo_root, must_exist=True),
        output_bitstrings=resolve_path(config.output_bitstrings, repo_root, must_exist=True),
        output_root=resolve_path(config.output_root, repo_root, must_exist=False),
    )


def base_params(config: SweepConfig) -> dict[str, Any]:
    return {
        "ranks": config.ranks,
        "batch_size": config.batch_size,
        "fraction": config.fraction,
        "threshold": config.threshold,
        "p": config.p,
        "r": config.r,
        "verbosity": config.verbosity,
        "dense": config.dense,
    }


def parse_metrics(stdout: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, pattern in METRIC_PATTERNS.items():
        match = pattern.search(stdout)
        if not match:
            parsed[key] = None
            continue
        token = match.group(1)
        parsed[key] = int(token) if key == "num_simulate_calls" else float(token)
    return parsed


def build_command(config: SweepConfig, paths: ProjectPaths, params: dict[str, Any], output_file: Path) -> list[str]:
    cmd = [
        config.mpirun,
        "-n",
        str(int(params["ranks"])),
        str(paths.binary),
        "-c",
        str(paths.circuit),
        "-i",
        str(paths.input_statevector),
        "-b",
        str(paths.output_bitstrings),
        "-o",
        str(output_file),
        "-s",
        str(int(params["batch_size"])),
        "-f",
        str(float(params["fraction"])),
        "-t",
        str(float(params["threshold"])),
        "-v",
        str(int(params["verbosity"])),
    ]
    if params["p"] is not None and params["r"] is not None:
        cmd.extend(["-p", str(params["p"]), "-r", str(params["r"])])
    if bool(params["dense"]):
        cmd.append("-D")
    return cmd


def _run_tag(vary: str, value: Any, run_index: int, rep: int) -> str:
    return f"run_{run_index:04d}_{vary}-{sanitize(str(value))}_rep{rep:02d}"


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def make_run_one(
    *,
    config: SweepConfig,
    paths: ProjectPaths,
    git_info: dict[str, Any],
) -> Callable[[Path, int, int, Any], tuple[dict[str, Any], int]]:
    def _run_one(sweep_dir: Path, run_index: int, rep: int, varied_value: Any):
        params = base_params(config)
        params[config.vary] = varied_value

        run_dir = sweep_dir / _run_tag(config.vary, varied_value, run_index, rep)
        run_dir.mkdir(parents=True, exist_ok=False)

        output_file = run_dir / "output.hsv"
        timing_file = run_dir / "timeBitstrings.tm"
        stdout_file = run_dir / "stdout.log"
        stderr_file = run_dir / "stderr.log"

        cmd = build_command(config, paths, params, output_file)
        start = dt.datetime.now(dt.timezone.utc)
        rc, elapsed_s, stdout_text, stderr_text = execute_command(
            cmd=cmd,
            cwd=paths.repo_root,
            timeout_seconds=config.timeout_seconds,
            dry_run=config.dry_run,
        )
        end = dt.datetime.now(dt.timezone.utc)

        stdout_file.write_text(stdout_text, encoding="utf-8")
        stderr_file.write_text(stderr_text, encoding="utf-8")
        metrics = parse_metrics(stdout_text)

        row = {
            "run_index": run_index,
            "repeat_index": rep,
            "varied_param": config.vary,
            "varied_value": varied_value,
            "ranks": params["ranks"],
            "batch_size": params["batch_size"],
            "fraction": params["fraction"],
            "threshold": params["threshold"],
            "p": params["p"],
            "r": params["r"],
            "verbosity": params["verbosity"],
            "dense": int(bool(params["dense"])),
            "returncode": rc,
            "walltime_s": elapsed_s,
            "num_simulate_calls": metrics["num_simulate_calls"],
            "total_simulate_calls_s": metrics["total_simulate_calls_s"],
            "avg_simulate_call_s": metrics["avg_simulate_call_s"],
            "total_sim_s": metrics["total_sim_s"],
            "total_io_s": metrics["total_io_s"],
            "total_full_s": metrics["total_full_s"],
            "run_dir": _rel(run_dir, paths.repo_root),
            "output_file": _rel(output_file, paths.repo_root),
            "timing_file": _rel(timing_file, paths.repo_root) if timing_file.exists() else "",
            "stdout_file": _rel(stdout_file, paths.repo_root),
            "stderr_file": _rel(stderr_file, paths.repo_root),
            "start_utc": iso_utc(start),
            "end_utc": iso_utc(end),
            "command": shlex.join(cmd),
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
        git_scope_paths=["apps", "src"],
        git_scope_filename="git_diff_apps_src.patch",
        git_scope_key="apps_src_snapshot",
        notes=config.notes,
        invocation=invocation,
        dry_run=config.dry_run,
        git_info=git_info,
        binary_path=paths.binary,
        input_files={
            "circuit": paths.circuit,
            "input_statevector": paths.input_statevector,
            "output_bitstrings": paths.output_bitstrings,
        },
        runner_script_path=runner_script_path,
        launcher_command=config.mpirun,
        launcher_key="mpi_launcher",
        config_snapshot={
            "config_file": config.config,
            "experiment_name": config.experiment_name,
            "vary": config.vary,
            "values": config.values,
            "repeat": config.repeat,
            "binary": str(paths.binary),
            "mpirun": config.mpirun,
            "circuit": str(paths.circuit),
            "input_statevector": str(paths.input_statevector),
            "output_bitstrings": str(paths.output_bitstrings),
            "output_root": str(paths.output_root),
            "defaults": base_params(config),
        },
    )

from __future__ import annotations

import datetime as dt
import re
import shlex
from pathlib import Path
from typing import Any, Callable

from sweeplib.materialize import (
    resolve_circuit_input,
    resolve_output_bitstrings_input,
    resolve_statevector_input,
)
from sweeplib.provenance import build_sweep_metadata
from sweeplib.sweep import execute_command
from sweeplib.utils import iso_utc, resolve_path, sanitize

from .schema import CASE_OVERRIDE_FIELDS, METRIC_PATTERNS, ProjectPaths, SweepConfig


_GATE_DISTRIBUTION_PATTERN = re.compile(
    r"Circuit has\s+(?P<total_gates>\d+)\s+gates\. Distributed as:\s*"
    r"\n\s*Chunk 0:\s*(?P<chunk0_gates>\d+)\s+gates\s*"
    r"\n\s*Chunk 1:\s*(?P<chunk1_gates>\d+)\s+gates\s*"
    r"\n\s*Chunk 2:\s*(?P<chunk2_gates>\d+)\s+gates",
    re.MULTILINE,
)
_ARTIFICIAL_DISTRIBUTION_PATTERN = re.compile(
    r"Total number of artificial sources:\s*(?P<total_artificial_sources>\d+)\. Distributed as:\s*"
    r"\n\s*Chunk 0:\s*(?P<chunk0_artificial>\d+)\s*"
    r"\n\s*Chunk 1:\s*(?P<chunk1_artificial>\d+)\s*"
    r"\n\s*Chunk 2:\s*(?P<chunk2_artificial>\d+)\s*",
    re.MULTILINE,
)


def resolve_paths(config: SweepConfig, repo_root: Path) -> ProjectPaths:
    circuit_path, _ = resolve_circuit_input(config.circuit, repo_root)
    input_statevector_path, _ = resolve_statevector_input(config.input_statevector, repo_root)
    output_bitstrings_path, _ = resolve_output_bitstrings_input(config.output_bitstrings, repo_root)
    return ProjectPaths(
        repo_root=repo_root,
        binary=resolve_path(config.binary, repo_root, must_exist=True),
        circuit=circuit_path,
        input_statevector=input_statevector_path,
        output_bitstrings=output_bitstrings_path,
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


def build_run_points(config: SweepConfig) -> list[dict[str, Any]]:
    cases = config.cases if config.cases else [{"name": "default"}]
    run_points: list[dict[str, Any]] = []
    for case in cases:
        case_name = str(case["name"])
        overrides = {key: case[key] for key in CASE_OVERRIDE_FIELDS if key in case}
        for value in config.values:
            run_points.append(
                {
                    "case_name": case_name,
                    "value": value,
                    "overrides": overrides,
                }
            )
    return run_points


def parse_metrics(stdout: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    int_keys = {
        "num_simulate_calls",
        "autotune_candidates",
        "autotune_step_size",
        "autotune_best_gate_ops_estimate",
    }
    for key, pattern in METRIC_PATTERNS.items():
        match = pattern.search(stdout)
        if not match:
            parsed[key] = None
            continue
        token = match.group(1)
        parsed[key] = int(token) if key in int_keys else float(token)
    return parsed


def parse_structure_metrics(stdout: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {
        "total_gates": None,
        "chunk0_gates": None,
        "chunk1_gates": None,
        "chunk2_gates": None,
        "total_artificial_sources": None,
        "chunk0_artificial": None,
        "chunk1_artificial": None,
        "chunk2_artificial": None,
        "num_histories_estimate": None,
        "gate_ops_estimate": None,
    }

    gate_match = _GATE_DISTRIBUTION_PATTERN.search(stdout)
    if gate_match:
        for key in ("total_gates", "chunk0_gates", "chunk1_gates", "chunk2_gates"):
            parsed[key] = int(gate_match.group(key))

    art_match = _ARTIFICIAL_DISTRIBUTION_PATTERN.search(stdout)
    if art_match:
        for key in (
            "total_artificial_sources",
            "chunk0_artificial",
            "chunk1_artificial",
            "chunk2_artificial",
        ):
            parsed[key] = int(art_match.group(key))

    g0 = parsed["chunk0_gates"]
    g1 = parsed["chunk1_gates"]
    g2 = parsed["chunk2_gates"]
    a0 = parsed["chunk0_artificial"]
    a1 = parsed["chunk1_artificial"]
    a2 = parsed["chunk2_artificial"]
    if None not in (g0, g1, g2, a0, a1, a2):
        parsed["num_histories_estimate"] = (1 << a0) * (1 << a1) * (1 << a2)
        parsed["gate_ops_estimate"] = (1 << a2) * (g2 + (1 << a1) * (g1 + (1 << a0) * g0))

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


def _run_tag(case_name: str, vary: str, value: Any, run_index: int, rep: int) -> str:
    return f"run_{run_index:04d}_{sanitize(case_name)}_{vary}-{sanitize(str(value))}_rep{rep:02d}"


def _rel(path: Path, root: Path) -> str:
    return str(path.relative_to(root))


def make_run_one(
    *,
    config: SweepConfig,
    paths: ProjectPaths,
    git_info: dict[str, Any],
) -> Callable[[Path, int, int, Any], tuple[dict[str, Any], int]]:
    def _run_one(sweep_dir: Path, run_index: int, rep: int, run_point: Any):
        if not isinstance(run_point, dict):
            raise ValueError(f"Expected run point dict, got: {run_point!r}")
        case_name = str(run_point.get("case_name", "default"))
        varied_value = run_point.get("value")
        case_overrides = run_point.get("overrides", {})
        if not isinstance(case_overrides, dict):
            raise ValueError(f"Expected dict for run point overrides, got: {case_overrides!r}")

        params = base_params(config)
        params.update(case_overrides)
        params[config.vary] = varied_value

        run_dir = sweep_dir / _run_tag(case_name, config.vary, varied_value, run_index, rep)
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
        structure_metrics = parse_structure_metrics(stdout_text)

        row = {
            "run_index": run_index,
            "repeat_index": rep,
            "case_name": case_name,
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
            "autotune_time_s": metrics["autotune_time_s"],
            "autotune_candidates": metrics["autotune_candidates"],
            "autotune_step_size": metrics["autotune_step_size"],
            "autotune_best_gate_ops_estimate": metrics["autotune_best_gate_ops_estimate"],
            "total_gates": structure_metrics["total_gates"],
            "chunk0_gates": structure_metrics["chunk0_gates"],
            "chunk1_gates": structure_metrics["chunk1_gates"],
            "chunk2_gates": structure_metrics["chunk2_gates"],
            "total_artificial_sources": structure_metrics["total_artificial_sources"],
            "chunk0_artificial": structure_metrics["chunk0_artificial"],
            "chunk1_artificial": structure_metrics["chunk1_artificial"],
            "chunk2_artificial": structure_metrics["chunk2_artificial"],
            "num_histories_estimate": structure_metrics["num_histories_estimate"],
            "gate_ops_estimate": structure_metrics["gate_ops_estimate"],
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
            "cases": config.cases if config.cases else [{"name": "default"}],
        },
    )

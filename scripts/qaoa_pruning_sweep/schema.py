from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


METRIC_PATTERNS = {
    "num_simulate_calls": re.compile(r"Number of simulate calls:\s+(\d+)"),
    "total_simulate_calls_s": re.compile(
        r"Total clocktime for all simulate calls:\s+([0-9eE+.\-]+) seconds"
    ),
    "avg_simulate_call_s": re.compile(
        r"Average clocktime per simulate call:\s+([0-9eE+.\-]+) seconds"
    ),
    "total_sim_s": re.compile(r"Total clocktime sim for sv.cpp:\s+([0-9eE+.\-]+) seconds"),
    "total_io_s": re.compile(
        r"Total clocktime writing to disk for sv.cpp:\s+([0-9eE+.\-]+) seconds"
    ),
    "total_full_s": re.compile(
        r"Total clocktime \(including I/O\) for sv.cpp:\s+([0-9eE+.\-]+) seconds"
    ),
}

SUMMARY_FIELDS = [
    "run_index",
    "repeat_index",
    "case_name",
    "varied_param",
    "varied_value",
    "threshold",
    "reference_threshold",
    "reference_available",
    "returncode",
    "walltime_s",
    "num_simulate_calls",
    "total_simulate_calls_s",
    "avg_simulate_call_s",
    "total_sim_s",
    "total_io_s",
    "total_full_s",
    "fidelity_to_reference",
    "max_abs_amp_error_to_reference",
    "mean_abs_amp_error_to_reference",
    "max_abs_population_error_to_reference",
    "mean_abs_population_error_to_reference",
    "run_dir",
    "output_file",
    "stdout_file",
    "stderr_file",
    "start_utc",
    "end_utc",
    "command",
    "feynman_env",
    "commit_short",
    "branch",
    "dirty",
]

OVERRIDE_FIELDS = (
    "binary",
    "mpirun",
    "ranks",
    "circuit",
    "input_statevector",
    "output_bitstrings",
    "fraction",
    "batch_size",
    "verbosity",
    "feynman_env",
)

DEFAULT_OPTIONS: dict[str, Any] = {
    "config": "",
    "experiment_name": None,
    "repo_root": ".",
    "output_root": "data/outputs/experiments",
    "base_config": None,
    "thresholds": None,
    "reference_threshold": 0.0,
    "repeat": 1,
    "continue_on_error": False,
    "timeout_seconds": None,
    "notes": "",
    "dry_run": False,
    "no_plot": False,
    "max_cases": None,
    "binary": None,
    "mpirun": None,
    "ranks": None,
    "circuit": None,
    "input_statevector": None,
    "output_bitstrings": None,
    "fraction": None,
    "batch_size": None,
    "verbosity": None,
    "feynman_env": None,
}

REQUIRED_FIELDS = ("experiment_name", "base_config", "thresholds")

NUMERIC_CASTS: dict[str, Any] = {
    "reference_threshold": float,
    "repeat": int,
    "timeout_seconds": float,
    "max_cases": int,
    "ranks": int,
    "fraction": float,
    "batch_size": int,
    "verbosity": int,
}

BOOLEAN_FIELDS = ("continue_on_error", "dry_run", "no_plot")


@dataclass(frozen=True)
class SweepConfig:
    config: str
    experiment_name: str
    repo_root: str
    output_root: str
    base_config: str
    thresholds: list[float]
    reference_threshold: float
    repeat: int
    continue_on_error: bool
    timeout_seconds: float | None
    notes: str
    dry_run: bool
    no_plot: bool
    max_cases: int | None
    binary: str | None
    mpirun: str | None
    ranks: int | None
    circuit: str | None
    input_statevector: str | None
    output_bitstrings: str | None
    fraction: float | None
    batch_size: int | None
    verbosity: int | None
    feynman_env: dict[str, str] | None


@dataclass(frozen=True)
class RuntimeConfig:
    mpirun: str
    ranks: int
    fraction: float
    batch_size: int
    verbosity: int
    feynman_env: dict[str, str]


@dataclass(frozen=True)
class ProjectPaths:
    repo_root: Path
    output_root: Path
    base_config_path: Path
    binary: Path
    circuit: Path
    input_statevector: Path
    output_bitstrings: Path
    subset_indices: list[int]

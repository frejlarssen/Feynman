from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


VARY_CHOICES = ("ranks", "batch_size", "fraction", "threshold", "p", "r", "circuit_it")
FLOAT_SWEEP_PARAMS = {"fraction", "threshold"}
CASE_OVERRIDE_FIELDS = (
    "ranks",
    "batch_size",
    "fraction",
    "threshold",
    "p",
    "r",
    "verbosity",
    "dense",
)

PARAM_FIELDS = (
    "ranks",
    "batch_size",
    "fraction",
    "threshold",
    "p",
    "r",
    "verbosity",
    "dense",
)

METRIC_PATTERNS = {
    "num_simulate_calls": re.compile(r"Number of simulate calls:\s+(\d+)"),
    "total_simulate_calls_s": re.compile(
        r"Total clocktime for all simulate calls:\s+([0-9eE+.\-]+) seconds"
    ),
    "avg_simulate_call_s": re.compile(
        r"Average clocktime per simulate call:\s+([0-9eE+.\-]+) seconds"
    ),
    "total_sim_s": re.compile(
        r"Total clocktime sim for sv.cpp:\s+([0-9eE+.\-]+) seconds"
    ),
    "total_io_s": re.compile(
        r"Total clocktime writing to disk for sv.cpp:\s+([0-9eE+.\-]+) seconds"
    ),
    "total_full_s": re.compile(
        r"Total clocktime \(including I/O\) for sv.cpp:\s+([0-9eE+.\-]+) seconds"
    ),
    "autotune_time_s": re.compile(r"Autotuning time:\s+([0-9eE+.\-]+)\s+seconds"),
    "autotune_candidates": re.compile(r"Autotuning time:.*candidates=(\d+)"),
    "autotune_step_size": re.compile(r"Autotuning time:.*step_size=(\d+)"),
    "autotune_best_gate_ops_estimate": re.compile(
        r"Autotuning time:.*best_gate_ops_estimate=([0-9]+)"
    ),
    "active_workers": re.compile(r"active workers\s*=\s*(\d+)"),
    "omp_threads_per_worker": re.compile(r"OMP_THREADS per worker\s*=\s*(\d+)"),
}
METRIC_FIELDS = tuple(METRIC_PATTERNS.keys()) + (
    "total_gates",
    "chunk0_gates",
    "chunk1_gates",
    "chunk2_gates",
    "total_artificial_sources",
    "chunk0_artificial",
    "chunk1_artificial",
    "chunk2_artificial",
    "num_histories_estimate",
    "gate_ops_estimate",
)

SUMMARY_FIELDS = list(
    ("run_index", "repeat_index", "case_name", "varied_param", "varied_value")
    + PARAM_FIELDS
    + METRIC_FIELDS
    + (
        "returncode",
        "walltime_s",
        "run_dir",
        "output_file",
        "timing_file",
        "stdout_file",
        "stderr_file",
        "start_utc",
        "end_utc",
        "circuit_file_used",
        "command",
        "commit_short",
        "branch",
        "dirty",
    )
)

DEFAULT_OPTIONS: dict[str, Any] = {
    "experiment_name": None,
    "repo_root": ".",
    "vary": None,
    "values": None,
    "repeat": 1,
    "binary": "build-release/sv_prefetcher_subset_mpi.x",
    "mpirun": "mpirun",
    "circuit": None,
    "input_statevector": None,
    "output_bitstrings": None,
    "output_root": "data/outputs/experiments",
    "ranks": 1,
    "batch_size": 32,
    "fraction": 1.0,
    "threshold": 1e-8,
    "p": None,
    "r": None,
    "verbosity": 1,
    "dense": False,
    "timeout_seconds": None,
    "continue_on_error": False,
    "notes": "",
    "dry_run": False,
    "config": "",
    "cases": None,
}

REQUIRED_FIELDS = (
    "experiment_name",
    "vary",
    "values",
    "circuit",
    "input_statevector",
    "output_bitstrings",
)

NUMERIC_CASTS: dict[str, Any] = {
    "repeat": int,
    "ranks": int,
    "batch_size": int,
    "fraction": float,
    "threshold": float,
    "verbosity": int,
    "timeout_seconds": float,
    "p": int,
    "r": int,
}

SPECIAL_CHECKPOINT_POLICY_THIRDS = "thirds"

BOOLEAN_FIELDS = ("dense", "continue_on_error", "dry_run")


@dataclass(frozen=True)
class SweepConfig:
    config: str
    experiment_name: str
    repo_root: str
    vary: str
    values: list[Any]
    repeat: int
    binary: str
    mpirun: str
    circuit: Any
    input_statevector: Any
    output_bitstrings: Any
    output_root: str
    ranks: int
    batch_size: int
    fraction: float
    threshold: float
    p: int | None
    r: int | None
    verbosity: int
    dense: bool
    timeout_seconds: float | None
    continue_on_error: bool
    notes: str
    dry_run: bool
    cases: list[dict[str, Any]] | None


@dataclass(frozen=True)
class ProjectPaths:
    repo_root: Path
    binary: Path
    circuit: Path
    input_statevector: Path
    output_bitstrings: Path
    output_root: Path

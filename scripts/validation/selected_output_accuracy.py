#!/usr/bin/env python
"""Compare exact and approximate selected-output amplitudes on the same probe set."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import numpy as np
from plot_timebitstrings_hist import auto_plot_timing_file_histograms
from sweeplib.materialize import (
    infer_circuit_qubits,
    resolve_circuit_input,
    resolve_output_bitstrings_input,
    resolve_statevector_input,
)
from sweeplib.utils import experiment_tag_from_config
from validation.selected_output_accuracy_plotting import plot_selected_output_tradeoff


SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[2]
SWEEP_PARAMS = ("fraction", "threshold")
_AMP_RE = re.compile(
    r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\+([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)i$"
)
_INTERNAL_RUNTIME_RE = re.compile(
    r"Total clocktime \(including I/O\) for sv\.cpp:\s+([0-9eE+.\-]+) seconds"
)
_ABS_STATS_ARTIFACT_BASENAMES = (
    "contribution2AbsMinMax.csv",
    "contribution1AbsMinMax.csv",
    "contribution0AbsMinMax.csv",
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


def _format_sweep_value(value: float) -> str:
    return f"{float(value):.12g}"


def _default_case_name(*, fraction: float, threshold: float, vary: str | None) -> str:
    if vary == "fraction":
        return _sanitize(f"fraction_{_format_sweep_value(fraction)}")
    if vary == "threshold":
        return _sanitize(f"threshold_{_format_sweep_value(threshold)}")
    if abs(threshold) < 1e-300:
        return _sanitize(f"fraction_{_format_sweep_value(fraction)}")
    return _sanitize(
        "fraction_"
        f"{_format_sweep_value(fraction)}"
        "_threshold_"
        f"{_format_sweep_value(threshold)}"
    )


def _default_explicit_case_name(
    raw_case: dict[str, Any],
    *,
    defaults: dict[str, Any],
    idx: int,
) -> str:
    parts: list[str] = []
    if "fraction" in raw_case:
        parts.append(f"fraction_{_format_sweep_value(float(raw_case['fraction']))}")
    if "threshold" in raw_case:
        parts.append(f"threshold_{_format_sweep_value(float(raw_case['threshold']))}")
    if "population_estimator" in raw_case:
        parts.append(str(raw_case["population_estimator"]))
    if "history_seed" in raw_case and raw_case["history_seed"] is not None:
        parts.append(f"history_seed_{int(raw_case['history_seed'])}")
    if "history_seeds" in raw_case and raw_case["history_seeds"] is not None:
        seeds = "_".join(str(int(seed)) for seed in raw_case["history_seeds"])
        parts.append(f"history_seeds_{seeds}")
    if "batch_size" in raw_case and raw_case["batch_size"] is not None:
        parts.append(f"batch_size_{int(raw_case['batch_size'])}")
    if "dense" in raw_case:
        parts.append(f"dense_{bool(raw_case['dense'])}")
    if "verbosity" in raw_case and int(raw_case["verbosity"]) != int(defaults["verbosity"]):
        parts.append(f"verbosity_{int(raw_case['verbosity'])}")
    if not parts:
        return f"case_{idx:02d}"
    return _sanitize("_".join(parts))


def _normalize_run_case(
    raw_case: dict[str, Any],
    *,
    defaults: dict[str, Any],
    fallback_name: str | None,
) -> dict[str, Any]:
    fraction = float(raw_case.get("fraction", defaults["fraction"]))
    threshold = float(raw_case.get("threshold", defaults["threshold"]))
    name_raw = raw_case.get(
        "name",
        fallback_name
        if fallback_name is not None
        else _default_case_name(fraction=fraction, threshold=threshold, vary=None),
    )
    name = _sanitize(str(name_raw))
    verbosity = int(raw_case.get("verbosity", defaults["verbosity"]))
    batch_size_raw = raw_case.get("batch_size", defaults["batch_size"])
    batch_size = None if batch_size_raw is None else int(batch_size_raw)
    dense = bool(raw_case.get("dense", defaults["dense"]))
    population_estimator = str(
        raw_case.get("population_estimator", defaults["population_estimator"])
    )
    history_seed_raw = raw_case.get("history_seed", defaults["history_seed"])
    history_seed = None if history_seed_raw is None else int(history_seed_raw)
    history_seeds_raw = raw_case.get("history_seeds", defaults["history_seeds"])
    history_seeds = None
    if history_seeds_raw is not None:
        if not isinstance(history_seeds_raw, list) or not history_seeds_raw:
            raise ValueError(f"case {name!r}: history_seeds must be a non-empty array.")
        history_seeds = [int(seed) for seed in history_seeds_raw]

    if fraction <= 0.0 or fraction > 1.0:
        raise ValueError(f"case {name!r}: fraction must satisfy 0 < fraction <= 1")
    if threshold < 0.0:
        raise ValueError(f"case {name!r}: threshold must be >= 0")
    if verbosity < 0:
        raise ValueError(f"case {name!r}: verbosity must be >= 0")
    if batch_size is not None and batch_size < 0:
        raise ValueError(f"case {name!r}: batch_size must be >= 0")
    if population_estimator not in ("amplitude_square", "cross_seeded"):
        raise ValueError(
            f"case {name!r}: population_estimator must be one of "
            "'amplitude_square', 'cross_seeded'"
        )
    if history_seed is not None and history_seeds is not None:
        raise ValueError(f"case {name!r}: use either history_seed or history_seeds, not both.")

    normalized_history_seeds: list[int] = []
    if history_seed is not None:
        normalized_history_seeds = [history_seed]
    elif history_seeds is not None:
        normalized_history_seeds = history_seeds

    if population_estimator == "cross_seeded":
        if not normalized_history_seeds:
            normalized_history_seeds = [1, 2]
        if len(normalized_history_seeds) < 2:
            raise ValueError(
                f"case {name!r}: cross_seeded requires at least two history seeds."
            )
    elif len(normalized_history_seeds) > 1:
        raise ValueError(
            f"case {name!r}: amplitude_square accepts at most one history seed."
        )

    return {
        "name": name,
        "fraction": fraction,
        "threshold": threshold,
        "verbosity": verbosity,
        "batch_size": batch_size,
        "dense": dense,
        "population_estimator": population_estimator,
        "history_seed": normalized_history_seeds[0] if normalized_history_seeds else None,
        "history_seeds": normalized_history_seeds,
    }


def _parse_sweep_cases(cfg: dict[str, Any], *, defaults: dict[str, Any]) -> list[dict[str, Any]]:
    cases_raw = cfg.get("cases")
    vary_raw = cfg.get("vary")
    values_raw = cfg.get("values")

    if cases_raw is not None and (vary_raw is not None or values_raw is not None):
        raise ValueError("Use either explicit 'cases' or sweep-style 'vary'/'values', not both.")

    if cases_raw is not None:
        if not isinstance(cases_raw, list) or not cases_raw:
            raise ValueError("Config 'cases' must be a non-empty array.")
        cases: list[dict[str, Any]] = []
        seen_names: set[str] = set()
        for idx, raw_case in enumerate(cases_raw):
            if not isinstance(raw_case, dict):
                raise ValueError(f"cases[{idx}] must be an object.")
            case = _normalize_run_case(
                raw_case,
                defaults=defaults,
                fallback_name=_default_explicit_case_name(
                    raw_case,
                    defaults=defaults,
                    idx=idx,
                ),
            )
            if case["name"] in seen_names:
                raise ValueError(f"Duplicate case name: {case['name']}")
            seen_names.add(case["name"])
            cases.append(case)
        return cases

    if vary_raw is None or values_raw is None:
        raise ValueError("Config must define either 'cases' or both 'vary' and 'values'.")

    vary = str(vary_raw).strip()
    if vary not in SWEEP_PARAMS:
        raise ValueError(f"'vary' must be one of {SWEEP_PARAMS}, got: {vary!r}")
    if not isinstance(values_raw, list) or not values_raw:
        raise ValueError("'values' must be a non-empty array.")

    cases: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for idx, raw_value in enumerate(values_raw):
        value = float(raw_value)
        raw_case = {vary: value}
        case = _normalize_run_case(
            raw_case,
            defaults=defaults,
            fallback_name=_default_case_name(
                fraction=value if vary == "fraction" else float(defaults["fraction"]),
                threshold=value if vary == "threshold" else float(defaults["threshold"]),
                vary=vary,
            ),
        )
        if case["name"] in seen_names:
            raise ValueError(
                f"Duplicate auto-generated case name {case['name']!r} at values[{idx}]."
            )
        seen_names.add(case["name"])
        cases.append(case)
    return cases


def _merge_config(args: argparse.Namespace) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    if args.config:
        cfg = _load_json(Path(args.config).resolve())

    defaults = {
        "fraction": float(_pick(cfg, "fraction", args.fraction, 1.0)),
        "threshold": float(_pick(cfg, "threshold", args.threshold, 0.0)),
        "verbosity": int(_pick(cfg, "verbosity", args.verbosity, 1)),
        "batch_size": _pick(cfg, "batch_size", args.batch_size, None),
        "dense": bool(_pick(cfg, "dense", args.dense, False)),
        "population_estimator": str(_pick(cfg, "population_estimator", None, "amplitude_square")),
        "history_seed": _pick(cfg, "history_seed", None, None),
        "history_seeds": _pick(cfg, "history_seeds", None, None),
    }
    if defaults["batch_size"] is not None:
        defaults["batch_size"] = int(defaults["batch_size"])

    compute_reference = bool(cfg.get("compute_reference", True))
    if args.skip_reference:
        compute_reference = False

    reference = None
    if compute_reference:
        reference_raw = cfg.get("reference", {}) or {}
        if not isinstance(reference_raw, dict):
            raise ValueError("'reference' must be an object when present.")
        reference_defaults = dict(defaults)
        reference_defaults["fraction"] = 1.0
        reference_defaults["threshold"] = 0.0
        reference_defaults["population_estimator"] = "amplitude_square"
        if defaults["history_seed"] is not None:
            reference_defaults["history_seed"] = defaults["history_seed"]
        elif defaults["history_seeds"] is not None and defaults["history_seeds"]:
            reference_defaults["history_seed"] = int(defaults["history_seeds"][0])
        else:
            reference_defaults["history_seed"] = 1
        reference_defaults["history_seeds"] = None
        reference = _normalize_run_case(
            reference_raw,
            defaults=reference_defaults,
            fallback_name="exact_reference",
        )
        if reference["population_estimator"] != "amplitude_square":
            raise ValueError("Reference run must use population_estimator='amplitude_square'.")

    cases = _parse_sweep_cases(cfg, defaults=defaults)

    merged = {
        "description": _pick(cfg, "description", args.description, ""),
        "repo_root": str(_pick(cfg, "repo_root", args.repo_root, SCRIPT_REPO_ROOT)),
        "output_root": str(_pick(cfg, "output_root", args.output_root, "data/outputs/validation")),
        "binary": str(_pick(cfg, "binary", args.binary, "build-cloud/cloud_task.x")),
        "mpirun": str(_pick(cfg, "mpirun", args.mpirun, "mpirun")),
        "ranks": int(_pick(cfg, "ranks", args.ranks, 1)),
        "feynman_env": dict(_pick(cfg, "feynman_env", None, {}) or {}),
        "circuit": _pick(cfg, "circuit", args.circuit, None),
        "input_statevector": _pick(cfg, "input_statevector", args.input_statevector, None),
        "output_bitstrings": _pick(cfg, "output_bitstrings", args.output_bitstrings, None),
        "nonzero_eps": float(_pick(cfg, "nonzero_eps", args.nonzero_eps, 1e-12)),
        "compute_reference": compute_reference,
        "vary": cfg.get("vary"),
        "values": list(cfg.get("values", [])) if isinstance(cfg.get("values"), list) else None,
        "defaults": defaults,
        "reference": reference,
        "cases": cases,
    }
    for key in ("circuit", "input_statevector", "output_bitstrings"):
        if not merged[key]:
            raise ValueError(f"Missing required parameter: {key}")
    if merged["ranks"] < 1:
        raise ValueError("ranks must be >= 1")
    if merged["nonzero_eps"] < 0.0:
        raise ValueError("nonzero_eps must be >= 0")
    merged["experiment_tag"] = experiment_tag_from_config(
        str(args.config.resolve()) if args.config else None,
        fallback="selected_output_accuracy",
    )
    return merged


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


def _binary_supports_batch_size(binary: Path) -> bool:
    return binary.name != "cloud_task.x"


def _binary_requires_mpirun(binary: Path) -> bool:
    return "mpi" in binary.name


def _parse_internal_runtime(stdout: str) -> float | None:
    match = _INTERNAL_RUNTIME_RE.search(stdout)
    if not match:
        return None
    return float(match.group(1))


def _archive_abs_stats_files(case_dir: Path, component_label: str) -> dict[str, Path]:
    archived: dict[str, Path] = {}
    for basename in _ABS_STATS_ARTIFACT_BASENAMES:
        path = case_dir / basename
        if not path.exists():
            continue
        archived_path = case_dir / f"{component_label}.{basename}"
        path.replace(archived_path)
        archived[path.stem] = archived_path
    return archived


def _collect_abs_stats_files(runs: list[dict[str, Any]]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {}
    for run in runs:
        for stem, path in run.get("abs_stats_files", {}).items():
            merged.setdefault(str(stem), []).append(str(path))
    return merged


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
    batch_size: int | None,
    dense: bool,
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
    if batch_size is not None and _binary_supports_batch_size(binary):
        run_args.extend(["-s", str(batch_size)])
    if dense:
        run_args.append("-D")
    if ranks == 1 and not _binary_requires_mpirun(binary):
        return run_args
    return [mpirun, "-n", str(ranks), *run_args]


def _run_case(
    *,
    repo_root: Path,
    binary: Path,
    mpirun: str,
    ranks: int,
    circuit: Path,
    input_statevector: Path,
    output_bitstrings: Path,
    feynman_env: dict[str, str],
    case: dict[str, Any],
    run_dir: Path,
) -> dict[str, Any]:
    case_dir = run_dir / "cases" / case["name"]
    case_dir.mkdir(parents=True, exist_ok=True)
    component_label = "output"
    if case.get("history_seed") is not None:
        component_label = f"seed_{int(case['history_seed'])}"
    output_file = case_dir / f"{component_label}.hsv"
    cmd = _build_command(
        binary=binary,
        mpirun=mpirun,
        ranks=ranks,
        circuit=circuit,
        input_statevector=input_statevector,
        output_bitstrings=output_bitstrings,
        output_file=output_file,
        fraction=float(case["fraction"]),
        threshold=float(case["threshold"]),
        verbosity=int(case["verbosity"]),
        batch_size=case["batch_size"],
        dense=bool(case["dense"]),
    )
    env = os.environ.copy()
    env.update({str(key): str(value) for key, value in feynman_env.items()})
    if case.get("history_seed") is not None:
        env["FEYNMAN_HISTORY_SEED"] = str(case["history_seed"])

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

    stdout_log = case_dir / f"{component_label}.stdout.log"
    stderr_log = case_dir / f"{component_label}.stderr.log"
    command_log = case_dir / f"{component_label}.command.txt"
    stdout_log.write_text(proc.stdout, encoding="utf-8")
    stderr_log.write_text(proc.stderr, encoding="utf-8")
    command_log.write_text(shlex.join(cmd) + "\n", encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(
            f"Run case {case['name']!r} failed with return code {proc.returncode}. "
            f"See {stderr_log}"
        )
    if not output_file.exists():
        raise RuntimeError(
            f"Run case {case['name']!r} did not produce {output_file}. "
            f"See {stdout_log} and {stderr_log}"
        )

    timing_file = case_dir / "timeBitstrings.csv"
    archived_timing_file: Path | None = None
    timing_histograms: list[Path] = []
    if timing_file.exists():
        archived_timing_file = case_dir / f"{component_label}.timeBitstrings.csv"
        timing_file.replace(archived_timing_file)
        timing_histograms = auto_plot_timing_file_histograms(
            timing_file=archived_timing_file,
            title=f"Bitstrings compute time distribution ({case['name']}, {component_label})",
        )
    archived_abs_stats_files = _archive_abs_stats_files(case_dir, component_label)

    return {
        "name": case["name"],
        "fraction": float(case["fraction"]),
        "threshold": float(case["threshold"]),
        "verbosity": int(case["verbosity"]),
        "batch_size": case["batch_size"],
        "dense": bool(case["dense"]),
        "dir": case_dir,
        "output_file": output_file,
        "stdout_log": stdout_log,
        "stderr_log": stderr_log,
        "command_log": command_log,
        "history_seed": case.get("history_seed"),
        "timing_file": archived_timing_file,
        "timing_histograms": timing_histograms,
        "abs_stats_files": archived_abs_stats_files,
        "contribution0_abs_stats_file": archived_abs_stats_files.get("contribution0AbsMinMax"),
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "wall_time_s": wall_time_s,
        "internal_runtime_s": _parse_internal_runtime(proc.stdout),
        "sparse": parse_hsv_sparse(output_file),
    }


def _run_cache_key(
    *,
    binary: Path,
    mpirun: str,
    ranks: int,
    circuit: Path,
    input_statevector: Path,
    output_bitstrings: Path,
    feynman_env: dict[str, str],
    case: dict[str, Any],
) -> tuple[Any, ...]:
    return (
        str(binary.resolve()),
        str(mpirun),
        int(ranks),
        str(circuit.resolve()),
        str(input_statevector.resolve()),
        str(output_bitstrings.resolve()),
        tuple(sorted((str(key), str(value)) for key, value in feynman_env.items())),
        float(case["fraction"]),
        float(case["threshold"]),
        int(case["verbosity"]),
        None if case["batch_size"] is None else int(case["batch_size"]),
        bool(case["dense"]),
        None if case.get("history_seed") is None else int(case["history_seed"]),
    )


def _run_case_cached(
    *,
    repo_root: Path,
    binary: Path,
    mpirun: str,
    ranks: int,
    circuit: Path,
    input_statevector: Path,
    output_bitstrings: Path,
    feynman_env: dict[str, str],
    case: dict[str, Any],
    run_dir: Path,
    run_cache: dict[tuple[Any, ...], dict[str, Any]],
) -> dict[str, Any]:
    key = _run_cache_key(
        binary=binary,
        mpirun=mpirun,
        ranks=ranks,
        circuit=circuit,
        input_statevector=input_statevector,
        output_bitstrings=output_bitstrings,
        feynman_env=feynman_env,
        case=case,
    )
    cached = run_cache.get(key)
    if cached is not None:
        return dict(cached)

    result = _run_case(
        repo_root=repo_root,
        binary=binary,
        mpirun=mpirun,
        ranks=ranks,
        circuit=circuit,
        input_statevector=input_statevector,
        output_bitstrings=output_bitstrings,
        feynman_env=feynman_env,
        case=case,
        run_dir=run_dir,
    )
    run_cache[key] = dict(result)
    return result


def _compute_metrics(
    *,
    subset_indices: list[int],
    reference_vec: np.ndarray,
    approx_vec: np.ndarray | None,
    approx_pop: np.ndarray,
    nonzero_eps: float,
) -> dict[str, Any]:
    ref_abs = np.abs(reference_vec)
    ref_pop = ref_abs**2
    cur_pop = approx_pop
    pop_nonzero_eps = nonzero_eps * nonzero_eps
    abs_pop_err = np.abs(cur_pop - ref_pop)
    cur_pop_nonnegative = np.clip(cur_pop, 0.0, None)

    ref_norm = float(np.vdot(reference_vec, reference_vec).real)
    approx_selected_mass = float(np.sum(cur_pop))
    approx_nonnegative_selected_mass = float(np.sum(cur_pop_nonnegative))
    negative_population_count = int(np.count_nonzero(cur_pop < 0.0))

    cur_abs = None
    abs_amp_err = None
    cur_norm = None
    l2_abs_error = None
    weighted_relative_l2_error = None
    amplitude_fidelity = None
    mean_relative_abs_amp_error_on_reference_support = None
    if approx_vec is not None:
        cur_abs = np.abs(approx_vec)
        diff = approx_vec - reference_vec
        abs_amp_err = np.abs(diff)
        cur_norm = float(np.vdot(approx_vec, approx_vec).real)
        l2_abs_error = float(np.linalg.norm(diff))
        weighted_relative_l2_error = (
            None if ref_norm <= 0.0 else float(l2_abs_error / np.sqrt(ref_norm))
        )
        if ref_norm > 0.0 and cur_norm > 0.0:
            overlap = np.vdot(reference_vec, approx_vec)
            amplitude_fidelity = float((abs(overlap) ** 2) / (ref_norm * cur_norm))

    ref_mask = ref_abs > nonzero_eps
    if cur_abs is not None:
        cur_mask = cur_abs > nonzero_eps
    else:
        cur_mask = cur_pop > pop_nonzero_eps
    ref_nonzero_count = int(np.count_nonzero(ref_mask))
    cur_nonzero_count = int(np.count_nonzero(cur_mask))
    support_intersection = int(np.count_nonzero(ref_mask & cur_mask))
    support_retention = (
        None if ref_nonzero_count == 0 else float(support_intersection / ref_nonzero_count)
    )
    support_precision = (
        None if cur_nonzero_count == 0 else float(support_intersection / cur_nonzero_count)
    )

    if abs_amp_err is not None and ref_nonzero_count > 0:
        mean_relative_abs_amp_error_on_reference_support = float(
            np.mean(abs_amp_err[ref_mask] / ref_abs[ref_mask])
        )

    ref_selected_mass = float(np.sum(ref_pop))
    mass_retention = None if ref_selected_mass <= 0.0 else float(approx_selected_mass / ref_selected_mass)
    nonnegative_mass_retention = (
        None
        if ref_selected_mass <= 0.0
        else float(approx_nonnegative_selected_mass / ref_selected_mass)
    )
    population_fidelity = None
    if ref_selected_mass > 0.0 and approx_nonnegative_selected_mass > 0.0:
        population_fidelity = float(
            (np.sum(np.sqrt(ref_pop * cur_pop_nonnegative)) ** 2)
            / (ref_selected_mass * approx_nonnegative_selected_mass)
        )

    fidelity_metric = "amplitude_overlap" if amplitude_fidelity is not None else "selected_population_bhattacharyya"
    fidelity_to_reference = (
        amplitude_fidelity if amplitude_fidelity is not None else population_fidelity
    )

    return {
        "subset_size": len(subset_indices),
        "reference_nonzero_count": ref_nonzero_count,
        "approx_nonzero_count": cur_nonzero_count,
        "support_intersection_count": support_intersection,
        "support_retention": support_retention,
        "support_precision": support_precision,
        "reference_selected_mass": ref_selected_mass,
        "approx_selected_mass": approx_selected_mass,
        "approx_nonnegative_selected_mass": approx_nonnegative_selected_mass,
        "mass_retention": mass_retention,
        "nonnegative_mass_retention": nonnegative_mass_retention,
        "negative_population_count": negative_population_count,
        "fidelity_metric": fidelity_metric,
        "fidelity_to_reference": fidelity_to_reference,
        "amplitude_fidelity_to_reference": amplitude_fidelity,
        "selected_population_fidelity_to_reference": population_fidelity,
        "l2_abs_error": l2_abs_error,
        "weighted_relative_l2_error": weighted_relative_l2_error,
        "max_abs_amp_error": (
            float(np.max(abs_amp_err)) if abs_amp_err is not None and abs_amp_err.size else None
        ),
        "mean_abs_amp_error": (
            float(np.mean(abs_amp_err)) if abs_amp_err is not None and abs_amp_err.size else None
        ),
        "max_abs_population_error": float(np.max(abs_pop_err)) if abs_pop_err.size else 0.0,
        "mean_abs_population_error": float(np.mean(abs_pop_err)) if abs_pop_err.size else 0.0,
        "mean_relative_abs_amp_error_on_reference_support": (
            mean_relative_abs_amp_error_on_reference_support
        ),
    }


def _compute_metrics_without_reference(
    *,
    subset_indices: list[int],
    approx_vec: np.ndarray | None,
    approx_pop: np.ndarray,
    nonzero_eps: float,
) -> dict[str, Any]:
    pop_nonzero_eps = nonzero_eps * nonzero_eps
    cur_pop_nonnegative = np.clip(approx_pop, 0.0, None)
    approx_selected_mass = float(np.sum(approx_pop))
    approx_nonnegative_selected_mass = float(np.sum(cur_pop_nonnegative))
    negative_population_count = int(np.count_nonzero(approx_pop < 0.0))

    if approx_vec is not None:
        cur_nonzero_count = int(np.count_nonzero(np.abs(approx_vec) > nonzero_eps))
    else:
        cur_nonzero_count = int(np.count_nonzero(approx_pop > pop_nonzero_eps))

    return {
        "subset_size": len(subset_indices),
        "reference_nonzero_count": None,
        "approx_nonzero_count": cur_nonzero_count,
        "support_intersection_count": None,
        "support_retention": None,
        "support_precision": None,
        "reference_selected_mass": None,
        "approx_selected_mass": approx_selected_mass,
        "approx_nonnegative_selected_mass": approx_nonnegative_selected_mass,
        "mass_retention": None,
        "nonnegative_mass_retention": None,
        "negative_population_count": negative_population_count,
        "fidelity_metric": None,
        "fidelity_to_reference": None,
        "amplitude_fidelity_to_reference": None,
        "selected_population_fidelity_to_reference": None,
        "l2_abs_error": None,
        "weighted_relative_l2_error": None,
        "max_abs_amp_error": None,
        "mean_abs_amp_error": None,
        "max_abs_population_error": None,
        "mean_abs_population_error": None,
        "mean_relative_abs_amp_error_on_reference_support": None,
    }


def _build_summary_row(
    *,
    case_name: str,
    run_result: dict[str, Any],
    metrics: dict[str, Any],
) -> dict[str, Any]:
    return {
        "case_name": case_name,
        "fraction": run_result["fraction"],
        "threshold": run_result["threshold"],
        "population_estimator": run_result["population_estimator"],
        "history_seeds": ",".join(str(seed) for seed in run_result["history_seeds"]),
        "component_runs": len(run_result["component_runs"]),
        "wall_time_s": run_result["wall_time_s"],
        "internal_runtime_s": run_result["internal_runtime_s"],
        **metrics,
        "output_file": str(run_result["output_file"]),
        "stdout_log": str(run_result["stdout_log"]),
        "stderr_log": str(run_result["stderr_log"]),
    }


def _jsonable(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    return value


def _write_reference_csv(
    *,
    path: Path,
    subset_indices: list[int],
    size_bytes: int,
    reference_vec: np.ndarray,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "ordinal",
                "bitstring_hex",
                "reference_real",
                "reference_imag",
                "reference_population",
            ]
        )
        for ordinal, idx in enumerate(subset_indices):
            amp = reference_vec[ordinal]
            writer.writerow(
                [
                    ordinal,
                    f"0x{idx:0{size_bytes * 2}X}",
                    f"{amp.real:.18e}",
                    f"{amp.imag:.18e}",
                    f"{float(np.abs(amp) ** 2):.18e}",
                ]
            )


def _write_comparison_csv(
    *,
    path: Path,
    subset_indices: list[int],
    size_bytes: int,
    reference_vec: np.ndarray,
    case_records: dict[str, dict[str, Any]],
    nonzero_eps: float,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "case_name",
                "population_estimator",
                "ordinal",
                "bitstring_hex",
                "reference_real",
                "reference_imag",
                "reference_population",
                "approx_real",
                "approx_imag",
                "approx_population",
                "abs_amp_error",
                "abs_population_error",
                "relative_abs_amp_error",
                "reference_nonzero",
                "approx_nonzero",
            ]
        )
        ref_abs = np.abs(reference_vec)
        ref_pop = ref_abs**2
        pop_nonzero_eps = nonzero_eps * nonzero_eps
        for case_name, case_record in case_records.items():
            case_vec = case_record["approx_vec"]
            cur_pop = case_record["approx_pop"]
            cur_abs = None if case_vec is None else np.abs(case_vec)
            abs_amp_err = None if case_vec is None else np.abs(case_vec - reference_vec)
            abs_pop_err = np.abs(cur_pop - ref_pop)
            for ordinal, idx in enumerate(subset_indices):
                rel_err = ""
                if abs_amp_err is not None and ref_abs[ordinal] > nonzero_eps:
                    rel_err = f"{float(abs_amp_err[ordinal] / ref_abs[ordinal]):.18e}"
                writer.writerow(
                    [
                        case_name,
                        case_record["population_estimator"],
                        ordinal,
                        f"0x{idx:0{size_bytes * 2}X}",
                        f"{reference_vec[ordinal].real:.18e}",
                        f"{reference_vec[ordinal].imag:.18e}",
                        f"{float(ref_pop[ordinal]):.18e}",
                        "" if case_vec is None else f"{case_vec[ordinal].real:.18e}",
                        "" if case_vec is None else f"{case_vec[ordinal].imag:.18e}",
                        f"{float(cur_pop[ordinal]):.18e}",
                        "" if abs_amp_err is None else f"{float(abs_amp_err[ordinal]):.18e}",
                        f"{float(abs_pop_err[ordinal]):.18e}",
                        rel_err,
                        int(ref_abs[ordinal] > nonzero_eps),
                        int(
                            (cur_abs[ordinal] > nonzero_eps)
                            if cur_abs is not None
                            else (cur_pop[ordinal] > pop_nonzero_eps)
                        ),
                    ]
                )


def _write_summary_csv(path: Path, case_rows: list[dict[str, Any]]) -> None:
    if not case_rows:
        raise ValueError("No case rows to write.")
    fieldnames = [
        "case_name",
        "fraction",
        "threshold",
        "population_estimator",
        "history_seeds",
        "component_runs",
        "wall_time_s",
        "internal_runtime_s",
        "subset_size",
        "reference_nonzero_count",
        "approx_nonzero_count",
        "support_intersection_count",
        "support_retention",
        "support_precision",
        "reference_selected_mass",
        "approx_selected_mass",
        "approx_nonnegative_selected_mass",
        "mass_retention",
        "nonnegative_mass_retention",
        "negative_population_count",
        "fidelity_metric",
        "fidelity_to_reference",
        "amplitude_fidelity_to_reference",
        "selected_population_fidelity_to_reference",
        "weighted_relative_l2_error",
        "l2_abs_error",
        "max_abs_amp_error",
        "mean_abs_amp_error",
        "max_abs_population_error",
        "mean_abs_population_error",
        "mean_relative_abs_amp_error_on_reference_support",
        "output_file",
        "stdout_log",
        "stderr_log",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in case_rows:
            writer.writerow({key: _jsonable(row.get(key, "")) for key in fieldnames})


def _cross_seeded_population(component_vectors: list[np.ndarray]) -> np.ndarray:
    if len(component_vectors) < 2:
        raise ValueError("cross_seeded population estimator requires at least two amplitude vectors.")
    accum = np.zeros(component_vectors[0].shape, dtype=np.float64)
    pair_count = 0
    for i in range(len(component_vectors)):
        for j in range(i + 1, len(component_vectors)):
            accum += np.real(component_vectors[i] * np.conjugate(component_vectors[j]))
            pair_count += 1
    if pair_count == 0:
        raise ValueError("cross_seeded population estimator found zero seed pairs.")
    return accum / float(pair_count)


def _run_case_estimator(
    *,
    repo_root: Path,
    binary: Path,
    mpirun: str,
    ranks: int,
    circuit: Path,
    input_statevector: Path,
    output_bitstrings: Path,
    feynman_env: dict[str, str],
    case: dict[str, Any],
    run_dir: Path,
    subset_indices: list[int],
    size_bytes: int,
    run_cache: dict[tuple[Any, ...], dict[str, Any]],
) -> dict[str, Any]:
    estimator = str(case["population_estimator"])
    history_seeds = list(case["history_seeds"])
    component_runs: list[dict[str, Any]] = []

    if estimator == "cross_seeded":
        for history_seed in history_seeds:
            component_case = dict(case)
            component_case["history_seed"] = history_seed
            component_case["history_seeds"] = [history_seed]
            component_runs.append(
                _run_case_cached(
                    repo_root=repo_root,
                    binary=binary,
                    mpirun=mpirun,
                    ranks=ranks,
                    circuit=circuit,
                    input_statevector=input_statevector,
                    output_bitstrings=output_bitstrings,
                    feynman_env=feynman_env,
                    case=component_case,
                    run_dir=run_dir,
                    run_cache=run_cache,
                )
            )
        component_vectors = [
            _ordered_vector(component_run["sparse"], subset_indices)
            for component_run in component_runs
        ]
        approx_pop = _cross_seeded_population(component_vectors)
        case_dir = run_dir / "cases" / case["name"]
        case_dir.mkdir(parents=True, exist_ok=True)
        population_file = case_dir / "population_estimate.csv"
        with population_file.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(["ordinal", "bitstring_hex", "approx_population"])
            for ordinal, idx in enumerate(subset_indices):
                writer.writerow(
                    [
                        ordinal,
                        f"0x{idx:0{size_bytes * 2}X}",
                        f"{float(approx_pop[ordinal]):.18e}",
                    ]
                )
        sources_file = case_dir / "population_estimate.sources.txt"
        sources_file.write_text(
            "".join(
                f"{run['name']}: seed={run.get('history_seed')} output={run['output_file']}\n"
                for run in component_runs
            ),
            encoding="utf-8",
        )
        return {
            "name": case["name"],
            "fraction": float(case["fraction"]),
            "threshold": float(case["threshold"]),
            "verbosity": int(case["verbosity"]),
            "batch_size": case["batch_size"],
            "dense": bool(case["dense"]),
            "population_estimator": estimator,
            "history_seeds": history_seeds,
            "component_runs": component_runs,
            "dir": case_dir,
            "output_file": population_file,
            "stdout_log": component_runs[0]["stdout_log"],
            "stderr_log": component_runs[0]["stderr_log"],
            "timing_files": [
                str(run["timing_file"]) for run in component_runs if run.get("timing_file") is not None
            ],
            "timing_histograms": [
                str(path)
                for run in component_runs
                for path in run.get("timing_histograms", [])
            ],
            "abs_stats_files": _collect_abs_stats_files(component_runs),
            "contribution0_abs_stats_files": [
                str(run["contribution0_abs_stats_file"])
                for run in component_runs
                if run.get("contribution0_abs_stats_file") is not None
            ],
            "approx_vec": None,
            "approx_pop": approx_pop,
            "wall_time_s": float(sum(run["wall_time_s"] for run in component_runs)),
            "internal_runtime_s": (
                float(sum(run["internal_runtime_s"] for run in component_runs))
                if all(run["internal_runtime_s"] is not None for run in component_runs)
                else None
            ),
        }

    single_run = _run_case_cached(
        repo_root=repo_root,
        binary=binary,
        mpirun=mpirun,
        ranks=ranks,
        circuit=circuit,
        input_statevector=input_statevector,
        output_bitstrings=output_bitstrings,
        feynman_env=feynman_env,
        case=case,
        run_dir=run_dir,
        run_cache=run_cache,
    )
    approx_vec = _ordered_vector(single_run["sparse"], subset_indices)
    return {
        "name": case["name"],
        "fraction": float(case["fraction"]),
        "threshold": float(case["threshold"]),
        "verbosity": int(case["verbosity"]),
        "batch_size": case["batch_size"],
        "dense": bool(case["dense"]),
        "population_estimator": estimator,
        "history_seeds": history_seeds,
        "component_runs": [single_run],
        "dir": single_run["dir"],
        "output_file": single_run["output_file"],
        "stdout_log": single_run["stdout_log"],
        "stderr_log": single_run["stderr_log"],
        "timing_files": (
            [str(single_run["timing_file"])] if single_run.get("timing_file") is not None else []
        ),
        "timing_histograms": [str(path) for path in single_run.get("timing_histograms", [])],
        "abs_stats_files": _collect_abs_stats_files([single_run]),
        "contribution0_abs_stats_files": (
            [str(single_run["contribution0_abs_stats_file"])]
            if single_run.get("contribution0_abs_stats_file") is not None
            else []
        ),
        "approx_vec": approx_vec,
        "approx_pop": np.abs(approx_vec) ** 2,
        "wall_time_s": single_run["wall_time_s"],
        "internal_runtime_s": single_run["internal_runtime_s"],
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare exact and approximate selected-output amplitudes on the same bitstrings."
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
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--verbosity", type=int, default=None)
    parser.add_argument("--dense", action="store_true", default=None)
    parser.add_argument("--nonzero-eps", type=float, default=None)
    parser.add_argument(
        "--plot-only",
        action="store_true",
        help="Regenerate the fraction tradeoff plot from an existing summary/comparison pair.",
    )
    parser.add_argument("--summary-csv", type=Path, default=None)
    parser.add_argument("--comparison-csv", type=Path, default=None)
    parser.add_argument("--plot-output", type=Path, default=None)
    parser.add_argument("--plot-title", default=None)
    parser.add_argument("--label-fontsize", type=float, default=None)
    parser.add_argument("--time-column", default="internal_runtime_s")
    parser.add_argument(
        "--plot-fidelity-loss",
        action="store_true",
        help="Plot fidelity loss 1-F on a logarithmic y-axis instead of fidelity.",
    )
    parser.add_argument(
        "--plot-exclude-threshold",
        action="append",
        type=float,
        default=[],
        help="Threshold value to omit from a plot-only figure; may be repeated.",
    )
    parser.add_argument(
        "--skip-reference",
        action="store_true",
        help="Skip the exact reference run and leave reference-dependent outputs blank.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.plot_only:
        if args.summary_csv is None:
            raise ValueError("--plot-only requires --summary-csv.")
        saved_path = plot_selected_output_tradeoff(
            summary_csv=args.summary_csv,
            comparison_csv=args.comparison_csv,
            output=args.plot_output,
            time_column=args.time_column,
            title=args.plot_title,
            label_fontsize=args.label_fontsize,
            exclude_thresholds=tuple(args.plot_exclude_threshold),
            plot_fidelity_loss=args.plot_fidelity_loss,
        )
        print(f"Saved plot: {saved_path}")
        return 0

    cfg = _merge_config(args)
    config_stem = Path(args.config).resolve().stem if args.config else str(cfg["experiment_tag"])

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
    if not binary.exists():
        raise FileNotFoundError(f"Binary not found: {binary}")

    subset_indices, size_bytes = parse_hs(output_bitstrings)

    run_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
    reference_run: dict[str, Any] | None = None
    reference_vec: np.ndarray | None = None
    case_records: dict[str, dict[str, Any]] = {}
    case_rows: list[dict[str, Any]] = []

    if bool(cfg["compute_reference"]):
        reference_run = _run_case_estimator(
            repo_root=repo_root,
            binary=binary,
            mpirun=str(cfg["mpirun"]),
            ranks=int(cfg["ranks"]),
            circuit=circuit,
            input_statevector=input_statevector,
            output_bitstrings=output_bitstrings,
            feynman_env={str(k): str(v) for k, v in cfg["feynman_env"].items()},
            case=cfg["reference"],
            run_dir=run_dir,
            subset_indices=subset_indices,
            size_bytes=size_bytes,
            run_cache=run_cache,
        )
        reference_vec = reference_run["approx_vec"]
        if reference_vec is None:
            raise RuntimeError("Reference run must produce amplitudes.")

        reference_metrics = _compute_metrics(
            subset_indices=subset_indices,
            reference_vec=reference_vec,
            approx_vec=reference_vec,
            approx_pop=np.abs(reference_vec) ** 2,
            nonzero_eps=float(cfg["nonzero_eps"]),
        )
        case_rows.append(
            _build_summary_row(
                case_name=reference_run["name"],
                run_result=reference_run,
                metrics=reference_metrics,
            )
        )
    for case in cfg["cases"]:
        case_run = _run_case_estimator(
            repo_root=repo_root,
            binary=binary,
            mpirun=str(cfg["mpirun"]),
            ranks=int(cfg["ranks"]),
            circuit=circuit,
            input_statevector=input_statevector,
            output_bitstrings=output_bitstrings,
            feynman_env={str(k): str(v) for k, v in cfg["feynman_env"].items()},
            case=case,
            run_dir=run_dir,
            subset_indices=subset_indices,
            size_bytes=size_bytes,
            run_cache=run_cache,
        )
        if reference_vec is not None:
            case_records[case["name"]] = {
                "approx_vec": case_run["approx_vec"],
                "approx_pop": case_run["approx_pop"],
                "population_estimator": case_run["population_estimator"],
            }
            metrics = _compute_metrics(
                subset_indices=subset_indices,
                reference_vec=reference_vec,
                approx_vec=case_run["approx_vec"],
                approx_pop=case_run["approx_pop"],
                nonzero_eps=float(cfg["nonzero_eps"]),
            )
        else:
            metrics = _compute_metrics_without_reference(
                subset_indices=subset_indices,
                approx_vec=case_run["approx_vec"],
                approx_pop=case_run["approx_pop"],
                nonzero_eps=float(cfg["nonzero_eps"]),
            )
        case_rows.append(
            _build_summary_row(
                case_name=case["name"],
                run_result=case_run,
                metrics=metrics,
            )
        )

    reference_csv: Path | None = None
    comparison_csv: Path | None = None
    summary_csv = run_dir / "summary.csv"
    if reference_vec is not None:
        reference_csv = run_dir / "reference_outputs.csv"
        comparison_csv = run_dir / "comparison.csv"
        _write_reference_csv(
            path=reference_csv,
            subset_indices=subset_indices,
            size_bytes=size_bytes,
            reference_vec=reference_vec,
        )
        _write_comparison_csv(
            path=comparison_csv,
            subset_indices=subset_indices,
            size_bytes=size_bytes,
            reference_vec=reference_vec,
            case_records=case_records,
            nonzero_eps=float(cfg["nonzero_eps"]),
        )
    _write_summary_csv(summary_csv, case_rows)
    tradeoff_plot_path: Path | None = None
    if comparison_csv is not None:
        try:
            tradeoff_plot_path = plot_selected_output_tradeoff(
                summary_csv=summary_csv,
                comparison_csv=comparison_csv,
                time_column=args.time_column,
                label_fontsize=args.label_fontsize,
                plot_fidelity_loss=args.plot_fidelity_loss,
            )
        except ValueError:
            tradeoff_plot_path = None

    summary = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "experiment_tag": cfg["experiment_tag"],
        "config": cfg,
        "config_file": str(Path(args.config).resolve()) if args.config else None,
        "paths": {
            "run_dir": str(run_dir),
            "binary": str(binary),
            "circuit": str(circuit),
            "input_statevector": str(input_statevector),
            "output_bitstrings": str(output_bitstrings),
            "reference_output": (
                str(reference_run["output_file"]) if reference_run is not None else None
            ),
            "reference_outputs_csv": str(reference_csv) if reference_csv is not None else None,
            "comparison_csv": str(comparison_csv) if comparison_csv is not None else None,
            "summary_csv": str(summary_csv),
            "selected_output_tradeoff_plot": str(tradeoff_plot_path) if tradeoff_plot_path else None,
        },
        "generated_inputs": {
            "circuit": circuit_generated,
            "input_statevector": input_generated,
            "output_bitstrings": output_generated,
        },
        "reference": (
            {
                "name": reference_run["name"],
                "fraction": reference_run["fraction"],
                "threshold": reference_run["threshold"],
                "wall_time_s": reference_run["wall_time_s"],
                "internal_runtime_s": reference_run["internal_runtime_s"],
                "output_file": str(reference_run["output_file"]),
                "timing_files": reference_run.get("timing_files", []),
                "timing_histograms": reference_run.get("timing_histograms", []),
                "abs_stats_files": reference_run.get("abs_stats_files", {}),
                "contribution0_abs_stats_files": reference_run.get(
                    "contribution0_abs_stats_files", []
                ),
            }
            if reference_run is not None
            else None
        ),
        "cases": case_rows,
    }
    summary_json = run_dir / "summary.json"
    summary_json.write_text(
        json.dumps(summary, indent=2, default=_jsonable) + "\n",
        encoding="utf-8",
    )

    print(f"Run directory: {run_dir}")
    print(f"Summary CSV: {summary_csv}")
    if comparison_csv is not None:
        print(f"Comparison CSV: {comparison_csv}")
    if tradeoff_plot_path is not None:
        print(f"Tradeoff plot: {tradeoff_plot_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

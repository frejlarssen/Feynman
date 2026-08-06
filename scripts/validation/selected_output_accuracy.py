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
import time
from pathlib import Path
from typing import Any

import numpy as np
from sweeplib.materialize import (
    resolve_circuit_input,
    resolve_output_bitstrings_input,
    resolve_statevector_input,
)


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


def _normalize_run_case(
    raw_case: dict[str, Any],
    *,
    defaults: dict[str, Any],
    fallback_name: str,
) -> dict[str, Any]:
    name_raw = raw_case.get("name", fallback_name)
    name = _sanitize(str(name_raw))
    fraction = float(raw_case.get("fraction", defaults["fraction"]))
    threshold = float(raw_case.get("threshold", defaults["threshold"]))
    verbosity = int(raw_case.get("verbosity", defaults["verbosity"]))
    batch_size_raw = raw_case.get("batch_size", defaults["batch_size"])
    batch_size = None if batch_size_raw is None else int(batch_size_raw)
    dense = bool(raw_case.get("dense", defaults["dense"]))

    if fraction <= 0.0 or fraction > 1.0:
        raise ValueError(f"case {name!r}: fraction must satisfy 0 < fraction <= 1")
    if threshold < 0.0:
        raise ValueError(f"case {name!r}: threshold must be >= 0")
    if verbosity < 0:
        raise ValueError(f"case {name!r}: verbosity must be >= 0")
    if batch_size is not None and batch_size < 0:
        raise ValueError(f"case {name!r}: batch_size must be >= 0")

    return {
        "name": name,
        "fraction": fraction,
        "threshold": threshold,
        "verbosity": verbosity,
        "batch_size": batch_size,
        "dense": dense,
    }


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
    }
    if defaults["batch_size"] is not None:
        defaults["batch_size"] = int(defaults["batch_size"])

    reference_raw = cfg.get("reference", {}) or {}
    if not isinstance(reference_raw, dict):
        raise ValueError("'reference' must be an object when present.")
    reference_defaults = dict(defaults)
    reference_defaults["fraction"] = 1.0
    reference_defaults["threshold"] = 0.0
    reference = _normalize_run_case(
        reference_raw,
        defaults=reference_defaults,
        fallback_name="exact_reference",
    )

    cases_raw = cfg.get("cases")
    if not isinstance(cases_raw, list) or not cases_raw:
        raise ValueError("Config must define a non-empty 'cases' array.")
    cases: list[dict[str, Any]] = []
    seen_names: set[str] = set()
    for idx, raw_case in enumerate(cases_raw):
        if not isinstance(raw_case, dict):
            raise ValueError(f"cases[{idx}] must be an object.")
        case = _normalize_run_case(raw_case, defaults=defaults, fallback_name=f"case_{idx:02d}")
        if case["name"] in seen_names:
            raise ValueError(f"Duplicate case name: {case['name']}")
        seen_names.add(case["name"])
        cases.append(case)

    merged = {
        "experiment_name": _pick(
            cfg, "experiment_name", args.experiment_name, "selected_output_accuracy"
        ),
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
    case_dir.mkdir(parents=True, exist_ok=False)
    output_file = case_dir / "output.hsv"
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

    (case_dir / "stdout.log").write_text(proc.stdout, encoding="utf-8")
    (case_dir / "stderr.log").write_text(proc.stderr, encoding="utf-8")
    (case_dir / "command.txt").write_text(shlex.join(cmd) + "\n", encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(
            f"Run case {case['name']!r} failed with return code {proc.returncode}. "
            f"See {case_dir / 'stderr.log'}"
        )
    if not output_file.exists():
        raise RuntimeError(
            f"Run case {case['name']!r} did not produce {output_file}. "
            f"See {case_dir / 'stdout.log'} and {case_dir / 'stderr.log'}"
        )

    return {
        "name": case["name"],
        "fraction": float(case["fraction"]),
        "threshold": float(case["threshold"]),
        "verbosity": int(case["verbosity"]),
        "batch_size": case["batch_size"],
        "dense": bool(case["dense"]),
        "dir": case_dir,
        "output_file": output_file,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "wall_time_s": wall_time_s,
        "internal_runtime_s": _parse_internal_runtime(proc.stdout),
        "sparse": parse_hsv_sparse(output_file),
    }


def _compute_metrics(
    *,
    subset_indices: list[int],
    reference_vec: np.ndarray,
    approx_vec: np.ndarray,
    nonzero_eps: float,
) -> dict[str, Any]:
    ref_abs = np.abs(reference_vec)
    cur_abs = np.abs(approx_vec)
    ref_pop = ref_abs**2
    cur_pop = cur_abs**2
    diff = approx_vec - reference_vec
    abs_amp_err = np.abs(diff)
    abs_pop_err = np.abs(cur_pop - ref_pop)

    ref_norm = float(np.vdot(reference_vec, reference_vec).real)
    cur_norm = float(np.vdot(approx_vec, approx_vec).real)
    l2_abs_error = float(np.linalg.norm(diff))
    weighted_relative_l2_error = None if ref_norm <= 0.0 else float(l2_abs_error / np.sqrt(ref_norm))

    fidelity = None
    if ref_norm > 0.0 and cur_norm > 0.0:
        overlap = np.vdot(reference_vec, approx_vec)
        fidelity = float((abs(overlap) ** 2) / (ref_norm * cur_norm))

    ref_mask = ref_abs > nonzero_eps
    cur_mask = cur_abs > nonzero_eps
    ref_nonzero_count = int(np.count_nonzero(ref_mask))
    cur_nonzero_count = int(np.count_nonzero(cur_mask))
    support_intersection = int(np.count_nonzero(ref_mask & cur_mask))
    support_retention = (
        None if ref_nonzero_count == 0 else float(support_intersection / ref_nonzero_count)
    )
    support_precision = (
        None if cur_nonzero_count == 0 else float(support_intersection / cur_nonzero_count)
    )

    rel_amp_err_nonzero = None
    if ref_nonzero_count > 0:
        rel_amp_err_nonzero = float(np.mean(abs_amp_err[ref_mask] / ref_abs[ref_mask]))

    ref_selected_mass = float(np.sum(ref_pop))
    approx_selected_mass = float(np.sum(cur_pop))
    mass_retention = None if ref_selected_mass <= 0.0 else float(approx_selected_mass / ref_selected_mass)

    return {
        "subset_size": len(subset_indices),
        "reference_nonzero_count": ref_nonzero_count,
        "approx_nonzero_count": cur_nonzero_count,
        "support_intersection_count": support_intersection,
        "support_retention": support_retention,
        "support_precision": support_precision,
        "reference_selected_mass": ref_selected_mass,
        "approx_selected_mass": approx_selected_mass,
        "mass_retention": mass_retention,
        "fidelity_to_reference": fidelity,
        "l2_abs_error": l2_abs_error,
        "weighted_relative_l2_error": weighted_relative_l2_error,
        "max_abs_amp_error": float(np.max(abs_amp_err)) if abs_amp_err.size else 0.0,
        "mean_abs_amp_error": float(np.mean(abs_amp_err)) if abs_amp_err.size else 0.0,
        "max_abs_population_error": float(np.max(abs_pop_err)) if abs_pop_err.size else 0.0,
        "mean_abs_population_error": float(np.mean(abs_pop_err)) if abs_pop_err.size else 0.0,
        "mean_relative_abs_amp_error_on_reference_support": rel_amp_err_nonzero,
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
    case_vectors: dict[str, np.ndarray],
    nonzero_eps: float,
) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "case_name",
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
        for case_name, case_vec in case_vectors.items():
            cur_abs = np.abs(case_vec)
            cur_pop = cur_abs**2
            abs_amp_err = np.abs(case_vec - reference_vec)
            abs_pop_err = np.abs(cur_pop - ref_pop)
            for ordinal, idx in enumerate(subset_indices):
                rel_err = ""
                if ref_abs[ordinal] > nonzero_eps:
                    rel_err = f"{float(abs_amp_err[ordinal] / ref_abs[ordinal]):.18e}"
                writer.writerow(
                    [
                        case_name,
                        ordinal,
                        f"0x{idx:0{size_bytes * 2}X}",
                        f"{reference_vec[ordinal].real:.18e}",
                        f"{reference_vec[ordinal].imag:.18e}",
                        f"{float(ref_pop[ordinal]):.18e}",
                        f"{case_vec[ordinal].real:.18e}",
                        f"{case_vec[ordinal].imag:.18e}",
                        f"{float(cur_pop[ordinal]):.18e}",
                        f"{float(abs_amp_err[ordinal]):.18e}",
                        f"{float(abs_pop_err[ordinal]):.18e}",
                        rel_err,
                        int(ref_abs[ordinal] > nonzero_eps),
                        int(cur_abs[ordinal] > nonzero_eps),
                    ]
                )


def _write_summary_csv(path: Path, case_rows: list[dict[str, Any]]) -> None:
    if not case_rows:
        raise ValueError("No case rows to write.")
    fieldnames = [
        "case_name",
        "fraction",
        "threshold",
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
        "mass_retention",
        "fidelity_to_reference",
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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare exact and approximate selected-output amplitudes on the same bitstrings."
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--experiment-name", default=None)
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
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = _merge_config(args)
    config_stem = Path(args.config).resolve().stem if args.config else _sanitize(str(cfg["experiment_name"]))

    repo_root = Path(cfg["repo_root"]).resolve()
    output_root = _resolve_path(cfg["output_root"], repo_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    run_dir = output_root / f"{_utc_stamp()}_{_sanitize(cfg['experiment_name'])}"
    run_dir.mkdir(parents=True, exist_ok=False)

    circuit, circuit_generated = resolve_circuit_input(cfg["circuit"], repo_root)
    input_statevector, input_generated = resolve_statevector_input(cfg["input_statevector"], repo_root)
    output_bitstrings, output_generated = resolve_output_bitstrings_input(cfg["output_bitstrings"], repo_root)
    binary = _resolve_path(cfg["binary"], repo_root).resolve()
    if not binary.exists():
        raise FileNotFoundError(f"Binary not found: {binary}")

    subset_indices, size_bytes = parse_hs(output_bitstrings)

    reference_run = _run_case(
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
    )
    reference_vec = _ordered_vector(reference_run["sparse"], subset_indices)

    case_vectors: dict[str, np.ndarray] = {}
    case_rows: list[dict[str, Any]] = []
    for case in cfg["cases"]:
        case_run = _run_case(
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
        )
        case_vec = _ordered_vector(case_run["sparse"], subset_indices)
        case_vectors[case["name"]] = case_vec
        metrics = _compute_metrics(
            subset_indices=subset_indices,
            reference_vec=reference_vec,
            approx_vec=case_vec,
            nonzero_eps=float(cfg["nonzero_eps"]),
        )
        case_rows.append(
            {
                "case_name": case["name"],
                "fraction": case_run["fraction"],
                "threshold": case_run["threshold"],
                "wall_time_s": case_run["wall_time_s"],
                "internal_runtime_s": case_run["internal_runtime_s"],
                **metrics,
                "output_file": str(case_run["output_file"]),
                "stdout_log": str(case_run["dir"] / "stdout.log"),
                "stderr_log": str(case_run["dir"] / "stderr.log"),
            }
        )

    reference_csv = run_dir / "reference_outputs.csv"
    comparison_csv = run_dir / "comparison.csv"
    summary_csv = run_dir / "summary.csv"
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
        case_vectors=case_vectors,
        nonzero_eps=float(cfg["nonzero_eps"]),
    )
    _write_summary_csv(summary_csv, case_rows)

    summary = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "experiment_name": cfg["experiment_name"],
        "config": cfg,
        "config_file": str(Path(args.config).resolve()) if args.config else None,
        "paths": {
            "run_dir": str(run_dir),
            "binary": str(binary),
            "circuit": str(circuit),
            "input_statevector": str(input_statevector),
            "output_bitstrings": str(output_bitstrings),
            "reference_output": str(reference_run["output_file"]),
            "reference_outputs_csv": str(reference_csv),
            "comparison_csv": str(comparison_csv),
            "summary_csv": str(summary_csv),
        },
        "generated_inputs": {
            "circuit": circuit_generated,
            "input_statevector": input_generated,
            "output_bitstrings": output_generated,
        },
        "reference": {
            "name": reference_run["name"],
            "fraction": reference_run["fraction"],
            "threshold": reference_run["threshold"],
            "wall_time_s": reference_run["wall_time_s"],
            "internal_runtime_s": reference_run["internal_runtime_s"],
            "output_file": str(reference_run["output_file"]),
        },
        "cases": case_rows,
    }
    summary_json = run_dir / "summary.json"
    summary_json.write_text(
        json.dumps(summary, indent=2, default=_jsonable) + "\n",
        encoding="utf-8",
    )

    print(f"Run directory: {run_dir}")
    print(f"Summary CSV: {summary_csv}")
    print(f"Comparison CSV: {comparison_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
"""Run sv_prefetcher sweeps and persist outputs, metadata, and timing metrics."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import platform
import re
import shlex
import subprocess
import sys
import time
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
    "total_sim_s": re.compile(
        r"Total clocktime sim for sv.cpp:\s+([0-9eE+.\-]+) seconds"
    ),
    "total_io_s": re.compile(
        r"Total clocktime writing to disk for sv.cpp:\s+([0-9eE+.\-]+) seconds"
    ),
    "total_full_s": re.compile(
        r"Total clocktime \(including I/O\) for sv.cpp:\s+([0-9eE+.\-]+) seconds"
    ),
}

DEFAULTS: dict[str, Any] = {
    "experiment_name": None,
    "vary": None,
    "values": None,
    "repeat": 1,
    "binary": "build/sv_prefetcher_subset_mpi.x",
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
}

REQUIRED_FIELDS = (
    "experiment_name",
    "vary",
    "values",
    "circuit",
    "input_statevector",
    "output_bitstrings",
)


def bool_from_any(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value in (0, 1):
            return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    raise ValueError(f"Invalid boolean for '{name}': {value!r}")


def number_from_any(name: str, value: Any, conv: Any) -> Any:
    if value is None:
        return None
    try:
        return conv(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric value for '{name}': {value!r}") from exc


def load_json_config(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file does not exist: {path}")
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("Config file must contain a JSON object at top level.")
    return payload


def normalize_merged_args(merged: dict[str, Any]) -> None:
    merged["repeat"] = number_from_any("repeat", merged.get("repeat"), int)
    merged["ranks"] = number_from_any("ranks", merged.get("ranks"), int)
    merged["batch_size"] = number_from_any("batch_size", merged.get("batch_size"), int)
    merged["fraction"] = number_from_any("fraction", merged.get("fraction"), float)
    merged["threshold"] = number_from_any("threshold", merged.get("threshold"), float)
    merged["verbosity"] = number_from_any("verbosity", merged.get("verbosity"), int)
    merged["timeout_seconds"] = number_from_any(
        "timeout_seconds", merged.get("timeout_seconds"), float
    )
    merged["p"] = number_from_any("p", merged.get("p"), int)
    merged["r"] = number_from_any("r", merged.get("r"), int)
    merged["dense"] = bool_from_any("dense", merged.get("dense"))
    merged["continue_on_error"] = bool_from_any(
        "continue_on_error", merged.get("continue_on_error")
    )
    merged["dry_run"] = bool_from_any("dry_run", merged.get("dry_run"))

    values = merged.get("values")
    if values is None:
        return
    if isinstance(values, str) or not isinstance(values, list):
        raise ValueError(
            f"'values' must be a JSON array or repeated CLI values, got: {values!r}"
        )


def now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def iso_utc(ts: dt.datetime) -> str:
    return ts.isoformat(timespec="seconds")


def sanitize(text: str) -> str:
    out = []
    for ch in text:
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_") or "value"


def resolve_path(path_str: str, root: Path, must_exist: bool = False) -> Path:
    path = Path(path_str)
    if not path.is_absolute():
        path = root / path
    path = path.resolve()
    if must_exist and not path.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")
    return path


def run_capture(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=str(cwd),
        capture_output=True,
        text=True,
        check=False,
    )


def run_git(root: Path, *args: str) -> str:
    proc = run_capture(["git", "-C", str(root), *args], cwd=root)
    if proc.returncode != 0:
        return ""
    return proc.stdout.strip()


def get_git_info(root: Path) -> dict[str, Any]:
    dirty = bool(run_git(root, "status", "--porcelain", "--untracked-files=no"))
    return {
        "commit": run_git(root, "rev-parse", "HEAD"),
        "commit_short": run_git(root, "rev-parse", "--short", "HEAD"),
        "branch": run_git(root, "rev-parse", "--abbrev-ref", "HEAD"),
        "dirty": dirty,
    }


def parse_values(vary: str, raw_values: list[str]) -> list[Any]:
    out: list[Any] = []
    for raw in raw_values:
        if vary in {"fraction", "threshold"}:
            out.append(float(raw))
        else:
            out.append(int(raw))
    return out


def parse_metrics(stdout: str) -> dict[str, Any]:
    parsed: dict[str, Any] = {}
    for key, pattern in METRIC_PATTERNS.items():
        match = pattern.search(stdout)
        if not match:
            parsed[key] = None
            continue
        token = match.group(1)
        if key == "num_simulate_calls":
            parsed[key] = int(token)
        else:
            parsed[key] = float(token)
    return parsed


def build_command(
    mpirun_path: str,
    ranks: int,
    binary_path: Path,
    circuit: Path,
    input_statevector: Path,
    output_bitstrings: Path,
    output_statevector: Path,
    p_chunk2: int | None,
    r_chunk1: int | None,
    batch_size: int,
    fraction: float,
    threshold: float,
    verbosity: int,
    dense: bool,
) -> list[str]:
    cmd = [
        mpirun_path,
        "-n",
        str(ranks),
        str(binary_path),
        "-c",
        str(circuit),
        "-i",
        str(input_statevector),
        "-b",
        str(output_bitstrings),
        "-o",
        str(output_statevector),
        "-s",
        str(batch_size),
        "-f",
        str(fraction),
        "-t",
        str(threshold),
        "-v",
        str(verbosity),
    ]
    if p_chunk2 is not None and r_chunk1 is not None:
        cmd.extend(["-p", str(p_chunk2), "-r", str(r_chunk1)])
    if dense:
        cmd.append("-D")
    return cmd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Sweep one parameter for sv_prefetcher and store results with metadata."
        )
    )
    parser.add_argument(
        "--config",
        default=argparse.SUPPRESS,
        help="Path to JSON config file for sweep parameters.",
    )
    parser.add_argument(
        "--experiment-name",
        default=argparse.SUPPRESS,
        help="Name of this sweep.",
    )
    parser.add_argument(
        "--vary",
        default=argparse.SUPPRESS,
        choices=["ranks", "batch_size", "fraction", "threshold", "p", "r"],
        help="Parameter to sweep.",
    )
    parser.add_argument(
        "--values",
        nargs="+",
        default=argparse.SUPPRESS,
        help="Values for the swept parameter, e.g. --values 1 2 4 8",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=argparse.SUPPRESS,
        help="How many runs per parameter value (default: 1).",
    )
    parser.add_argument(
        "--binary",
        default=argparse.SUPPRESS,
        help="Path to sv_prefetcher binary.",
    )
    parser.add_argument(
        "--mpirun",
        default=argparse.SUPPRESS,
        help="MPI launcher command (default: mpirun).",
    )
    parser.add_argument(
        "--circuit", default=argparse.SUPPRESS, help="Path to circuit file."
    )
    parser.add_argument(
        "--input-statevector",
        default=argparse.SUPPRESS,
        help="Path to input statevector file.",
    )
    parser.add_argument(
        "--output-bitstrings",
        default=argparse.SUPPRESS,
        help="Path to output bitstring subset file.",
    )
    parser.add_argument(
        "--output-root",
        default=argparse.SUPPRESS,
        help="Root directory for sweep outputs.",
    )
    parser.add_argument(
        "--ranks", type=int, default=argparse.SUPPRESS, help="Default MPI ranks."
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=argparse.SUPPRESS,
        help="Default batch size (-s).",
    )
    parser.add_argument(
        "--fraction",
        type=float,
        default=argparse.SUPPRESS,
        help="Default fraction (-f).",
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=argparse.SUPPRESS,
        help="Default threshold (-t).",
    )
    parser.add_argument(
        "--p",
        type=int,
        default=argparse.SUPPRESS,
        help="Fixed chunk2 value (-p).",
    )
    parser.add_argument(
        "--r",
        type=int,
        default=argparse.SUPPRESS,
        help="Fixed chunk1 value (-r).",
    )
    parser.add_argument(
        "--verbosity", type=int, default=argparse.SUPPRESS, help="Verbosity (-v)."
    )
    parser.add_argument(
        "--dense",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Pass -D.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=argparse.SUPPRESS,
        help="Optional timeout per run.",
    )
    parser.add_argument(
        "--continue-on-error",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Continue running even if one sweep point fails.",
    )
    parser.add_argument(
        "--notes",
        default=argparse.SUPPRESS,
        help="Free-text note stored in sweep metadata.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=argparse.SUPPRESS,
        help="Print commands and create metadata skeleton without executing runs.",
    )

    cli_data = vars(parser.parse_args())
    config_path_raw = cli_data.pop("config", None)
    merged = dict(DEFAULTS)

    if config_path_raw:
        config_path = Path(config_path_raw).expanduser().resolve()
        try:
            config_data = load_json_config(config_path)
        except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
            parser.error(str(exc))
        unknown = sorted(set(config_data.keys()) - set(DEFAULTS.keys()))
        if unknown:
            parser.error(
                "Unknown keys in config file: "
                + ", ".join(unknown)
                + f". Allowed keys: {', '.join(sorted(DEFAULTS.keys()))}"
            )
        merged.update(config_data)
        merged["config"] = str(config_path)

    merged.update(cli_data)

    try:
        normalize_merged_args(merged)
    except ValueError as exc:
        parser.error(str(exc))

    missing = [
        field
        for field in REQUIRED_FIELDS
        if merged.get(field) is None
        or merged.get(field) == ""
        or (field == "values" and len(merged["values"]) == 0)
    ]
    if missing:
        parser.error(
            "Missing required sweep arguments: "
            + ", ".join(missing)
            + ". Use CLI flags or provide them in --config JSON."
        )

    return argparse.Namespace(**merged)


def validate_args(args: argparse.Namespace) -> None:
    if args.repeat < 1:
        raise ValueError("--repeat must be >= 1")
    if args.ranks < 1:
        raise ValueError("--ranks must be >= 1")
    if args.batch_size < 0:
        raise ValueError("--batch-size must be >= 0")
    if (args.p is None) ^ (args.r is None):
        raise ValueError("Provide both --p and --r, or neither.")
    if args.vary == "p" and args.r is None:
        raise ValueError("Sweeping --vary p requires fixed --r.")
    if args.vary == "r" and args.p is None:
        raise ValueError("Sweeping --vary r requires fixed --p.")


def main() -> int:
    args = parse_args()
    validate_args(args)

    repo_root = Path(__file__).resolve().parents[1]
    binary_path = resolve_path(args.binary, repo_root, must_exist=True)
    circuit_path = resolve_path(args.circuit, repo_root, must_exist=True)
    input_sv_path = resolve_path(args.input_statevector, repo_root, must_exist=True)
    output_bs_path = resolve_path(args.output_bitstrings, repo_root, must_exist=True)
    output_root = resolve_path(args.output_root, repo_root, must_exist=False)

    varied_values = parse_values(args.vary, args.values)

    sweep_ts = now_utc()
    sweep_name = sanitize(args.experiment_name)
    stamp = sweep_ts.strftime("%Y%m%d_%H%M%S")
    sweep_dir = output_root / f"{stamp}_{sweep_name}"
    sweep_dir.mkdir(parents=True, exist_ok=False)

    git_info = get_git_info(repo_root)
    env_snapshot = {
        "OMP_NUM_THREADS": os.environ.get("OMP_NUM_THREADS", ""),
        "OMP_PROC_BIND": os.environ.get("OMP_PROC_BIND", ""),
        "OMP_PLACES": os.environ.get("OMP_PLACES", ""),
    }

    sweep_meta = {
        "created_at_utc": iso_utc(sweep_ts),
        "repo_root": str(repo_root),
        "python": sys.version,
        "platform": platform.platform(),
        "hostname": platform.node(),
        "git": git_info,
        "notes": args.notes,
        "invocation": shlex.join(sys.argv),
        "config": {
            "config_file": args.config,
            "experiment_name": args.experiment_name,
            "vary": args.vary,
            "values": varied_values,
            "repeat": args.repeat,
            "binary": str(binary_path),
            "mpirun": args.mpirun,
            "circuit": str(circuit_path),
            "input_statevector": str(input_sv_path),
            "output_bitstrings": str(output_bs_path),
            "output_root": str(output_root),
            "defaults": {
                "ranks": args.ranks,
                "batch_size": args.batch_size,
                "fraction": args.fraction,
                "threshold": args.threshold,
                "p": args.p,
                "r": args.r,
                "verbosity": args.verbosity,
                "dense": args.dense,
            },
        },
        "environment": env_snapshot,
        "dry_run": bool(args.dry_run),
    }

    summary_path = sweep_dir / "summary.csv"
    meta_path = sweep_dir / "sweep_metadata.json"
    meta_path.write_text(json.dumps(sweep_meta, indent=2) + "\n", encoding="utf-8")

    fieldnames = [
        "run_index",
        "repeat_index",
        "varied_param",
        "varied_value",
        "ranks",
        "batch_size",
        "fraction",
        "threshold",
        "p",
        "r",
        "verbosity",
        "dense",
        "returncode",
        "walltime_s",
        "num_simulate_calls",
        "total_simulate_calls_s",
        "avg_simulate_call_s",
        "total_sim_s",
        "total_io_s",
        "total_full_s",
        "run_dir",
        "output_file",
        "timing_file",
        "stdout_file",
        "stderr_file",
        "start_utc",
        "end_utc",
        "command",
        "commit_short",
        "branch",
        "dirty",
    ]

    run_index = 0
    failures = 0

    with summary_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
        writer.writeheader()

        for value in varied_values:
            for rep in range(1, args.repeat + 1):
                run_index += 1
                run_tag = (
                    f"run_{run_index:04d}_{args.vary}-{sanitize(str(value))}_rep{rep:02d}"
                )
                run_dir = sweep_dir / run_tag
                run_dir.mkdir(parents=True, exist_ok=False)

                params = {
                    "ranks": args.ranks,
                    "batch_size": args.batch_size,
                    "fraction": args.fraction,
                    "threshold": args.threshold,
                    "p": args.p,
                    "r": args.r,
                    "verbosity": args.verbosity,
                    "dense": args.dense,
                }
                params[args.vary] = value

                output_file = run_dir / "output.hsv"
                timing_file = run_dir / "timeBitstrings.tm"
                stdout_file = run_dir / "stdout.log"
                stderr_file = run_dir / "stderr.log"

                cmd = build_command(
                    mpirun_path=args.mpirun,
                    ranks=int(params["ranks"]),
                    binary_path=binary_path,
                    circuit=circuit_path,
                    input_statevector=input_sv_path,
                    output_bitstrings=output_bs_path,
                    output_statevector=output_file,
                    p_chunk2=params["p"],
                    r_chunk1=params["r"],
                    batch_size=int(params["batch_size"]),
                    fraction=float(params["fraction"]),
                    threshold=float(params["threshold"]),
                    verbosity=int(params["verbosity"]),
                    dense=bool(params["dense"]),
                )

                start = now_utc()
                cmd_str = shlex.join(cmd)

                if args.dry_run:
                    rc = 0
                    elapsed_s = 0.0
                    stdout_text = f"[dry-run] {cmd_str}\n"
                    stderr_text = ""
                else:
                    t0 = time.perf_counter()
                    try:
                        proc = subprocess.run(
                            cmd,
                            cwd=str(repo_root),
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=args.timeout_seconds,
                        )
                        elapsed_s = time.perf_counter() - t0
                        rc = proc.returncode
                        stdout_text = proc.stdout
                        stderr_text = proc.stderr
                    except subprocess.TimeoutExpired as exc:
                        elapsed_s = time.perf_counter() - t0
                        rc = 124
                        stdout_text = exc.stdout or ""
                        stderr_text = (exc.stderr or "") + (
                            f"\n[runner] timeout after {args.timeout_seconds} seconds\n"
                        )

                end = now_utc()
                stdout_file.write_text(stdout_text, encoding="utf-8")
                stderr_file.write_text(stderr_text, encoding="utf-8")

                metrics = parse_metrics(stdout_text)
                timing_file_rel = ""
                if timing_file.exists():
                    timing_file_rel = str(timing_file.relative_to(repo_root))

                row = {
                    "run_index": run_index,
                    "repeat_index": rep,
                    "varied_param": args.vary,
                    "varied_value": value,
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
                    "run_dir": str(run_dir.relative_to(repo_root)),
                    "output_file": str(output_file.relative_to(repo_root)),
                    "timing_file": timing_file_rel,
                    "stdout_file": str(stdout_file.relative_to(repo_root)),
                    "stderr_file": str(stderr_file.relative_to(repo_root)),
                    "start_utc": iso_utc(start),
                    "end_utc": iso_utc(end),
                    "command": cmd_str,
                    "commit_short": git_info.get("commit_short", ""),
                    "branch": git_info.get("branch", ""),
                    "dirty": int(bool(git_info.get("dirty", False))),
                }
                writer.writerow(row)
                csvfile.flush()

                if rc != 0:
                    failures += 1
                    if not args.continue_on_error:
                        print(
                            f"Run failed (index={run_index}, rc={rc}). "
                            f"See {stdout_file} and {stderr_file}.",
                            file=sys.stderr,
                        )
                        print(f"Sweep directory: {sweep_dir}", file=sys.stderr)
                        return rc

    print(f"Sweep directory: {sweep_dir}")
    print(f"Summary CSV: {summary_path}")
    print(f"Sweep metadata: {meta_path}")
    if failures > 0:
        print(f"Completed with {failures} failed run(s).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

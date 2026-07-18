#!/usr/bin/env python
"""Sweep quantum-walk qubit count for Feynman vs quimb."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parents[1]
for path in (SCRIPT_REPO_ROOT, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.sweeplib.plot_style import apply_plot_fontsizes, configure_headless_matplotlib


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
        "notes": raw.get("notes", ""),
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
        "run_feynman_transpiled": run_feynman_transpiled,
    }
    return payload


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
    feynman = metrics.get("feynman", {}) if isinstance(metrics.get("feynman", {}), dict) else {}
    feynman_transpiled = (
        metrics.get("feynman_transpiled", {}) if isinstance(metrics.get("feynman_transpiled", {}), dict) else {}
    )
    summary_status = summary.get("status")
    timed_out = returncode == 124
    if summary_status == "ok":
        overall_status = "ok"
        quimb_status = "ok"
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

    feynman_status = (
        "ok"
        if feynman.get("walltime_s") is not None or feynman.get("internal_total_s") is not None
        else ("not_run" if feynman.get("enabled", True) else "disabled")
    )
    feynman_transpiled_status = (
        "failed"
        if feynman_transpiled.get("failed")
        else (
            "ok"
            if feynman_transpiled.get("enabled") and feynman_transpiled.get("walltime_s") is not None
            else ("disabled" if not feynman_transpiled.get("enabled") else "not_run")
        )
    )
    quimb_peak_rss_mb = metrics.get("quimb_phase_peak_rss_mb") if quimb_status in {"ok", "failed"} else None
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


def _mean_by_n(rows: list[dict[str, Any]], column: str) -> dict[int, float]:
    grouped: dict[int, list[float]] = {}
    for row in rows:
        raw = row.get(column, "")
        if raw in ("", None):
            continue
        value = float(raw)
        if not math.isfinite(value):
            continue
        grouped.setdefault(int(row["n"]), []).append(value)
    return {n: sum(values) / len(values) for n, values in grouped.items()}


def _failure_marker_y(series: dict[str, dict[int, float]]) -> float:
    values = [y for data in series.values() for y in data.values() if y > 0.0 and math.isfinite(y)]
    if not values:
        return 1.0
    return max(values) * 1.25


def _plot_summary(summary_csv: Path, *, output_dir: Path, title: str, label_fontsize: float | None = None) -> list[Path]:
    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_plot_fontsizes(plt=plt, label_fontsize=label_fontsize)
    rows_all = _read_rows(summary_csv, include_failures=True)
    rows_quimb_ok = [row for row in rows_all if row.get("quimb_status") == "ok"]
    quimb_missing_ns = sorted(
        {int(row["n"]) for row in rows_all if row.get("quimb_status") in {"failed", "timeout"}}
    )

    outputs: list[Path] = []
    time_series = {
        "Feynman original wall": _mean_by_n(rows_all, "feynman_walltime_s"),
        "Feynman original internal": _mean_by_n(rows_all, "feynman_internal_total_s"),
        "Feynman transpiled wall": _mean_by_n(rows_all, "feynman_transpiled_walltime_s"),
        "Feynman transpiled internal": _mean_by_n(rows_all, "feynman_transpiled_internal_total_s"),
        "quimb": _mean_by_n(rows_quimb_ok, "quimb_total_s"),
    }
    memory_series = {
        "Feynman original": _mean_by_n(rows_all, "feynman_peak_rss_mb"),
        "Feynman transpiled": _mean_by_n(rows_all, "feynman_transpiled_peak_rss_mb"),
        "quimb": _mean_by_n(rows_quimb_ok, "quimb_peak_rss_mb"),
    }
    ops_series = {
        "transpiled Qiskit ops": _mean_by_n(rows_all, "transpiled_qiskit_ops"),
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
            ys = [values[x] for x in xs]
            ax.plot(xs, ys, marker="o", linewidth=1.6, label=label)
            plotted = True
        if mark_missing_quimb and quimb_missing_ns:
            for i, n in enumerate(quimb_missing_ns):
                ax.axvline(
                    n,
                    color="0.7",
                    linestyle=":",
                    linewidth=1.1,
                    label="quimb not measured" if i == 0 else None,
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
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--experiment-name", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--output-root", default=None)
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument("--no-plot", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = _merge_config(args)
    repo_root = _resolve_path(cfg["repo_root"], Path.cwd())
    output_root = _resolve_path(cfg["output_root"], repo_root)
    sweep_dir = output_root / f"{_utc_stamp()}_{_sanitize(str(cfg['experiment_name']))}"
    sweep_dir.mkdir(parents=True, exist_ok=False)
    configs_dir = sweep_dir / "configs"
    logs_dir = sweep_dir / "logs"
    configs_dir.mkdir()
    logs_dir.mkdir()

    metadata = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "experiment_name": cfg["experiment_name"],
        "config": cfg,
        "config_file": str(args.config.resolve()),
        "sweep_dir": str(sweep_dir),
        "runner": str(Path(__file__).resolve()),
    }
    (sweep_dir / "sweep_metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    summary_csv = sweep_dir / "summary.csv"
    failures = 0
    run_index = 0
    with summary_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        for n_qubits in [int(n) for n in cfg["qubits"]]:
            for repeat_index in range(1, int(cfg["repeat"]) + 1):
                run_index += 1
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
                t0 = time.perf_counter()
                if cfg["dry_run"]:
                    elapsed_s = 0.0
                    stdout = f"[dry-run] {' '.join(cmd)}\n"
                    stderr = ""
                    returncode = 0
                else:
                    try:
                        proc = subprocess.run(
                            cmd,
                            cwd=repo_root,
                            capture_output=True,
                            text=True,
                            check=False,
                            timeout=None if cfg["timeout_seconds"] is None else float(cfg["timeout_seconds"]),
                        )
                        elapsed_s = time.perf_counter() - t0
                        stdout = proc.stdout
                        stderr = proc.stderr
                        returncode = proc.returncode
                    except subprocess.TimeoutExpired as exc:
                        elapsed_s = time.perf_counter() - t0
                        stdout = exc.stdout.decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
                        stderr = exc.stderr.decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
                        stderr += f"\n[qwalk-quimb-sweep] timeout after {cfg['timeout_seconds']} seconds\n"
                        returncode = 124
                stdout_file.write_text(stdout, encoding="utf-8")
                stderr_file.write_text(stderr, encoding="utf-8")
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

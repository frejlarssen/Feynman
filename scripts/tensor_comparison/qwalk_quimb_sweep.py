#!/usr/bin/env python
"""Sweep quantum-walk qubit count for Feynman vs quimb."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
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
    "status",
    "returncode",
    "run_dir",
    "summary_json",
    "stdout_file",
    "stderr_file",
    "qwalk_iterations",
    "output_count",
    "transpiled_qiskit_ops",
    "feynman_walltime_s",
    "feynman_internal_total_s",
    "feynman_peak_rss_mb",
    "feynman_transpiled_walltime_s",
    "feynman_transpiled_internal_total_s",
    "feynman_transpiled_peak_rss_mb",
    "feynman_transpiled_status",
    "feynman_transpiled_error",
    "quimb_total_s",
    "quimb_transpile_s",
    "quimb_build_s",
    "quimb_amplitude_s",
    "quimb_peak_rss_mb",
    "max_abs_amp_error",
    "max_abs_population_error",
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


def _load_summary(path: Path | None) -> dict[str, Any]:
    if path is None or not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


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
    qwalk_iterations: int,
) -> dict[str, Any]:
    metrics = summary.get("metrics", {})
    problem = summary.get("problem", {})
    feynman = metrics.get("feynman", {}) if isinstance(metrics.get("feynman", {}), dict) else {}
    feynman_transpiled = (
        metrics.get("feynman_transpiled", {}) if isinstance(metrics.get("feynman_transpiled", {}), dict) else {}
    )
    status = summary.get("status")
    if not status:
        status = "ok" if returncode == 0 else "failed"
    quimb_peak_rss_mb = metrics.get("quimb_phase_peak_rss_mb") if status == "ok" else None
    return {
        "run_index": run_index,
        "n": n_qubits,
        "repeat_index": repeat_index,
        "status": status,
        "returncode": returncode,
        "run_dir": "" if validation_run_dir is None else str(validation_run_dir),
        "summary_json": "" if validation_run_dir is None else str(validation_run_dir / "summary.json"),
        "stdout_file": str(stdout_file),
        "stderr_file": str(stderr_file),
        "qwalk_iterations": qwalk_iterations,
        "output_count": problem.get("output_count", ""),
        "transpiled_qiskit_ops": problem.get("transpiled_qiskit_ops", ""),
        "feynman_walltime_s": _float_or_empty(feynman.get("walltime_s")),
        "feynman_internal_total_s": _float_or_empty(feynman.get("internal_total_s")),
        "feynman_peak_rss_mb": _float_or_empty(feynman.get("peak_rss_mb")),
        "feynman_transpiled_walltime_s": _float_or_empty(feynman_transpiled.get("walltime_s")),
        "feynman_transpiled_internal_total_s": _float_or_empty(feynman_transpiled.get("internal_total_s")),
        "feynman_transpiled_peak_rss_mb": _float_or_empty(feynman_transpiled.get("peak_rss_mb")),
        "feynman_transpiled_status": (
            "failed"
            if feynman_transpiled.get("failed")
            else ("ok" if feynman_transpiled.get("enabled") and feynman_transpiled.get("walltime_s") else "")
        ),
        "feynman_transpiled_error": feynman_transpiled.get("error", ""),
        "quimb_total_s": _float_or_empty(metrics.get("quimb_total_s")),
        "quimb_transpile_s": _float_or_empty(metrics.get("quimb_transpile_s")),
        "quimb_build_s": _float_or_empty(metrics.get("quimb_build_s")),
        "quimb_amplitude_s": _float_or_empty(metrics.get("quimb_amplitude_s")),
        "quimb_peak_rss_mb": _float_or_empty(quimb_peak_rss_mb),
        "max_abs_amp_error": _float_or_empty(metrics.get("max_abs_amp_error")),
        "max_abs_population_error": _float_or_empty(metrics.get("max_abs_population_error")),
    }


def _read_rows(summary_csv: Path, *, include_failures: bool) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with summary_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not include_failures and row.get("status") != "ok":
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
    rows_ok = [row for row in rows_all if row.get("status") == "ok"]
    safety_ns = sorted({int(row["n"]) for row in rows_all if row.get("status") == "quimb_safety_limit"})

    outputs: list[Path] = []
    time_series = {
        "Feynman original wall": _mean_by_n(rows_all, "feynman_walltime_s"),
        "Feynman original internal": _mean_by_n(rows_all, "feynman_internal_total_s"),
        "Feynman transpiled wall": _mean_by_n(rows_all, "feynman_transpiled_walltime_s"),
        "Feynman transpiled internal": _mean_by_n(rows_all, "feynman_transpiled_internal_total_s"),
        "quimb": _mean_by_n(rows_ok, "quimb_total_s"),
    }
    memory_series = {
        "Feynman original": _mean_by_n(rows_all, "feynman_peak_rss_mb"),
        "Feynman transpiled": _mean_by_n(rows_all, "feynman_transpiled_peak_rss_mb"),
        "quimb": _mean_by_n(rows_ok, "quimb_peak_rss_mb"),
    }
    ops_series = {
        "transpiled Qiskit ops": _mean_by_n(rows_all, "transpiled_qiskit_ops"),
    }

    for filename, ylabel, series in (
        ("qwalk_quimb_time.pdf", "Time (s)", time_series),
        ("qwalk_quimb_memory.pdf", "Peak RSS (MB)", memory_series),
        ("qwalk_quimb_transpiled_ops.pdf", "Transpiled Qiskit ops", ops_series),
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
        marker_y = _failure_marker_y(series)
        for n in safety_ns:
            ax.axvline(n, color="0.7", linestyle="--", linewidth=1.0)
            ax.scatter(
                [n],
                [marker_y],
                marker="x",
                s=70,
                color="black",
                linewidths=1.8,
                label="quimb safety limit" if n == safety_ns[0] else None,
                zorder=5,
            )
            ax.text(
                n,
                marker_y,
                " quimb limit",
                rotation=90,
                va="bottom",
                ha="left",
                fontsize=max(8, int((label_fontsize or 12) * 0.65)),
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
                    qwalk_iterations=int(cfg["qwalk"].get("iterations", 4)),
                )
                writer.writerow(row)
                handle.flush()
                if returncode != 0 and row.get("status") != "quimb_safety_limit":
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

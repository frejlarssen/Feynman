#!/usr/bin/env python
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
from pathlib import Path
from typing import Iterable

def _add_common_sweep_flags(parser: argparse.ArgumentParser, *, require_config: bool = True) -> None:
    parser.add_argument("--config", required=require_config, help="Path to sweep config JSON.")
    parser.add_argument("--experiment-name", default="", help="Optional experiment name override.")
    parser.add_argument("--repo-root", default="", help="Optional repo root override.")
    parser.add_argument("--output-root", default="", help="Optional output root override.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument("--notes", default="", help="Optional metadata notes.")
    parser.add_argument("extra", nargs=argparse.REMAINDER, help="Extra mode-specific passthrough flags.")


def _sweep_argv(args: argparse.Namespace) -> list[str]:
    argv = []
    if args.config:
        argv.extend(["--config", args.config])
    if args.experiment_name:
        argv.extend(["--experiment-name", args.experiment_name])
    if args.repo_root:
        argv.extend(["--repo-root", args.repo_root])
    if args.output_root:
        argv.extend(["--output-root", args.output_root])
    if args.dry_run:
        argv.append("--dry-run")
    if args.continue_on_error:
        argv.append("--continue-on-error")
    if args.timeout_seconds is not None:
        argv.extend(["--timeout-seconds", str(args.timeout_seconds)])
    if args.notes:
        argv.extend(["--notes", args.notes])
    passthrough = list(args.extra)
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    argv.extend(passthrough)
    return argv


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Unified pipeline entrypoint for sweeps, validation, and plotting."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    perf = sub.add_parser("perf-sweep", help="Run sv_prefetcher parameter sweep.")
    _add_common_sweep_flags(perf)

    qaoa = sub.add_parser("qaoa-pruning", help="Run QAOA pruning threshold sweep.")
    _add_common_sweep_flags(qaoa)
    qaoa.add_argument("--no-plot", action="store_true", help="Disable auto-plot at sweep completion.")

    qwalk_quimb_sweep = sub.add_parser("qwalk-quimb-sweep", help="Run QWalk Feynman vs quimb qubit sweep.")
    _add_common_sweep_flags(qwalk_quimb_sweep, require_config=False)
    qwalk_quimb_sweep.add_argument("--no-plot", action="store_true", help="Disable auto-plot at sweep completion.")
    qwalk_quimb_sweep.add_argument("--plot-only", action="store_true", help="Regenerate plots from an existing summary.csv.")
    qwalk_quimb_sweep.add_argument("--summary-csv", default="", help="Existing qwalk-quimb sweep summary.csv for --plot-only.")
    qwalk_quimb_sweep.add_argument("--plot-output-dir", default="", help="Directory for regenerated plots.")

    qwalk_quimb_gate_contract = sub.add_parser(
        "qwalk-quimb-gate-contract-sweep",
        help="Run qwalk-quimb sweeps for quimb gate contraction modes.",
    )
    qwalk_quimb_gate_contract.add_argument("--config", required=True, help="Path to base qwalk-quimb sweep config JSON.")
    qwalk_quimb_gate_contract.add_argument("--repo-root", default="", help="Optional repo root override.")
    qwalk_quimb_gate_contract.add_argument("--output-root", default="", help="Optional outer output root.")
    qwalk_quimb_gate_contract.add_argument("--continue-on-error", action="store_true")
    qwalk_quimb_gate_contract.add_argument("--dry-run", action="store_true")
    qwalk_quimb_gate_contract.add_argument(
        "--contract-values",
        nargs="*",
        help="Specific contract values to test. Defaults to all documented quimb modes.",
    )

    run_all = sub.add_parser(
        "run-all-experiments",
        help="Run all perf+validation configs under scripts/experiments.",
    )
    run_all.add_argument(
        "--scope",
        choices=["all", "paper", "exploratory"],
        default="all",
        help="Which config bucket(s) to run.",
    )
    run_all.add_argument("--dry-run", action="store_true", help="Pass --dry-run to each launched run.")
    run_all.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Pass --continue-on-error to each launched sweep run.",
    )
    run_all.add_argument(
        "--timeout-seconds",
        type=float,
        default=None,
        help="Pass --timeout-seconds to each experiment run.",
    )
    run_all.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after first failed experiment command.",
    )

    validation = sub.add_parser("validation", help="Run validation workflows.")
    validation_sub = validation.add_subparsers(dest="validation_kind", required=True)

    qaoa_val = validation_sub.add_parser("qaoa-qiskit", help="Run QAOA vs Qiskit validation.")
    qaoa_val.add_argument("--config", required=True, help="Path to validation config JSON.")
    qaoa_val.add_argument("--output-root", default="", help="Optional output root override.")
    qaoa_val.add_argument("--repo-root", default="", help="Optional repo root override.")
    qaoa_val.add_argument("extra", nargs=argparse.REMAINDER, help="Extra mode-specific passthrough flags.")

    qft_val = validation_sub.add_parser("qft-demo", help="Run QFT validation/demo workflow.")
    qft_val.add_argument("--config", required=True, help="Path to validation config JSON.")
    qft_val.add_argument("--output-root", default="", help="Optional output root override.")
    qft_val.add_argument("--repo-root", default="", help="Optional repo root override.")
    qft_val.add_argument(
        "--latest",
        action="store_true",
        help="With '-- --from-csv', auto-resolve latest qft-demo summary.json if not provided.",
    )
    qft_val.add_argument(
        "--latest-name-contains",
        default="qft_demo",
        help="Substring filter for --latest qft-demo run directory matching.",
    )
    qft_val.add_argument("extra", nargs=argparse.REMAINDER, help="Extra mode-specific passthrough flags.")

    qwalk_quimb = validation_sub.add_parser("qwalk-quimb", help="Run quantum-walk vs quimb validation.")
    qwalk_quimb.add_argument("--config", required=True, help="Path to validation config JSON.")
    qwalk_quimb.add_argument("--output-root", default="", help="Optional output root override.")
    qwalk_quimb.add_argument("--repo-root", default="", help="Optional repo root override.")
    qwalk_quimb.add_argument("extra", nargs=argparse.REMAINDER, help="Extra mode-specific passthrough flags.")

    plot = sub.add_parser("plot", help="Plot from existing summary/output artifacts.")
    plot_sub = plot.add_subparsers(dest="plot_kind", required=True)

    p_perf = plot_sub.add_parser("perf-sweep", help="Plot perf sweep summary.")
    p_perf_input = p_perf.add_mutually_exclusive_group(required=True)
    p_perf_input.add_argument("--summary-csv", default="")
    p_perf_input.add_argument(
        "--latest",
        action="store_true",
        help="Use newest matching experiment run directory and read summary.csv from it.",
    )
    p_perf.add_argument(
        "--latest-name-contains",
        default="",
        help="Optional substring filter for selecting latest experiment run directory.",
    )
    p_perf.add_argument("--y-column", default="total_full_s")
    p_perf.add_argument("--mode", choices=["scatter", "meanstd"], default="meanstd")
    p_perf.add_argument("--include-failures", action="store_true")
    p_perf.add_argument("--output", default="")
    p_perf.add_argument("--title", default="")
    p_perf.add_argument("--label-fontsize", type=float, default=None)

    p_cases = plot_sub.add_parser("perf-cases", help="Plot perf case aggregates.")
    p_cases_input = p_cases.add_mutually_exclusive_group(required=True)
    p_cases_input.add_argument("--summary-csv", default="")
    p_cases_input.add_argument(
        "--latest",
        action="store_true",
        help="Use newest matching experiment run directory and read summary.csv from it.",
    )
    p_cases.add_argument(
        "--latest-name-contains",
        default="",
        help="Optional substring filter for selecting latest experiment run directory.",
    )
    p_cases.add_argument("--y-column", default="total_full_s")
    p_cases.add_argument("--include-failures", action="store_true")
    p_cases.add_argument("--varied-value", default="")
    p_cases.add_argument("--output", default="")
    p_cases.add_argument("--title", default="")
    p_cases.add_argument("--label-fontsize", type=float, default=None)

    p_case_lines = plot_sub.add_parser("perf-case-lines", help="Plot perf line curves by case.")
    p_case_lines_input = p_case_lines.add_mutually_exclusive_group(required=True)
    p_case_lines_input.add_argument("--summary-csv", default="")
    p_case_lines_input.add_argument(
        "--latest",
        action="store_true",
        help="Use newest matching experiment run directory and read summary.csv from it.",
    )
    p_case_lines.add_argument(
        "--latest-name-contains",
        default="",
        help="Optional substring filter for selecting latest experiment run directory.",
    )
    p_case_lines.add_argument("--x-column", default="total_artificial_sources")
    p_case_lines.add_argument("--y-column", default="total_full_s")
    p_case_lines.add_argument("--xscale", choices=["linear", "log", "symlog"], default="linear")
    p_case_lines.add_argument("--yscale", choices=["linear", "log", "symlog"], default="log")
    p_case_lines.add_argument("--include-failures", action="store_true")
    p_case_lines.add_argument("--output", default="")
    p_case_lines.add_argument("--title", default="")
    p_case_lines.add_argument("--label-fontsize", type=float, default=None)

    p_qaoa = plot_sub.add_parser("qaoa-pruning", help="Plot QAOA pruning sweep summary.")
    p_qaoa_input = p_qaoa.add_mutually_exclusive_group(required=True)
    p_qaoa_input.add_argument("--summary-csv", default="")
    p_qaoa_input.add_argument(
        "--latest",
        action="store_true",
        help="Use newest matching QAOA pruning run directory and read summary.csv from it.",
    )
    p_qaoa.add_argument(
        "--latest-name-contains",
        default="qaoa_pruning_sweep",
        help="Substring filter for selecting latest experiment run directory.",
    )
    p_qaoa.add_argument("--time-column", default="total_full_s")
    p_qaoa.add_argument("--fidelity-column", default="fidelity_to_reference")
    p_qaoa.add_argument("--include-failures", action="store_true")
    p_qaoa.add_argument("--output", default="")
    p_qaoa.add_argument("--title", default="QAOA pruning sweep")
    p_qaoa.add_argument("--xscale", choices=["linear", "log", "symlog"], default="symlog")
    p_qaoa.add_argument("--label-fontsize", type=float, default=None)

    p_qaoa_val = plot_sub.add_parser("qaoa-qiskit", help="Plot QAOA validation agreement from comparison.csv.")
    p_qaoa_val_input = p_qaoa_val.add_mutually_exclusive_group(required=True)
    p_qaoa_val_input.add_argument("--comparison-csv", default="")
    p_qaoa_val_input.add_argument(
        "--latest",
        action="store_true",
        help="Use newest matching validation run directory and read comparison.csv from it.",
    )
    p_qaoa_val.add_argument(
        "--latest-name-contains",
        default="qiskit_validation",
        help="Substring filter for selecting latest validation run directory.",
    )
    p_qaoa_val.add_argument("--output", default="")
    p_qaoa_val.add_argument("--label-fontsize", type=float, default=None)
    return parser


def _validation_argv(args: argparse.Namespace) -> list[str]:
    argv = ["--config", args.config]
    if args.repo_root:
        argv.extend(["--repo-root", args.repo_root])
    if args.output_root:
        argv.extend(["--output-root", args.output_root])
    passthrough = list(args.extra)
    if passthrough and passthrough[0] == "--":
        passthrough = passthrough[1:]
    if (
        getattr(args, "validation_kind", "") == "qft-demo"
        and getattr(args, "latest", False)
        and "--from-csv" in passthrough
        and "--summary-json" not in passthrough
    ):
        repo_root = Path(args.repo_root).resolve() if args.repo_root else Path(__file__).resolve().parents[1]
        latest_summary = _resolve_latest_artifact(
            repo_root=repo_root,
            run_type="validation",
            artifact_name="summary.json",
            name_contains=args.latest_name_contains,
        )
        passthrough.extend(["--summary-json", str(latest_summary)])
    argv.extend(passthrough)
    return argv


def _infer_vary_label(summary_path: Path) -> str:
    metadata_path = summary_path.parent / "sweep_metadata.json"
    if not metadata_path.exists():
        return "varied_value"
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "varied_value"
    vary = payload.get("config", {}).get("vary", "")
    return vary if isinstance(vary, str) and vary else "varied_value"


def _iter_latest_dirs(
    *,
    root: Path,
    name_contains: str,
) -> Iterable[Path]:
    if not root.exists():
        return []
    dirs = [p for p in root.iterdir() if p.is_dir()]
    if name_contains:
        dirs = [p for p in dirs if name_contains in p.name]
    return sorted(dirs, key=lambda p: p.stat().st_mtime, reverse=True)


def _resolve_latest_artifact(
    *,
    repo_root: Path,
    run_type: str,
    artifact_name: str,
    name_contains: str,
) -> Path:
    if run_type not in {"experiments", "validation"}:
        raise ValueError(f"Unsupported run_type: {run_type}")
    runs_root = (repo_root / "data" / "outputs" / run_type).resolve()
    for run_dir in _iter_latest_dirs(root=runs_root, name_contains=name_contains):
        candidate = run_dir / artifact_name
        if candidate.exists():
            return candidate
    suffix_msg = f" containing '{name_contains}'" if name_contains else ""
    raise FileNotFoundError(
        f"No run directory found under {runs_root} with {artifact_name}{suffix_msg}. "
        "Provide explicit file path instead."
    )


def _strip_timestamp_prefix(run_dir_name: str) -> str:
    return re.sub(r"^\d{8}_\d{6}_", "", run_dir_name)


def _config_stem_from_experiment_run_dir(run_dir: Path) -> str:
    metadata_path = run_dir / "sweep_metadata.json"
    if metadata_path.exists():
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        cfg_file = payload.get("config", {}).get("config_file")
        if isinstance(cfg_file, str) and cfg_file:
            return Path(cfg_file).stem
    fallback = _strip_timestamp_prefix(run_dir.name)
    return fallback if fallback else "plot"


def _config_stem_from_validation_run_dir(run_dir: Path) -> str:
    summary_path = run_dir / "summary.json"
    if summary_path.exists():
        try:
            payload = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        cfg_file = payload.get("config_file")
        if isinstance(cfg_file, str) and cfg_file:
            return Path(cfg_file).stem
    fallback = _strip_timestamp_prefix(run_dir.name)
    return fallback if fallback else "plot"


def _default_plot_path(
    *,
    artifact_path: Path,
    run_type: str,
    current_stem: str,
    multiple_plots_for_config: bool,
) -> Path:
    if run_type == "experiments":
        cfg_stem = _config_stem_from_experiment_run_dir(artifact_path.parent)
    elif run_type == "validation":
        cfg_stem = _config_stem_from_validation_run_dir(artifact_path.parent)
    else:
        raise ValueError(f"Unsupported run_type: {run_type}")
    stem = f"{cfg_stem}_{_short_plot_suffix(current_stem)}" if multiple_plots_for_config else cfg_stem
    return artifact_path.parent / f"{stem}.pdf"


def _short_plot_suffix(stem: str) -> str:
    short = stem.strip()
    if short.startswith("plot_"):
        short = short[len("plot_") :]

    replacements = {
        "total_full_s": "ttot",
        "total_artificial_sources": "a",
        "fidelity_to_reference": "fidelity",
        "batch_size": "batch",
        "circuit_it": "it",
        "varied_value": "vary",
        "summary_time_fidelity": "time_fidelity",
    }
    for old, new in replacements.items():
        short = short.replace(old, new)

    short = re.sub(r"[^a-zA-Z0-9_]+", "_", short)
    short = re.sub(r"_+", "_", short).strip("_")
    return short or "plot"


def _resolve_summary_csv_arg(
    *,
    args: argparse.Namespace,
    run_type: str,
) -> Path:
    if args.summary_csv:
        return Path(args.summary_csv).resolve()
    if not args.latest:
        raise ValueError("Provide --summary-csv or use --latest.")
    repo_root = Path(__file__).resolve().parents[1]
    return _resolve_latest_artifact(
        repo_root=repo_root,
        run_type=run_type,
        artifact_name="summary.csv",
        name_contains=args.latest_name_contains,
    )


def _plot_perf_sweep(args: argparse.Namespace) -> int:
    from sweeplib.plotting import default_plot_output_path, load_xy_from_summary, render_sweep_plot

    summary_path = _resolve_summary_csv_arg(args=args, run_type="experiments")
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary CSV not found: {summary_path}")
    x_column = "varied_value"
    x_label = _infer_vary_label(summary_path)
    xs, ys = load_xy_from_summary(
        summary_path=summary_path,
        x_column=x_column,
        y_column=args.y_column,
        include_failures=args.include_failures,
    )
    output_path = Path(args.output).resolve() if args.output else _default_plot_path(
        artifact_path=summary_path,
        run_type="experiments",
        current_stem=default_plot_output_path(summary_path, x_column=x_label, y_column=args.y_column).stem,
        multiple_plots_for_config=True,
    )
    render_sweep_plot(
        xs=xs,
        ys=ys,
        mode=args.mode,
        x_label=x_label,
        y_label=args.y_column,
        title=args.title,
        output_path=output_path,
        label_fontsize=args.label_fontsize,
    )
    print(f"Saved plot: {output_path}")
    return 0


def _plot_perf_cases(args: argparse.Namespace) -> int:
    from sweeplib.plot_style import apply_plot_fontsizes, configure_headless_matplotlib, format_metric_label

    import csv

    def _to_float(value: str) -> float:
        if value is None or value == "":
            raise ValueError("empty")
        return float(value)

    summary_path = _resolve_summary_csv_arg(args=args, run_type="experiments")
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary CSV not found: {summary_path}")

    varied_value_filter = float(args.varied_value) if args.varied_value else None
    grouped: dict[str, list[float]] = {}
    with summary_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not args.include_failures and int(row.get("returncode", "1")) != 0:
                continue
            if varied_value_filter is not None:
                try:
                    vv = _to_float(row.get("varied_value", ""))
                except ValueError:
                    continue
                if vv != varied_value_filter:
                    continue
            try:
                y = _to_float(row.get(args.y_column, ""))
            except ValueError:
                continue
            case_name = row.get("case_name", "") or "default"
            grouped.setdefault(case_name, []).append(y)
    if not grouped:
        raise RuntimeError("No plottable rows found for the selected filters.")

    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_plot_fontsizes(plt=plt, label_fontsize=args.label_fontsize)
    case_names = sorted(grouped)
    means = [statistics.mean(grouped[name]) for name in case_names]
    stds = [statistics.stdev(grouped[name]) if len(grouped[name]) > 1 else 0.0 for name in case_names]
    fig, ax = plt.subplots(figsize=(8, 5))
    xs = list(range(len(case_names)))
    ax.bar(xs, means, yerr=stds, capsize=5, alpha=0.9)
    ax.set_xticks(xs, case_names)
    ax.set_ylabel(format_metric_label(args.y_column))
    ax.set_xlabel("")
    default_title = (
        "Autotuning and Checkpoint Ablation"
        if args.y_column == "total_full_s"
        else f"{format_metric_label(args.y_column)} by case"
    )
    ax.set_title(args.title or default_title)
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    output_path = (
        Path(args.output).resolve()
        if args.output
        else _default_plot_path(
            artifact_path=summary_path,
            run_type="experiments",
            current_stem=f"plot_{args.y_column}_by_case",
            multiple_plots_for_config=True,
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    print(f"Saved plot: {output_path}")
    return 0


def _plot_perf_case_lines(args: argparse.Namespace) -> int:
    from sweeplib.plot_style import apply_plot_fontsizes, configure_headless_matplotlib, format_metric_label

    import csv

    def _to_float(value: str) -> float:
        if value is None or value == "":
            raise ValueError("empty")
        return float(value)

    summary_path = _resolve_summary_csv_arg(args=args, run_type="experiments")
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary CSV not found: {summary_path}")

    grouped: dict[str, dict[float, list[float]]] = {}
    with summary_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not args.include_failures and int(row.get("returncode", "1")) != 0:
                continue
            try:
                x = _to_float(row.get(args.x_column, ""))
                y = _to_float(row.get(args.y_column, ""))
            except ValueError:
                continue
            case_name = row.get("case_name", "") or "default"
            grouped.setdefault(case_name, {}).setdefault(x, []).append(y)
    if len(grouped) <= 1:
        raise RuntimeError("Need at least two cases with plottable rows.")

    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_plot_fontsizes(plt=plt, label_fontsize=args.label_fontsize)
    fig, ax = plt.subplots(figsize=(8, 5))
    for case_name in sorted(grouped):
        x_sorted = sorted(grouped[case_name])
        means = [statistics.mean(grouped[case_name][x]) for x in x_sorted]
        stds = [
            statistics.stdev(grouped[case_name][x]) if len(grouped[case_name][x]) > 1 else 0.0
            for x in x_sorted
        ]
        ax.errorbar(
            x_sorted,
            means,
            yerr=stds,
            fmt="o-",
            capsize=4,
            linewidth=1.4,
            markersize=5,
            label=case_name,
        )

    if args.xscale == "log":
        all_x = [x for case_data in grouped.values() for x in case_data]
        if any(x <= 0.0 for x in all_x):
            raise ValueError(f"xscale=log requires all {args.x_column} values > 0.")
    if args.yscale == "log":
        all_y = [y for case_data in grouped.values() for ys in case_data.values() for y in ys]
        if any(y <= 0.0 for y in all_y):
            raise ValueError(f"yscale=log requires all {args.y_column} values > 0.")

    ax.set_xscale(args.xscale)
    ax.set_yscale(args.yscale)
    display_x = format_metric_label(args.x_column)
    display_y = format_metric_label(args.y_column)
    ax.set_xlabel(display_x)
    ax.set_ylabel(display_y)
    if args.x_column == "total_artificial_sources" and args.y_column == "total_full_s":
        default_title = "Time vs Number of Artificial Sources"
    else:
        default_title = f"{display_y} vs {display_x} by case ({args.xscale}/{args.yscale})"
    ax.set_title(args.title or default_title)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    output_path = (
        Path(args.output).resolve()
        if args.output
        else _default_plot_path(
            artifact_path=summary_path,
            run_type="experiments",
            current_stem=f"plot_{args.y_column}_vs_{args.x_column}_by_case",
            multiple_plots_for_config=True,
        )
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    print(f"Saved plot: {output_path}")
    return 0


def _plot_qaoa_pruning(args: argparse.Namespace) -> int:
    from qaoa_pruning_sweep.plotting import plot_time_fidelity

    summary_path = _resolve_summary_csv_arg(args=args, run_type="experiments")
    output_path = Path(args.output).resolve() if args.output else _default_plot_path(
        artifact_path=summary_path,
        run_type="experiments",
        current_stem="summary_time_fidelity",
        multiple_plots_for_config=False,
    )
    saved_path = plot_time_fidelity(
        summary_csv=summary_path,
        output=output_path,
        time_column=args.time_column,
        fidelity_column=args.fidelity_column,
        title=args.title,
        xscale=args.xscale,
        include_failures=args.include_failures,
        label_fontsize=args.label_fontsize,
    )
    print(f"Saved plot: {saved_path}")
    return 0


def _plot_qaoa_qiskit(args: argparse.Namespace) -> int:
    from validation.qaoa_qiskit_validation import plot_from_comparison_csv

    if args.comparison_csv:
        comparison_csv = Path(args.comparison_csv).resolve()
    elif args.latest:
        comparison_csv = _resolve_latest_artifact(
            repo_root=Path(__file__).resolve().parents[1],
            run_type="validation",
            artifact_name="comparison.csv",
            name_contains=args.latest_name_contains,
        )
    else:
        raise ValueError("Provide --comparison-csv or use --latest.")
    if not comparison_csv.exists():
        raise FileNotFoundError(f"Comparison CSV not found: {comparison_csv}")
    output = Path(args.output).resolve() if args.output else _default_plot_path(
        artifact_path=comparison_csv,
        run_type="validation",
        current_stem="agreement_plot",
        multiple_plots_for_config=False,
    )
    saved = plot_from_comparison_csv(comparison_csv, output_path=output, label_fontsize=args.label_fontsize)
    print(f"Saved plot: {saved}")
    return 0


def _detect_experiment_mode(config_path: Path) -> str:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config must be a JSON object: {config_path}")
    config_type = config_path.parent.name
    if config_type == "perf":
        stem = config_path.stem.lower()
        if "qwalk_quimb" in stem or str(payload.get("backend", "")).lower() == "quimb":
            return "qwalk-quimb-sweep"
        # QAOA pruning configs use thresholds + base_config.
        if "thresholds" in payload and "base_config" in payload:
            return "qaoa-pruning"
        return "perf-sweep"
    if config_type == "validation":
        stem = config_path.stem.lower()
        if "quimb" in stem or str(payload.get("backend", "")).lower() == "quimb":
            return "validation:qwalk-quimb"
        if "qiskit_validation" in stem or "qiskit" in stem:
            return "validation:qaoa-qiskit"
        return "validation:qft-demo"
    raise ValueError(f"Unsupported config location for mode detection: {config_path}")


def _discover_experiment_configs(repo_root: Path, scope: str) -> list[Path]:
    base = repo_root / "scripts" / "experiments"
    buckets: list[str]
    if scope == "all":
        buckets = ["paper", "exploratory"]
    else:
        buckets = [scope]
    out: list[Path] = []
    for bucket in buckets:
        out.extend(sorted((base / bucket / "perf").glob("*.json")))
        out.extend(sorted((base / bucket / "validation").glob("*.json")))
    return out


def _build_run_all_command(script_path: Path, cfg: Path, mode: str) -> list[str]:
    if mode == "perf-sweep":
        return [sys.executable, str(script_path), "perf-sweep", "--config", str(cfg)]
    if mode == "qaoa-pruning":
        return [sys.executable, str(script_path), "qaoa-pruning", "--config", str(cfg)]
    if mode == "qwalk-quimb-sweep":
        return [sys.executable, str(script_path), "qwalk-quimb-sweep", "--config", str(cfg)]
    if mode == "validation:qaoa-qiskit":
        return [sys.executable, str(script_path), "validation", "qaoa-qiskit", "--config", str(cfg)]
    if mode == "validation:qwalk-quimb":
        return [sys.executable, str(script_path), "validation", "qwalk-quimb", "--config", str(cfg)]
    if mode == "validation:qft-demo":
        return [sys.executable, str(script_path), "validation", "qft-demo", "--config", str(cfg)]
    raise ValueError(f"Unsupported run-all mode: {mode}")


def _run_all_experiments(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    configs = _discover_experiment_configs(repo_root, args.scope)
    if not configs:
        raise FileNotFoundError(
            f"No configs found for scope={args.scope!r} under scripts/experiments/{{paper,exploratory}}."
        )

    script_path = Path(__file__).resolve()
    failures: list[tuple[Path, int]] = []
    for cfg in configs:
        mode = _detect_experiment_mode(cfg)
        cmd = _build_run_all_command(script_path, cfg, mode)
        if args.continue_on_error and mode in {"perf-sweep", "qaoa-pruning", "qwalk-quimb-sweep"}:
            cmd.append("--continue-on-error")
        if args.timeout_seconds is not None and mode in {"perf-sweep", "qaoa-pruning", "qwalk-quimb-sweep"}:
            cmd.extend(["--timeout-seconds", str(args.timeout_seconds)])
        if args.dry_run:
            print(f"[run-all-experiments] DRY-RUN: {' '.join(cmd)}")
            continue
        print(f"[run-all-experiments] Running: {mode} :: {cfg}")
        proc = subprocess.run(cmd, cwd=str(repo_root), check=False)
        if proc.returncode != 0:
            failures.append((cfg, proc.returncode))
            if args.fail_fast:
                break

    print(
        "[run-all-experiments] Summary: "
        f"total={len(configs)}, succeeded={len(configs) - len(failures)}, failed={len(failures)}"
    )
    if failures:
        for cfg, code in failures:
            print(f"  - failed({code}): {cfg}")
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "perf-sweep":
        from sv_prefetcher_sweep.main import main as perf_sweep_main

        return perf_sweep_main(entry_script=Path(__file__).resolve(), argv=_sweep_argv(args))
    if args.command == "qaoa-pruning":
        from qaoa_pruning_sweep.main import main as qaoa_pruning_main

        sweep_argv = _sweep_argv(args)
        if args.no_plot:
            sweep_argv.append("--no-plot")
        return qaoa_pruning_main(entry_script=Path(__file__).resolve(), argv=sweep_argv)
    if args.command == "qwalk-quimb-sweep":
        from tensor_comparison.qwalk_quimb_sweep import main as qwalk_quimb_sweep_main

        sweep_argv = _sweep_argv(args)
        if args.no_plot:
            sweep_argv.append("--no-plot")
        if args.plot_only:
            sweep_argv.append("--plot-only")
        if args.summary_csv:
            sweep_argv.extend(["--summary-csv", args.summary_csv])
        if args.plot_output_dir:
            sweep_argv.extend(["--plot-output-dir", args.plot_output_dir])
        return qwalk_quimb_sweep_main(sweep_argv)
    if args.command == "qwalk-quimb-gate-contract-sweep":
        from tensor_comparison.qwalk_quimb_gate_contract_sweep import main as gate_contract_sweep_main

        sweep_argv = ["--config", args.config]
        if args.repo_root:
            sweep_argv.extend(["--repo-root", args.repo_root])
        if args.output_root:
            sweep_argv.extend(["--output-root", args.output_root])
        if args.continue_on_error:
            sweep_argv.append("--continue-on-error")
        if args.dry_run:
            sweep_argv.append("--dry-run")
        if args.contract_values:
            sweep_argv.append("--contract-values")
            sweep_argv.extend(args.contract_values)
        return gate_contract_sweep_main(sweep_argv)
    if args.command == "run-all-experiments":
        return _run_all_experiments(args)
    if args.command == "validation":
        from validation.qaoa_qiskit_validation import main as qaoa_validation_main
        from validation.qft_demo import main as qft_demo_main
        from tensor_comparison.qwalk_quimb import main as qwalk_quimb_main

        val_argv = _validation_argv(args)
        if args.validation_kind == "qaoa-qiskit":
            return qaoa_validation_main(val_argv)
        if args.validation_kind == "qwalk-quimb":
            return qwalk_quimb_main(val_argv)
        if args.validation_kind == "qft-demo":
            return qft_demo_main(val_argv)
        parser.error(f"Unknown validation kind: {args.validation_kind}")
    if args.command == "plot":
        if args.plot_kind == "perf-sweep":
            return _plot_perf_sweep(args)
        if args.plot_kind == "perf-cases":
            return _plot_perf_cases(args)
        if args.plot_kind == "perf-case-lines":
            return _plot_perf_case_lines(args)
        if args.plot_kind == "qaoa-pruning":
            return _plot_qaoa_pruning(args)
        if args.plot_kind == "qaoa-qiskit":
            return _plot_qaoa_qiskit(args)
        parser.error(f"Unknown plot kind: {args.plot_kind}")
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

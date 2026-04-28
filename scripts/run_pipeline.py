#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path

def _add_common_sweep_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True, help="Path to sweep config JSON.")
    parser.add_argument("--experiment-name", default="", help="Optional experiment name override.")
    parser.add_argument("--repo-root", default="", help="Optional repo root override.")
    parser.add_argument("--output-root", default="", help="Optional output root override.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--continue-on-error", action="store_true")
    parser.add_argument("--timeout-seconds", type=float, default=None)
    parser.add_argument("--notes", default="", help="Optional metadata notes.")
    parser.add_argument("extra", nargs=argparse.REMAINDER, help="Extra mode-specific passthrough flags.")


def _sweep_argv(args: argparse.Namespace) -> list[str]:
    argv = ["--config", args.config]
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
    qft_val.add_argument("extra", nargs=argparse.REMAINDER, help="Extra mode-specific passthrough flags.")

    plot = sub.add_parser("plot", help="Plot from existing summary/output artifacts.")
    plot_sub = plot.add_subparsers(dest="plot_kind", required=True)

    p_perf = plot_sub.add_parser("perf-sweep", help="Plot perf sweep summary.")
    p_perf.add_argument("--summary-csv", required=True)
    p_perf.add_argument("--y-column", default="total_full_s")
    p_perf.add_argument("--mode", choices=["scatter", "meanstd"], default="meanstd")
    p_perf.add_argument("--include-failures", action="store_true")
    p_perf.add_argument("--output", default="")
    p_perf.add_argument("--title", default="")
    p_perf.add_argument("--label-fontsize", type=float, default=None)

    p_cases = plot_sub.add_parser("perf-cases", help="Plot perf case aggregates.")
    p_cases.add_argument("--summary-csv", required=True)
    p_cases.add_argument("--y-column", default="total_full_s")
    p_cases.add_argument("--include-failures", action="store_true")
    p_cases.add_argument("--varied-value", default="")
    p_cases.add_argument("--output", default="")
    p_cases.add_argument("--title", default="")
    p_cases.add_argument("--label-fontsize", type=float, default=None)

    p_qaoa = plot_sub.add_parser("qaoa-pruning", help="Plot QAOA pruning sweep summary.")
    p_qaoa.add_argument("--summary-csv", required=True)
    p_qaoa.add_argument("--time-column", default="total_full_s")
    p_qaoa.add_argument("--fidelity-column", default="fidelity_to_reference")
    p_qaoa.add_argument("--include-failures", action="store_true")
    p_qaoa.add_argument("--output", default="")
    p_qaoa.add_argument("--title", default="QAOA pruning sweep")
    p_qaoa.add_argument("--xscale", choices=["linear", "log", "symlog"], default="symlog")
    p_qaoa.add_argument("--label-fontsize", type=float, default=None)
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


def _plot_perf_sweep(args: argparse.Namespace) -> int:
    from sweeplib.plotting import default_plot_output_path, load_xy_from_summary, render_sweep_plot

    summary_path = Path(args.summary_csv).resolve()
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
    output_path = (
        Path(args.output).resolve()
        if args.output
        else default_plot_output_path(summary_path, x_column=x_label, y_column=args.y_column)
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
    from sweeplib.plot_style import apply_plot_fontsizes, configure_headless_matplotlib

    import csv

    def _to_float(value: str) -> float:
        if value is None or value == "":
            raise ValueError("empty")
        return float(value)

    summary_path = Path(args.summary_csv).resolve()
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
    ax.set_ylabel(args.y_column)
    ax.set_xlabel("case_name")
    ax.set_title(args.title or f"{args.y_column} by case")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    output_path = (
        Path(args.output).resolve() if args.output else (summary_path.parent / f"plot_{args.y_column}_by_case.pdf")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    print(f"Saved plot: {output_path}")
    return 0


def _plot_qaoa_pruning(args: argparse.Namespace) -> int:
    from qaoa_pruning_sweep.plotting import plot_time_fidelity

    summary_path = Path(args.summary_csv).resolve()
    output_path = Path(args.output).resolve() if args.output else None
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
    if args.command == "validation":
        from validation.qaoa_qiskit_validation import main as qaoa_validation_main
        from validation.qft_demo import main as qft_demo_main

        val_argv = _validation_argv(args)
        if args.validation_kind == "qaoa-qiskit":
            return qaoa_validation_main(val_argv)
        if args.validation_kind == "qft-demo":
            return qft_demo_main(val_argv)
        parser.error(f"Unknown validation kind: {args.validation_kind}")
    if args.command == "plot":
        if args.plot_kind == "perf-sweep":
            return _plot_perf_sweep(args)
        if args.plot_kind == "perf-cases":
            return _plot_perf_cases(args)
        if args.plot_kind == "qaoa-pruning":
            return _plot_qaoa_pruning(args)
        parser.error(f"Unknown plot kind: {args.plot_kind}")
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

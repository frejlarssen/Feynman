#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from plot_qaoa_pruning_sweep import main as plot_qaoa_main
from plot_sv_prefetcher_cases import main as plot_perf_cases_main
from plot_sv_prefetcher_sweep import main as plot_perf_main
from qaoa_pruning_sweep.main import main as qaoa_pruning_main
from sv_prefetcher_sweep.main import main as perf_sweep_main
from validation.qaoa_qiskit_validation import main as qaoa_validation_main
from validation.qft_demo import main as qft_demo_main


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


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "perf-sweep":
        return perf_sweep_main(entry_script=Path(__file__).resolve(), argv=_sweep_argv(args))
    if args.command == "qaoa-pruning":
        sweep_argv = _sweep_argv(args)
        if args.no_plot:
            sweep_argv.append("--no-plot")
        return qaoa_pruning_main(entry_script=Path(__file__).resolve(), argv=sweep_argv)
    if args.command == "validation":
        val_argv = _validation_argv(args)
        if args.validation_kind == "qaoa-qiskit":
            return qaoa_validation_main(val_argv)
        if args.validation_kind == "qft-demo":
            return qft_demo_main(val_argv)
        parser.error(f"Unknown validation kind: {args.validation_kind}")
    if args.command == "plot":
        if args.plot_kind == "perf-sweep":
            return plot_perf_main(
                [
                    "--summary-csv",
                    args.summary_csv,
                    "--y-column",
                    args.y_column,
                    "--mode",
                    args.mode,
                    *(["--include-failures"] if args.include_failures else []),
                    *(["--output", args.output] if args.output else []),
                    *(["--title", args.title] if args.title else []),
                    *(
                        ["--label-fontsize", str(args.label_fontsize)]
                        if args.label_fontsize is not None
                        else []
                    ),
                ]
            )
        if args.plot_kind == "perf-cases":
            return plot_perf_cases_main(
                [
                    "--summary-csv",
                    args.summary_csv,
                    "--y-column",
                    args.y_column,
                    *(["--include-failures"] if args.include_failures else []),
                    *(["--varied-value", args.varied_value] if args.varied_value else []),
                    *(["--output", args.output] if args.output else []),
                    *(["--title", args.title] if args.title else []),
                    *(
                        ["--label-fontsize", str(args.label_fontsize)]
                        if args.label_fontsize is not None
                        else []
                    ),
                ]
            )
        if args.plot_kind == "qaoa-pruning":
            return plot_qaoa_main(
                [
                    "--summary-csv",
                    args.summary_csv,
                    "--time-column",
                    args.time_column,
                    "--fidelity-column",
                    args.fidelity_column,
                    "--xscale",
                    args.xscale,
                    *(["--include-failures"] if args.include_failures else []),
                    *(["--output", args.output] if args.output else []),
                    *(["--title", args.title] if args.title else []),
                    *(
                        ["--label-fontsize", str(args.label_fontsize)]
                        if args.label_fontsize is not None
                        else []
                    ),
                ]
            )
        parser.error(f"Unknown plot kind: {args.plot_kind}")
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

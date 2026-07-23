#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import math
import statistics
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sweeplib.plot_style import (
    LINE_COLOR_PRIMARY,
    LINE_COLOR_SECONDARY,
    apply_plot_fontsizes,
    configure_headless_matplotlib,
    single_column_figure_size,
)

METRIC_LABELS = {
    "elapsed_seconds": "Wall-clock time [s]",
    "simulate_stage_elapsed_seconds": "simulate_batch stage span [s]",
    "simulate_task_instance_seconds_sum": "Summed simulate_batch task-instance time [s]",
    "simulate_autotuning_seconds_sum": "Summed worker autotuning time [s]",
    "simulate_autotuning_seconds_mean": "Mean worker autotuning time [s]",
    "simulate_worker_full_seconds_sum": "Summed worker full time [s]",
    "simulate_worker_full_seconds_mean": "Mean worker full time [s]",
    "simulate_worker_simulate_calls_seconds_sum": "Summed pure simulate() time [s]",
    "simulate_worker_simulate_calls_seconds_mean": "Mean pure simulate() time [s]",
}

METRIC_TITLES = {
    "elapsed_seconds": "Cloud benchmark wall-clock time",
    "simulate_stage_elapsed_seconds": "Cloud benchmark simulate stage span",
    "simulate_task_instance_seconds_sum": "Cloud benchmark summed simulate task time",
    "simulate_autotuning_seconds_sum": "Cloud benchmark summed worker autotuning time",
    "simulate_autotuning_seconds_mean": "Cloud benchmark mean worker autotuning time",
    "simulate_worker_full_seconds_sum": "Cloud benchmark summed worker full time",
    "simulate_worker_full_seconds_mean": "Cloud benchmark mean worker full time",
    "simulate_worker_simulate_calls_seconds_sum": "Cloud benchmark summed pure simulate() time",
    "simulate_worker_simulate_calls_seconds_mean": "Cloud benchmark mean pure simulate() time",
}


def _load_rows(summary_csv: Path) -> list[dict[str, str]]:
    with summary_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
    if not rows:
        raise RuntimeError(f"No rows found in benchmark summary: {summary_csv}")
    return rows


def _successful_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    successful = [row for row in rows if row.get("state", "").strip() == "success"]
    if not successful:
        raise RuntimeError("No successful benchmark rows found in summary CSV.")
    return successful


def _to_groups(rows: list[dict[str, str]], *, metric: str) -> dict[int, list[float]]:
    groups: dict[int, list[float]] = {}
    for row in rows:
        pods = int(row["target_num_pods"])
        raw_value = row.get(metric, "").strip()
        if not raw_value:
            continue
        elapsed = float(raw_value)
        if math.isnan(elapsed):
            continue
        groups.setdefault(pods, []).append(elapsed)
    if not groups:
        raise RuntimeError(f"No plottable {metric} rows found.")
    return groups


def _default_output(summary_csv: Path, *, metric: str) -> Path:
    return summary_csv.parent / f"cloud_benchmark_{metric}_vs_pods.pdf"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot cloud benchmark wall-clock time versus target pod count."
    )
    parser.add_argument(
        "--summary-csv",
        required=True,
        type=Path,
        help="Benchmark summary CSV produced by benchmark_cloud_pod_sweep.sh.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output PDF path. Defaults next to summary.csv.",
    )
    parser.add_argument(
        "--title",
        default=None,
        help="Optional plot title. Defaults depend on the selected metric.",
    )
    parser.add_argument(
        "--label-fontsize",
        type=float,
        default=None,
        help="Optional fontsize override for plot labels.",
    )
    parser.add_argument(
        "--metric",
        choices=tuple(METRIC_LABELS),
        default="elapsed_seconds",
        help="Summary CSV column to plot.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary_csv = args.summary_csv.resolve()
    if not summary_csv.exists():
        raise FileNotFoundError(f"Benchmark summary CSV not found: {summary_csv}")

    rows = _load_rows(summary_csv)
    rows_success = _successful_rows(rows)
    groups = _to_groups(rows_success, metric=args.metric)
    experiment_names = sorted(
        {
            row.get("experiment_name", "").strip()
            for row in rows_success
            if row.get("experiment_name", "").strip()
        }
    )

    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_plot_fontsizes(plt=plt, label_fontsize=args.label_fontsize)

    fig, ax = plt.subplots(figsize=single_column_figure_size())
    x_sorted = sorted(groups)

    scatter_xs: list[int] = []
    scatter_ys: list[float] = []
    for pods in x_sorted:
        for elapsed in groups[pods]:
            scatter_xs.append(pods)
            scatter_ys.append(elapsed)

    ax.scatter(
        scatter_xs,
        scatter_ys,
        color=LINE_COLOR_PRIMARY,
        alpha=0.8,
        s=36,
        label="Runs",
    )

    mean_ys = [statistics.mean(groups[pods]) for pods in x_sorted]
    std_ys = [statistics.stdev(groups[pods]) if len(groups[pods]) > 1 else 0.0 for pods in x_sorted]
    ax.errorbar(
        x_sorted,
        mean_ys,
        yerr=std_ys,
        color=LINE_COLOR_SECONDARY,
        fmt="o-",
        capsize=4,
        linewidth=1.2,
        markersize=3.5,
        label="Mean +/- std",
    )

    ax.set_xlabel("Target pods")
    ax.set_ylabel(METRIC_LABELS[args.metric])
    title = args.title if args.title is not None else METRIC_TITLES[args.metric]
    if experiment_names:
        title = f"{title}: {', '.join(experiment_names)}"
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()

    output_path = (
        args.output.resolve()
        if args.output is not None
        else _default_output(summary_csv, metric=args.metric)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)

    print(f"Loaded {len(rows_success)} successful rows from {summary_csv}")
    print(f"Saved plot to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

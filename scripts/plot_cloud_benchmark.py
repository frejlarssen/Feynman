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
    "simulate_task_instance_seconds_mean": "Mean simulate_batch task-instance time [s]",
    "simulate_autotuning_seconds_sum": "Summed worker autotuning time [s]",
    "simulate_autotuning_seconds_mean": "Mean worker autotuning time [s]",
    "simulate_worker_full_seconds_sum": "Summed worker full time [s]",
    "simulate_worker_full_seconds_mean": "Mean worker full time [s]",
    "simulate_worker_simulate_calls_seconds_sum": "Summed pure simulate() time [s]",
    "simulate_worker_simulate_calls_seconds_mean": "Mean pure simulate() time [s]",
}

METRIC_TITLES = {
    "elapsed_seconds": "Cloud wall time",
    "simulate_stage_elapsed_seconds": "Cloud simulate span",
    "simulate_task_instance_seconds_sum": "Summed simulate task time",
    "simulate_task_instance_seconds_mean": "Mean simulate task time",
    "simulate_autotuning_seconds_sum": "Summed autotuning time",
    "simulate_autotuning_seconds_mean": "Mean autotuning time",
    "simulate_worker_full_seconds_sum": "Summed worker time",
    "simulate_worker_full_seconds_mean": "Mean worker time",
    "simulate_worker_simulate_calls_seconds_sum": "Summed simulate() time",
    "simulate_worker_simulate_calls_seconds_mean": "Mean simulate() time",
}
EFFICIENCY_LINE_COLOR = "#2F4858"
EFFICIENCY_DEFAULT_METRICS = {
    "elapsed_seconds",
    "simulate_stage_elapsed_seconds",
}


def _metric_value(row: dict[str, str], *, metric: str) -> float | None:
    if metric == "simulate_task_instance_seconds_mean":
        raw_sum = row.get("simulate_task_instance_seconds_sum", "").strip()
        raw_count = row.get("simulate_finished_task_instance_count", "").strip()
        if not raw_sum or not raw_count:
            return None
        count = int(raw_count)
        if count <= 0:
            return None
        return float(raw_sum) / count

    raw_value = row.get(metric, "").strip()
    if not raw_value:
        return None
    return float(raw_value)


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
        label_kind = (row.get("label_kind") or "").strip()
        raw_x = (row.get("target_label_value") or "").strip()
        if not raw_x and label_kind == "target_num_batches":
            raw_x = (row.get("target_num_batches") or "").strip()
        if not raw_x:
            continue
        x_value = int(raw_x)
        value = _metric_value(row, metric=metric)
        if value is None:
            continue
        elapsed = value
        if math.isnan(elapsed):
            continue
        groups.setdefault(x_value, []).append(elapsed)
    if not groups:
        raise RuntimeError(f"No plottable {metric} rows found.")
    return groups


def _summary_label_kind(rows: list[dict[str, str]]) -> str:
    kinds = {
        (row.get("label_kind") or "").strip()
        for row in rows
        if (row.get("label_kind") or "").strip()
    }
    if len(kinds) == 1:
        return next(iter(kinds))
    return "target_num_batches"


def _label_axis_text(label_kind: str) -> str:
    if label_kind == "pool_slots":
        return "Pool slots"
    return "Target batches"


def _default_output(summary_csv: Path, *, metric: str, label_kind: str) -> Path:
    suffix = "pool_slots" if label_kind == "pool_slots" else "batches"
    return summary_csv.parent / f"cloud_benchmark_{metric}_vs_{suffix}.pdf"


def _default_aggregate_csv(summary_csv: Path, *, metric: str, label_kind: str) -> Path:
    suffix = "pool_slots" if label_kind == "pool_slots" else "batches"
    return summary_csv.parent / f"cloud_benchmark_{metric}_vs_{suffix}.csv"


def _default_title(summary_csv: Path, *, metric: str, experiment_tags: list[str]) -> str:
    if metric in {"elapsed_seconds", "simulate_stage_elapsed_seconds"}:
        return "Strong scaling"
    return METRIC_TITLES[metric]


def _metric_axis_scales(*, metric: str, label_kind: str) -> tuple[str, str]:
    xscale = "log" if label_kind == "pool_slots" else "linear"
    yscale = "log" if metric == "elapsed_seconds" else "linear"
    return (xscale, yscale)


def _strong_scaling_efficiency_percent(
    *,
    x_sorted: list[int],
    mean_ys: list[float],
) -> list[float]:
    if len(x_sorted) != len(mean_ys):
        raise ValueError("x_sorted and mean_ys must have the same length.")
    if not x_sorted:
        return []

    baseline_x = x_sorted[0]
    baseline_time = mean_ys[0]
    if baseline_x <= 0 or baseline_time <= 0.0:
        raise ValueError("Baseline x value and baseline time must be positive.")

    efficiencies: list[float] = []
    for x_value, elapsed in zip(x_sorted, mean_ys, strict=True):
        if x_value <= 0 or elapsed <= 0.0:
            efficiencies.append(float("nan"))
            continue
        efficiencies.append(100.0 * baseline_time * baseline_x / (elapsed * x_value))
    return efficiencies


def _should_plot_efficiency(*, metric: str, no_efficiency: bool) -> bool:
    if no_efficiency:
        return False
    return metric in EFFICIENCY_DEFAULT_METRICS


def _write_aggregate_csv(
    *,
    output_path: Path,
    label_kind: str,
    x_sorted: list[int],
    groups: dict[int, list[float]],
    mean_ys: list[float],
    std_ys: list[float],
    efficiency_ys: list[float] | None,
) -> None:
    x_label = _label_axis_text(label_kind)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=(
                x_label.lower().replace(" ", "_"),
                "num_runs",
                "mean",
                "std",
                "strong_scaling_efficiency_percent",
            ),
        )
        writer.writeheader()
        for idx, x_value in enumerate(x_sorted):
            efficiency_value = ""
            if efficiency_ys is not None:
                current = efficiency_ys[idx]
                if not math.isnan(current):
                    efficiency_value = f"{current:.6f}"
            writer.writerow(
                {
                    x_label.lower().replace(" ", "_"): x_value,
                    "num_runs": len(groups[x_value]),
                    "mean": f"{mean_ys[idx]:.6f}",
                    "std": f"{std_ys[idx]:.6f}",
                    "strong_scaling_efficiency_percent": efficiency_value,
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot cloud benchmark metrics versus the benchmark label value."
    )
    parser.add_argument(
        "--summary-csv",
        required=True,
        type=Path,
        help="Benchmark summary CSV produced by the cloud benchmark sweep scripts.",
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
    parser.add_argument(
        "--no-efficiency",
        action="store_true",
        help="Disable the strong-scaling efficiency line.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    summary_csv = args.summary_csv.resolve()
    if not summary_csv.exists():
        raise FileNotFoundError(f"Benchmark summary CSV not found: {summary_csv}")

    rows = _load_rows(summary_csv)
    rows_success = _successful_rows(rows)
    label_kind = _summary_label_kind(rows_success)
    groups = _to_groups(rows_success, metric=args.metric)
    experiment_tags = sorted(
        {
            row.get("experiment_tag", "").strip()
            for row in rows_success
            if row.get("experiment_tag", "").strip()
        }
    )

    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker

    apply_plot_fontsizes(plt=plt, label_fontsize=args.label_fontsize)

    fig, ax = plt.subplots(figsize=single_column_figure_size())
    x_sorted = sorted(groups)

    scatter_xs: list[int] = []
    scatter_ys: list[float] = []
    for x_value in x_sorted:
        for elapsed in groups[x_value]:
            scatter_xs.append(x_value)
            scatter_ys.append(elapsed)

    ax.scatter(
        scatter_xs,
        scatter_ys,
        color=LINE_COLOR_PRIMARY,
        alpha=0.8,
        s=36,
        label="Runs",
    )

    mean_ys = [statistics.mean(groups[x_value]) for x_value in x_sorted]
    std_ys = [
        statistics.stdev(groups[x_value]) if len(groups[x_value]) > 1 else 0.0
        for x_value in x_sorted
    ]
    efficiency_ys: list[float] | None = None
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

    legend_handles, legend_labels = ax.get_legend_handles_labels()
    if _should_plot_efficiency(metric=args.metric, no_efficiency=args.no_efficiency):
        efficiency_ys = _strong_scaling_efficiency_percent(
            x_sorted=x_sorted,
            mean_ys=mean_ys,
        )
        ax_efficiency = ax.twinx()
        (efficiency_line,) = ax_efficiency.plot(
            x_sorted,
            efficiency_ys,
            color=EFFICIENCY_LINE_COLOR,
            marker="D",
            linestyle="--",
            linewidth=1.2,
            markersize=4.0,
            label="Strong-scaling efficiency",
        )
        ax_efficiency.set_ylabel("Efficiency [%]")
        ax_efficiency.set_ylim(bottom=0.0)
        legend_handles.append(efficiency_line)
        legend_labels.append("Strong-scaling efficiency")

    ax.set_xlabel(_label_axis_text(label_kind))
    ax.set_ylabel(METRIC_LABELS[args.metric])
    xscale, yscale = _metric_axis_scales(metric=args.metric, label_kind=label_kind)
    ax.set_xscale(xscale)
    ax.set_yscale(yscale)
    ax.set_xticks(x_sorted)
    ax.xaxis.set_major_formatter(mticker.FormatStrFormatter("%d"))
    ax.xaxis.set_minor_locator(mticker.NullLocator())
    title = (
        args.title
        if args.title is not None
        else _default_title(summary_csv, metric=args.metric, experiment_tags=experiment_tags)
    )
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    if len(legend_labels) > 2:
        fig.legend(
            legend_handles,
            legend_labels,
            loc="lower center",
            bbox_to_anchor=(0.5, -0.02),
            frameon=False,
            ncol=min(2, len(legend_labels)),
        )
        fig.tight_layout(rect=(0.0, 0.12, 0.96, 1.0))
    else:
        ax.legend(legend_handles, legend_labels, loc="best", frameon=False)
        fig.tight_layout()

    output_path = (
        args.output.resolve()
        if args.output is not None
        else _default_output(summary_csv, metric=args.metric, label_kind=label_kind)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    aggregate_csv_path = _default_aggregate_csv(
        summary_csv,
        metric=args.metric,
        label_kind=label_kind,
    )
    _write_aggregate_csv(
        output_path=aggregate_csv_path,
        label_kind=label_kind,
        x_sorted=x_sorted,
        groups=groups,
        mean_ys=mean_ys,
        std_ys=std_ys,
        efficiency_ys=efficiency_ys,
    )

    print(f"Loaded {len(rows_success)} successful rows from {summary_csv}")
    print(f"Saved plot to {output_path}")
    print(f"Saved aggregate CSV to {aggregate_csv_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

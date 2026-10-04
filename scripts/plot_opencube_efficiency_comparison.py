#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
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
from scripts.sweeplib.plotting import strong_scaling_series


DEFAULT_DIRECTORY = REPO_ROOT / "data/outputs/experiments/cn07_vs_cn09"
SYSTEMS = (
    ("cn07 (AmpereOne)", "summary_merged_cn07.csv", LINE_COLOR_PRIMARY, "o"),
    ("cn09 (Rhea)", "summary_merged_cn09.csv", LINE_COLOR_SECONDARY, "s"),
)


def load_efficiency(summary_path: Path, *, y_column: str) -> tuple[list[int], list[float], list[float], list[float]]:
    with summary_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    series = strong_scaling_series(rows, y_column, varied_param="omp_threads")
    if len(series) != 1:
        raise ValueError(f"Expected one benchmark case in {summary_path}, found {len(series)}.")
    return next(iter(series.values()))


def write_plotted_data(
    output_path: Path,
    datasets: list[tuple[str, list[int], list[float], list[float], list[float]]],
    *,
    y_column: str,
) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow((
            "system",
            "omp_threads",
            "y_column",
            "mean",
            "sample_std",
            "speedup",
            "relative_parallel_efficiency_percent",
        ))
        for system, threads, means, stds, efficiencies in datasets:
            baseline = means[0]
            for thread, mean, std, efficiency in zip(threads, means, stds, efficiencies):
                writer.writerow((system, thread, y_column, mean, std, baseline / mean, efficiency))


def render_comparison(*, directory: Path, output_path: Path, y_column: str) -> tuple[Path, Path]:
    datasets = []
    for label, filename, _, _ in SYSTEMS:
        threads, means, stds, efficiencies = load_efficiency(
            directory / filename,
            y_column=y_column,
        )
        datasets.append((label, threads, means, stds, efficiencies))

    configure_headless_matplotlib()
    import matplotlib.pyplot as plt

    apply_plot_fontsizes(plt=plt)
    fig, ax = plt.subplots(figsize=single_column_figure_size())
    for (label, _, color, marker), (_, threads, _, _, efficiencies) in zip(SYSTEMS, datasets):
        ax.plot(
            threads,
            efficiencies,
            color=color,
            marker=marker,
            linewidth=2,
            markersize=5,
            markeredgewidth=1,
            label=label,
        )

    all_threads = sorted({thread for _, threads, *_ in datasets for thread in threads})
    ax.axhline(100, color="0.45", linestyle="--", linewidth=1, label="Ideal")
    ax.set_xticks(all_threads)
    ax.set_xlabel("Number of OpenMP threads")
    ax.set_ylabel("Efficiency (%)")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(loc="lower left", framealpha=0.9)
    fig.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)

    speedup_output_path = output_path.with_name("cn07_vs_cn09_speedup.pdf")
    fig, ax = plt.subplots(figsize=single_column_figure_size())
    for (label, _, color, marker), (_, threads, means, _, _) in zip(SYSTEMS, datasets):
        baseline = means[0]
        ax.plot(
            threads,
            [baseline / mean for mean in means],
            color=color,
            marker=marker,
            linewidth=2,
            markersize=5,
            markeredgewidth=1,
            label=label,
        )

    baseline_threads = min(all_threads)
    ax.plot(
        all_threads,
        [thread / baseline_threads for thread in all_threads],
        color="0.45",
        linestyle="--",
        linewidth=1,
        label="Ideal",
    )
    ax.set_xticks(all_threads)
    ax.set_xlabel("Number of OpenMP threads")
    ax.set_ylabel(f"Speedup relative to {baseline_threads} threads")
    ax.set_ylim(bottom=0)
    ax.grid(axis="y", alpha=0.3)
    ax.legend(loc="upper left", framealpha=0.9)
    fig.tight_layout()
    fig.savefig(speedup_output_path, dpi=160)
    plt.close(fig)

    plotted_data_path = output_path.with_name(f"{output_path.stem}_plotted_data.csv")
    write_plotted_data(plotted_data_path, datasets, y_column=y_column)
    return speedup_output_path, plotted_data_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare cn07 and cn09 OpenMP strong-scaling efficiency."
    )
    parser.add_argument("--directory", type=Path, default=DEFAULT_DIRECTORY)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--y-column", default="total_full_s")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output or args.directory / "cn07_vs_cn09_efficiency.pdf"
    speedup_output, plotted_data = render_comparison(
        directory=args.directory,
        output_path=output,
        y_column=args.y_column,
    )
    print(f"Saved plot: {output}")
    print(f"Saved plot: {speedup_output}")
    print(f"Saved plotted data: {plotted_data}")


if __name__ == "__main__":
    main()

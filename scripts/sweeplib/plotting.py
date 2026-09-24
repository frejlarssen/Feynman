from __future__ import annotations

import csv
import math
import json
import statistics
from pathlib import Path

from .plot_style import (
    apply_plot_fontsizes,
    configure_headless_matplotlib,
    format_metric_label,
    single_column_figure_size,
)


def _to_float(value: str) -> float:
    if value is None or value == "":
        raise ValueError("empty value")
    return float(value)


def load_xy_from_summary(
    *,
    summary_path: Path,
    x_column: str,
    y_column: str,
    include_failures: bool,
) -> tuple[list[float], list[float]]:
    xs: list[float] = []
    ys: list[float] = []

    with summary_path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if not include_failures and int(row.get("returncode", "1")) != 0:
                continue
            try:
                x = _to_float(row.get(x_column, ""))
                y = _to_float(row.get(y_column, ""))
            except ValueError:
                continue
            if math.isnan(x) or math.isnan(y):
                continue
            xs.append(x)
            ys.append(y)

    if not xs:
        raise RuntimeError("No plottable rows found in summary CSV.")
    return xs, ys


def render_sweep_plot(
    *,
    xs: list[float],
    ys: list[float],
    mode: str,
    x_label: str,
    y_label: str,
    title: str,
    output_path: Path,
    label_fontsize: float | None = None,
) -> None:
    configure_headless_matplotlib()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    apply_plot_fontsizes(plt=plt, label_fontsize=label_fontsize)

    fig, ax = plt.subplots(figsize=single_column_figure_size())

    if mode == "scatter":
        ax.scatter(xs, ys, s=36, alpha=0.8)
    else:
        grouped: dict[float, list[float]] = {}
        for x, y in zip(xs, ys):
            grouped.setdefault(x, []).append(y)

        x_sorted = sorted(grouped)
        y_mean = [statistics.mean(grouped[x]) for x in x_sorted]
        y_std = [
            statistics.stdev(grouped[x]) if len(grouped[x]) > 1 else 0.0
            for x in x_sorted
        ]
        ax.errorbar(
            x_sorted,
            y_mean,
            yerr=y_std,
            fmt="o-",
            capsize=4,
            linewidth=1.2,
            markersize=3.5,
        )

    display_x = format_metric_label(x_label)
    display_y = format_metric_label(y_label)
    ax.set_xlabel(display_x)
    ax.set_ylabel(display_y)
    ax.set_title(title or f"{display_y} vs {display_x}")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)


def default_plot_output_path(summary_path: Path, *, x_column: str, y_column: str) -> Path:
    return summary_path.parent / f"plot_{y_column}_vs_{x_column}.pdf"


def strong_scaling_series(rows: list[dict[str, str]], y_column: str) -> dict:
    """Aggregate successful timings per case; efficiency counts all MPI ranks."""
    grouped = {}
    settings = {}
    fixed_fields = (
        "batch_size", "p", "r", "fraction", "threshold", "dense",
        "circuit_file_used", "omp_threads_per_worker", "feynman_env",
    )
    for row in rows:
        if int(row.get("returncode", "1")) != 0:
            continue
        case = row.get("case_name") or "default"
        signature = tuple(
            json.dumps(json.loads(row[key]), sort_keys=True)
            if key == "feynman_env" and row.get(key) else row.get(key, "")
            for key in fixed_fields
        )
        if case in settings and settings[case] != signature:
            raise ValueError(f"Strong scaling requires fixed workload/settings within case {case!r}.")
        settings[case] = signature
        try:
            ranks = float(row["varied_value"])
            elapsed = float(row[y_column])
        except (KeyError, ValueError, TypeError):
            continue
        if not (math.isfinite(ranks) and ranks >= 1 and ranks.is_integer()
                and math.isfinite(elapsed) and elapsed > 0):
            continue
        grouped.setdefault(case, {}).setdefault(int(ranks), []).append(elapsed)
    result = {}
    for case, samples in grouped.items():
        ranks = sorted(samples)
        means = [statistics.mean(samples[p]) for p in ranks]
        stds = [statistics.stdev(samples[p]) if len(samples[p]) > 1 else 0.0 for p in ranks]
        efficiency = [100 * means[0] * ranks[0] / (t * p) for p, t in zip(ranks, means)]
        result[case] = (ranks, means, stds, efficiency)
    if not result:
        raise RuntimeError("No successful positive timings for strong scaling.")
    return result


def render_perf_sweep_plot(
    *, summary_path: Path, y_column: str, include_failures: bool,
    mode: str, x_label: str, title: str, output_path: Path,
    label_fontsize: float | None = None,
) -> None:
    """Shared dispatch for initial sweeps, explicit plotting, and regeneration."""
    with summary_path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    varied = {row.get("varied_param", "") for row in rows}
    # Efficiency is meaningful for elapsed time, not arbitrary telemetry.
    if varied != {"ranks"} or y_column not in {"total_full_s", "total_sim_s", "walltime_s"}:
        xs, ys = load_xy_from_summary(
            summary_path=summary_path, x_column="varied_value", y_column=y_column,
            include_failures=include_failures,
        )
        return render_sweep_plot(
            xs=xs, ys=ys, mode=mode, x_label=x_label, y_label=y_column,
            title=title, output_path=output_path, label_fontsize=label_fontsize,
        )

    series = strong_scaling_series(rows, y_column)
    configure_headless_matplotlib()
    import matplotlib.pyplot as plt
    apply_plot_fontsizes(plt=plt, label_fontsize=label_fontsize)
    fig, ax = plt.subplots(figsize=single_column_figure_size())
    efficiency_ax = ax.twinx()
    ranks_all = sorted({p for ranks, *_ in series.values() for p in ranks})
    positions = {p: i for i, p in enumerate(ranks_all)}
    width = 0.8 / len(series)
    baselines = []
    for i, (case, (ranks, means, stds, efficiencies)) in enumerate(series.items()):
        color = f"C{i % 10}"
        xs = [positions[p] + (i - (len(series) - 1) / 2) * width for p in ranks]
        label = "" if case == "default" else f"{case} "
        ax.bar(xs, means, width=width, yerr=stds, capsize=2,
               facecolor="none", edgecolor=color, hatch="///", label=f"{label}time")
        efficiency_ax.plot(xs, efficiencies, "o-", color=color,
                           markersize=3, label=f"{label}efficiency")
        baselines.append(f"{label}P₀={ranks[0]}")
    ax.set_xticks(range(len(ranks_all)), [str(p) for p in ranks_all])
    ax.set_xlabel("Number of MPI processes")
    timing_labels = {
        "total_full_s": "Execution time including I/O [s]",
        "total_sim_s": "Simulation time [s]",
        "walltime_s": "Launcher wall time [s]",
    }
    ax.set_ylabel(timing_labels[y_column])
    ax.set_yscale("log")
    efficiency_ax.set_ylabel("Relative parallel efficiency (%)")
    efficiency_ax.set_ylim(bottom=0)
    ax.set_title(title or "Strong scaling")
    ax.grid(axis="y", alpha=0.3)
    handles, labels = ax.get_legend_handles_labels()
    handles2, labels2 = efficiency_ax.get_legend_handles_labels()
    ax.legend(handles + handles2, labels + labels2, fontsize="small", loc="lower left")
    fig.text(0.5, 0.01, "Baseline: " + "; ".join(baselines), ha="center", fontsize="small")
    fig.tight_layout(rect=(0, 0.06, 1, 1))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)

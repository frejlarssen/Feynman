from __future__ import annotations

import csv
import math
import os
import statistics
from pathlib import Path


def configure_headless_matplotlib() -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mplconfig_feynman")
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp/xdg_cache_feynman")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)


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
) -> None:
    configure_headless_matplotlib()

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 5))

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
            linewidth=1.4,
            markersize=5,
        )

    ax.set_xlabel(x_label)
    ax.set_ylabel(y_label)
    ax.set_title(title or f"{y_label} vs {x_label}")
    ax.grid(True, alpha=0.3)
    fig.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)


def default_plot_output_path(summary_path: Path, *, x_column: str, y_column: str) -> Path:
    return summary_path.parent / f"plot_{y_column}_vs_{x_column}.pdf"

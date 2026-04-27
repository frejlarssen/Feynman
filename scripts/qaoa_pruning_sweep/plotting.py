from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from sweeplib.plotting import apply_plot_fontsizes, configure_headless_matplotlib


def _to_float(value: str) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_rows(path: Path, time_column: str, fidelity_column: str) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    thresholds: list[float] = []
    times: list[float] = []
    fidelities: list[float] = []

    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("returncode", "1") != "0":
                continue
            t = _to_float(row.get("threshold", ""))
            tm = _to_float(row.get(time_column, ""))
            fid = _to_float(row.get(fidelity_column, ""))
            if t is None or tm is None or fid is None:
                continue
            thresholds.append(t)
            times.append(tm)
            fidelities.append(fid)

    if not thresholds:
        raise ValueError("No successful rows with valid threshold/time/fidelity values.")

    order = np.argsort(np.asarray(thresholds, dtype=float))
    return (
        np.asarray(thresholds, dtype=float)[order],
        np.asarray(times, dtype=float)[order],
        np.asarray(fidelities, dtype=float)[order],
    )


def default_output(summary_csv: Path) -> Path:
    return summary_csv.with_name(f"{summary_csv.stem}_time_fidelity.pdf")


def plot_time_fidelity(
    *,
    summary_csv: Path,
    output: Path | None = None,
    time_column: str = "total_full_s",
    fidelity_column: str = "fidelity_to_reference",
    title: str = "QAOA pruning sweep",
    xscale: str = "symlog",
    label_fontsize: float | None = None,
) -> Path:
    summary_path = summary_csv.resolve()
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary CSV not found: {summary_path}")
    if xscale not in {"linear", "log", "symlog"}:
        raise ValueError(f"Unsupported xscale: {xscale}")

    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    thresholds, times, fidelities = load_rows(
        summary_path, time_column=time_column, fidelity_column=fidelity_column
    )

    fig, ax_time = plt.subplots(figsize=(8.0, 4.8))
    ax_fidelity = ax_time.twinx()

    time_line = ax_time.plot(
        thresholds,
        times,
        marker="o",
        linewidth=1.8,
        color="#1f77b4",
        label=f"{time_column}",
    )[0]
    fidelity_line = ax_fidelity.plot(
        thresholds,
        fidelities,
        marker="s",
        linewidth=1.6,
        color="#d62728",
        label=f"{fidelity_column}",
    )[0]

    if xscale == "symlog":
        positives = thresholds[thresholds > 0]
        linthresh = float(np.min(positives)) if positives.size else 1e-12
        ax_time.set_xscale("symlog", linthresh=linthresh)
    else:
        ax_time.set_xscale(xscale)

    ax_time.set_xlabel("threshold t")
    ax_time.set_ylabel(time_column)
    ax_fidelity.set_ylabel(fidelity_column)
    ax_time.yaxis.label.set_color("#1f77b4")
    ax_fidelity.yaxis.label.set_color("#d62728")
    ax_time.tick_params(axis="y", colors="#1f77b4")
    ax_fidelity.tick_params(axis="y", colors="#d62728")
    ax_fidelity.set_ylim(0.0, 1.02)
    ax_time.grid(True, linestyle="--", alpha=0.35)
    ax_time.set_title(title)
    ax_time.legend(handles=[time_line, fidelity_line], loc="best")

    apply_plot_fontsizes(plt=plt, label_fontsize=label_fontsize)
    fig.tight_layout()

    output_path = output.resolve() if output else default_output(summary_path)
    fig.savefig(output_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return output_path

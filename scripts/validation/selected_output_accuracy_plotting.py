from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from sweeplib.plot_style import (
    DEFAULT_LINEWIDTH_PRIMARY,
    DEFAULT_LINEWIDTH_SECONDARY,
    DEFAULT_MARKER_PRIMARY,
    DEFAULT_MARKER_SECONDARY,
    LINE_COLOR_PRIMARY,
    LINE_COLOR_SECONDARY,
    apply_plot_fontsizes,
    configure_headless_matplotlib,
    stacked_single_column_figure_size,
)


def _to_float(value: str | None) -> float | None:
    try:
        return None if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return None


def _load_summary_rows(summary_csv: Path) -> list[dict[str, str]]:
    with summary_csv.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _load_run_title(summary_csv: Path) -> str:
    summary_json = summary_csv.parent / "summary.json"
    if not summary_json.exists():
        return summary_csv.parent.name
    try:
        payload = json.loads(summary_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return summary_csv.parent.name
    experiment_name = payload.get("experiment_name")
    return str(experiment_name) if isinstance(experiment_name, str) and experiment_name else summary_csv.parent.name


def _comparison_grouped_by_case(
    comparison_csv: Path,
) -> dict[str, list[tuple[float, float]]]:
    grouped: dict[str, list[tuple[float, float]]] = {}
    with comparison_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            case_name = row.get("case_name", "")
            reference_population = _to_float(row.get("reference_population"))
            approx_population = _to_float(row.get("approx_population"))
            if not case_name or reference_population is None or approx_population is None:
                continue
            grouped.setdefault(case_name, []).append((reference_population, approx_population))
    if not grouped:
        raise ValueError(f"No plottable case rows found in comparison CSV: {comparison_csv}")
    return grouped


def recompute_population_fidelity_by_case(comparison_csv: Path) -> dict[str, float]:
    grouped = _comparison_grouped_by_case(comparison_csv)
    fidelities: dict[str, float] = {}
    for case_name, values in grouped.items():
        ref_mass = sum(reference_population for reference_population, _ in values)
        approx_nonnegative_mass = sum(
            max(approx_population, 0.0) for _, approx_population in values
        )
        if ref_mass <= 0.0 or approx_nonnegative_mass <= 0.0:
            fidelities[case_name] = 0.0
            continue
        bc = sum(
            math.sqrt(reference_population * max(approx_population, 0.0))
            for reference_population, approx_population in values
        )
        fidelities[case_name] = (bc * bc) / (ref_mass * approx_nonnegative_mass)
    return fidelities


def load_fraction_tradeoff_rows(
    *,
    summary_csv: Path,
    comparison_csv: Path,
    time_column: str,
) -> list[dict[str, Any]]:
    summary_rows = _load_summary_rows(summary_csv)
    fidelities = recompute_population_fidelity_by_case(comparison_csv)

    rows: list[dict[str, Any]] = []
    for row in summary_rows:
        case_name = row.get("case_name", "")
        fraction = _to_float(row.get("fraction"))
        runtime_s = _to_float(row.get(time_column))
        if not case_name or fraction is None or runtime_s is None:
            continue
        rows.append(
            {
                "case_name": case_name,
                "fraction": fraction,
                "runtime_s": runtime_s,
                "population_fidelity": 1.0 if case_name == "exact_reference" else fidelities.get(case_name, 0.0),
                "is_reference": case_name == "exact_reference",
            }
        )

    if not rows:
        raise ValueError(f"No plottable rows found in summary CSV: {summary_csv}")

    non_reference_fractions = {
        float(row["fraction"]) for row in rows if not bool(row["is_reference"])
    }
    if len(non_reference_fractions) < 2:
        raise ValueError(
            "Need at least two distinct non-reference fraction values to plot a fraction tradeoff."
        )

    return sorted(rows, key=lambda item: (float(item["fraction"]), str(item["case_name"])))


def default_output(summary_csv: Path) -> Path:
    return summary_csv.parent / "fraction_tradeoff.pdf"


def plot_fraction_tradeoff(
    *,
    summary_csv: Path,
    comparison_csv: Path | None = None,
    output: Path | None = None,
    time_column: str = "internal_runtime_s",
    title: str | None = None,
    label_fontsize: float | None = None,
) -> Path:
    summary_path = summary_csv.resolve()
    if not summary_path.exists():
        raise FileNotFoundError(f"Summary CSV not found: {summary_path}")
    comparison_path = (
        comparison_csv.resolve()
        if comparison_csv is not None
        else (summary_path.parent / "comparison.csv").resolve()
    )
    if not comparison_path.exists():
        raise FileNotFoundError(f"Comparison CSV not found: {comparison_path}")

    rows = load_fraction_tradeoff_rows(
        summary_csv=summary_path,
        comparison_csv=comparison_path,
        time_column=time_column,
    )
    plot_title = title if title else _load_run_title(summary_path)

    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_plot_fontsizes(plt=plt, label_fontsize=label_fontsize)

    approx_rows = [row for row in rows if not row["is_reference"]]
    reference_row = next((row for row in rows if row["is_reference"]), None)

    x_approx = [float(row["fraction"]) for row in approx_rows]
    runtime_approx = [float(row["runtime_s"]) for row in approx_rows]
    fidelity_approx = [float(row["population_fidelity"]) for row in approx_rows]

    fig, (ax_time, ax_fidelity) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=stacked_single_column_figure_size(),
        constrained_layout=True,
    )

    ax_time.plot(
        x_approx,
        runtime_approx,
        marker=DEFAULT_MARKER_PRIMARY,
        linewidth=DEFAULT_LINEWIDTH_PRIMARY,
        color=LINE_COLOR_PRIMARY,
        label="Approximate case",
    )
    ax_time.set_ylabel("Runtime [s]")
    ax_time.grid(True, alpha=0.3, linewidth=0.5)

    ax_fidelity.plot(
        x_approx,
        fidelity_approx,
        marker=DEFAULT_MARKER_SECONDARY,
        linewidth=DEFAULT_LINEWIDTH_SECONDARY,
        color=LINE_COLOR_SECONDARY,
        label="Selected-population fidelity",
    )
    ax_fidelity.set_xlabel("Chunk-2 sampling fraction")
    ax_fidelity.set_ylabel("Population fidelity")
    ax_fidelity.set_ylim(0.0, 1.05)
    ax_fidelity.grid(True, alpha=0.3, linewidth=0.5)

    if reference_row is not None:
        x_ref = [float(reference_row["fraction"])]
        y_ref_runtime = [float(reference_row["runtime_s"])]
        y_ref_fidelity = [float(reference_row["population_fidelity"])]
        ax_time.scatter(x_ref, y_ref_runtime, color="black", marker="*", s=42, zorder=3, label="Exact reference")
        ax_fidelity.scatter(x_ref, y_ref_fidelity, color="black", marker="*", s=42, zorder=3)
        ax_time.legend(loc="upper left", frameon=False, handlelength=1.8)

    all_fractions = sorted({float(row["fraction"]) for row in rows})
    ax_fidelity.set_xticks(all_fractions)
    ax_fidelity.set_xlim(min(all_fractions) - 0.02, max(all_fractions) + 0.02)

    ax_time.set_title(plot_title)

    output_path = output.resolve() if output is not None else default_output(summary_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any

from sweeplib.plot_style import (
    DEFAULT_LINEWIDTH_PRIMARY,
    DEFAULT_LINEWIDTH_SECONDARY,
    DEFAULT_MARKERSIZE,
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
        return "Selected-output Google-RQC validation"
    try:
        payload = json.loads(summary_json.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "Selected-output Google-RQC validation"

    config = payload.get("config", {})
    if isinstance(config, dict):
        circuit_spec = config.get("circuit")
        if isinstance(circuit_spec, dict):
            generator = str(circuit_spec.get("generator", "")).lower()
            rows = circuit_spec.get("rows")
            cols = circuit_spec.get("cols")
            cycles = circuit_spec.get("cycles")
            if generator == "google_rqc" and rows is not None and cols is not None and cycles is not None:
                return f"Google-RQC selected-output tradeoff ({rows}x{cols}, m={cycles})"

    return "Selected-output Google-RQC validation"


def _format_estimator_label(estimator: str) -> str:
    key = str(estimator).strip().lower()
    if key == "amplitude_square":
        return "Amplitude-square"
    if key == "cross_seeded":
        return "Cross-seeded"
    return estimator.replace("_", "-")


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


def _infer_tradeoff_param(rows: list[dict[str, Any]]) -> str:
    approx_rows = [row for row in rows if not bool(row["is_reference"])]
    fractions = {float(row["fraction"]) for row in approx_rows}
    thresholds = {float(row["threshold"]) for row in approx_rows}
    if len(fractions) >= 2 and len(thresholds) <= 1:
        return "fraction"
    if len(thresholds) >= 2 and len(fractions) <= 1:
        return "threshold"
    raise ValueError(
        "Selected-output tradeoff auto-plot requires a one-parameter sweep in fraction or threshold."
    )


def load_tradeoff_rows(
    *,
    summary_csv: Path,
    comparison_csv: Path,
    time_column: str,
) -> tuple[list[dict[str, Any]], str]:
    summary_rows = _load_summary_rows(summary_csv)
    fidelities = recompute_population_fidelity_by_case(comparison_csv)

    rows: list[dict[str, Any]] = []
    for row in summary_rows:
        case_name = row.get("case_name", "")
        fraction = _to_float(row.get("fraction"))
        threshold = _to_float(row.get("threshold"))
        runtime_s = _to_float(row.get(time_column))
        if not case_name or fraction is None or threshold is None or runtime_s is None:
            continue
        rows.append(
            {
                "case_name": case_name,
                "fraction": fraction,
                "threshold": threshold,
                "runtime_s": runtime_s,
                "population_estimator": row.get("population_estimator", ""),
                "population_fidelity": 1.0 if case_name == "exact_reference" else fidelities.get(case_name, 0.0),
                "is_reference": case_name == "exact_reference",
            }
        )

    if not rows:
        raise ValueError(f"No plottable rows found in summary CSV: {summary_csv}")

    tradeoff_param = _infer_tradeoff_param(rows)
    return (
        sorted(rows, key=lambda item: (float(item[tradeoff_param]), str(item["case_name"]))),
        tradeoff_param,
    )


def default_output(summary_csv: Path) -> Path:
    return summary_csv.parent / "selected_output_tradeoff.pdf"


def _format_fraction_tick(value: float, *, has_reference_one: bool) -> str:
    if has_reference_one and abs(value - 1.0) < 1e-12:
        return "1"
    if has_reference_one and 0.98 <= value < 1.0:
        return ""
    if abs(value - round(value)) < 1e-12:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _default_output_for_param(summary_csv: Path, tradeoff_param: str) -> Path:
    if tradeoff_param == "fraction":
        return summary_csv.parent / "fraction_tradeoff.pdf"
    if tradeoff_param == "threshold":
        return summary_csv.parent / "threshold_tradeoff.pdf"
    return default_output(summary_csv)


def _tradeoff_axis_label(tradeoff_param: str) -> str:
    if tradeoff_param == "fraction":
        return "Chunk-2 sampling fraction"
    if tradeoff_param == "threshold":
        return "Threshold $t$"
    return tradeoff_param.replace("_", " ").title()


def plot_selected_output_tradeoff(
    *,
    summary_csv: Path,
    comparison_csv: Path | None = None,
    output: Path | None = None,
    time_column: str = "internal_runtime_s",
    title: str | None = None,
    label_fontsize: float | None = None,
    exclude_thresholds: tuple[float, ...] = (),
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

    rows, tradeoff_param = load_tradeoff_rows(
        summary_csv=summary_path,
        comparison_csv=comparison_path,
        time_column=time_column,
    )
    if tradeoff_param == "threshold" and exclude_thresholds:
        rows = [
            row
            for row in rows
            if row["is_reference"]
            or not any(
                math.isclose(
                    float(row["threshold"]),
                    excluded,
                    rel_tol=1e-12,
                    abs_tol=0.0,
                )
                for excluded in exclude_thresholds
            )
        ]
    plot_title = title if title else _load_run_title(summary_path)

    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_plot_fontsizes(plt=plt, label_fontsize=label_fontsize)

    approx_rows = [row for row in rows if not row["is_reference"]]
    reference_row = next((row for row in rows if row["is_reference"]), None)
    estimator_keys = list(
        dict.fromkeys(
            str(row.get("population_estimator", "")).strip() or "unspecified"
            for row in approx_rows
        )
    )
    grouped_rows: dict[str, list[dict[str, Any]]] = {
        estimator: sorted(
            [
                row
                for row in approx_rows
                if (str(row.get("population_estimator", "")).strip() or "unspecified") == estimator
            ],
            key=lambda item: (float(item[tradeoff_param]), str(item["case_name"])),
        )
        for estimator in estimator_keys
    }
    multiple_estimators = len(estimator_keys) > 1
    estimator_styles = [
        (LINE_COLOR_PRIMARY, DEFAULT_MARKER_PRIMARY),
        (LINE_COLOR_SECONDARY, DEFAULT_MARKER_SECONDARY),
        ("#2ca02c", "^"),
        ("#9467bd", "D"),
    ]

    fig, (ax_time, ax_fidelity) = plt.subplots(
        2,
        1,
        sharex=True,
        figsize=stacked_single_column_figure_size(),
        constrained_layout=True,
    )

    for index, estimator in enumerate(estimator_keys):
        series = grouped_rows[estimator]
        if not series:
            continue
        color, marker = estimator_styles[index % len(estimator_styles)]
        x_values = [float(row[tradeoff_param]) for row in series]
        runtime_values = [float(row["runtime_s"]) for row in series]
        fidelity_values = [float(row["population_fidelity"]) for row in series]
        label = (
            _format_estimator_label(estimator) if multiple_estimators else "Approximate case"
        )
        ax_time.plot(
            x_values,
            runtime_values,
            marker=marker,
            linewidth=DEFAULT_LINEWIDTH_PRIMARY,
            markersize=DEFAULT_MARKERSIZE,
            color=color,
            label=label,
        )
        ax_fidelity.plot(
            x_values,
            fidelity_values,
            marker=marker,
            linewidth=DEFAULT_LINEWIDTH_SECONDARY,
            markersize=DEFAULT_MARKERSIZE,
            color=color,
            label=label,
        )

    ax_time.set_ylabel("Runtime [s]")
    ax_time.grid(True, alpha=0.3, linewidth=0.5)

    ax_fidelity.set_xlabel(_tradeoff_axis_label(tradeoff_param))
    ax_fidelity.set_ylabel("Population fidelity")
    ax_fidelity.set_ylim(0.0, 1.05)
    ax_fidelity.grid(True, alpha=0.3, linewidth=0.5)

    if tradeoff_param == "threshold" and grouped_rows:
        ax_fidelity_drop = ax_fidelity.twinx()
        for estimator in estimator_keys:
            series = grouped_rows[estimator]
            baseline_row = next(
                (
                    row
                    for row in series
                    if math.isclose(float(row["threshold"]), 0.0, abs_tol=1e-300)
                ),
                None,
            )
            if baseline_row is None:
                continue
            baseline_fidelity = float(baseline_row["population_fidelity"])
            ax_fidelity_drop.plot(
                [float(row["threshold"]) for row in series],
                [
                    max(
                        abs(baseline_fidelity - float(row["population_fidelity"])),
                        1e-16,
                    )
                    for row in series
                ],
                color=LINE_COLOR_SECONDARY,
                marker=DEFAULT_MARKER_SECONDARY,
                linestyle="--",
                linewidth=DEFAULT_LINEWIDTH_SECONDARY,
                markersize=DEFAULT_MARKERSIZE,
            )
        ax_fidelity_drop.set_yscale("log")
        ax_fidelity_drop.set_ylabel(
            "$|F(t)-F(0)|$", color=LINE_COLOR_SECONDARY
        )
        ax_fidelity_drop.tick_params(axis="y", colors=LINE_COLOR_SECONDARY)
        ax_fidelity_drop.spines["right"].set_color(LINE_COLOR_SECONDARY)

    if reference_row is not None:
        x_ref = [float(reference_row[tradeoff_param])]
        y_ref_runtime = [float(reference_row["runtime_s"])]
        y_ref_fidelity = [float(reference_row["population_fidelity"])]
        ax_time.scatter(x_ref, y_ref_runtime, color="black", marker="*", s=42, zorder=3, label="Exact reference")
        ax_fidelity.scatter(x_ref, y_ref_fidelity, color="black", marker="*", s=42, zorder=3)
    ax_time.legend(loc="upper right", frameon=False, handlelength=1.8)

    all_x = sorted({float(row[tradeoff_param]) for row in rows})
    if tradeoff_param == "fraction":
        ax_fidelity.set_xticks(all_x)
        has_reference_one = any(abs(value - 1.0) < 1e-12 for value in all_x)
        ax_fidelity.set_xticklabels(
            [_format_fraction_tick(value, has_reference_one=has_reference_one) for value in all_x]
        )
        ax_fidelity.set_xlim(min(all_x) - 0.02, max(all_x) + 0.02)
    elif tradeoff_param == "threshold":
        positives = [value for value in all_x if value > 0.0]
        linthresh = min(positives) if positives else 1e-12
        ax_time.set_xscale("symlog", linthresh=linthresh)
        ax_fidelity.set_xscale("symlog", linthresh=linthresh)
        ax_fidelity.set_xticks(all_x)
        labels = []
        for value in all_x:
            if abs(value) < 1e-300:
                labels.append("0")
            else:
                labels.append(f"{value:.0e}".replace("+0", "").replace("+", ""))
        ax_fidelity.set_xticklabels(
            labels,
            rotation=45,
            ha="right",
            rotation_mode="anchor",
        )
        tick_labels = ax_fidelity.get_xticklabels()
        if len(tick_labels) >= 2:
            from matplotlib.transforms import ScaledTranslation

            tick_labels[-2].set_transform(
                tick_labels[-2].get_transform()
                + ScaledTranslation(-3.0 / 72.0, 0.0, fig.dpi_scale_trans)
            )
            tick_labels[-1].set_transform(
                tick_labels[-1].get_transform()
                + ScaledTranslation(3.0 / 72.0, 0.0, fig.dpi_scale_trans)
            )

    ax_time.set_title(plot_title)

    output_path = (
        output.resolve()
        if output is not None
        else _default_output_for_param(summary_path, tradeoff_param)
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=200)
    plt.close(fig)
    return output_path


def plot_fraction_tradeoff(
    *,
    summary_csv: Path,
    comparison_csv: Path | None = None,
    output: Path | None = None,
    time_column: str = "internal_runtime_s",
    title: str | None = None,
    label_fontsize: float | None = None,
) -> Path:
    return plot_selected_output_tradeoff(
        summary_csv=summary_csv,
        comparison_csv=comparison_csv,
        output=output,
        time_column=time_column,
        title=title,
        label_fontsize=label_fontsize,
    )

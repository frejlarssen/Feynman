#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.airflow_gantt import (  # noqa: E402
    build_gantt_records,
    load_task_instances_json,
)
from scripts.sweeplib.plot_style import (  # noqa: E402
    SINGLE_COLUMN_FIGURE_HEIGHT_IN,
    apply_plot_fontsizes,
    configure_headless_matplotlib,
    ieee_column_width_inches,
)

configure_headless_matplotlib()
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch


def _seconds(value) -> float:
    return value.timestamp()


def _categorical_colors(values: list[str]) -> dict[str, tuple[float, float, float, float]]:
    palette = list(plt.get_cmap("tab10").colors)
    return {
        value: palette[index % len(palette)]
        for index, value in enumerate(values)
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot multiple Airflow runs as stacked by-resource Gantt charts with shared x-axis."
    )
    parser.add_argument(
        "--task-instances-json",
        type=Path,
        action="append",
        required=True,
        help="Saved Airflow taskInstances JSON payload. Can be repeated.",
    )
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        help="Panel label for the corresponding --task-instances-json. Can be repeated.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output PDF path.",
    )
    return parser.parse_args()


def _default_labels(paths: list[Path]) -> list[str]:
    labels: list[str] = []
    for path in paths:
        parent = path.parent
        maybe_case = parent.parent.parent.name if parent.parent.parent != parent else parent.name
        labels.append(maybe_case or parent.name)
    return labels


def main() -> int:
    args = parse_args()
    json_paths = [path.resolve() for path in args.task_instances_json]
    labels = list(args.label)
    if labels and len(labels) != len(json_paths):
        raise ValueError("Pass either no --label values or exactly one per --task-instances-json.")
    if not labels:
        labels = _default_labels(json_paths)

    payloads = [load_task_instances_json(path) for path in json_paths]
    record_groups = [build_gantt_records([payload]) for payload in payloads]
    if any(not records for records in record_groups):
        raise RuntimeError("At least one input run has no plottable task records.")

    task_categories = list(
        dict.fromkeys(
            str(record["task"])
            for records in record_groups
            for record in records
        )
    )
    task_colors = _categorical_colors(task_categories)

    base_fontsize = apply_plot_fontsizes(plt=plt)
    tick_fontsize = max(1.0, base_fontsize - 0.9)
    annotation_fontsize = max(1.0, base_fontsize - 1.5)

    fig_width = ieee_column_width_inches()
    per_panel_height = max(SINGLE_COLUMN_FIGURE_HEIGHT_IN * 0.55, 1.25)
    fig_height = max(
        SINGLE_COLUMN_FIGURE_HEIGHT_IN + 0.65,
        0.95 + per_panel_height * len(record_groups),
    )
    fig, axes = plt.subplots(
        len(record_groups),
        1,
        figsize=(fig_width, fig_height),
        sharex=True,
        squeeze=False,
    )
    axes_flat = [ax for row in axes for ax in row]
    fig.subplots_adjust(left=0.14, right=0.995, bottom=0.12, top=0.70, hspace=0.28)

    max_end_seconds = 0.0
    for records in record_groups:
        for record in records:
            max_end_seconds = max(max_end_seconds, _seconds(record["end"]))

    for ax, label, records in zip(axes_flat, labels, record_groups, strict=True):
        y_categories = list(dict.fromkeys(str(record["resource"]) for record in records))
        y_positions = {category: index for index, category in enumerate(y_categories)}

        for record in records:
            start = _seconds(record["start"])
            end = _seconds(record["end"])
            width = max(0.0, end - start)
            y_value = str(record["resource"])
            task = str(record["task"])
            y_position = y_positions[y_value]

            ax.barh(
                y_position,
                width,
                left=start,
                height=0.7,
                color=task_colors[task],
                edgecolor="black",
                linewidth=0.5,
            )

            map_index = str(record.get("map_index") or "").strip()
            if map_index and width >= 0.25:
                ax.text(
                    start + width / 2.0,
                    y_position,
                    map_index,
                    ha="center",
                    va="center",
                    fontsize=annotation_fontsize,
                    color="black",
                )

        ax.set_yticks(range(len(y_categories)))
        ax.set_yticklabels(y_categories)
        ax.tick_params(axis="both", labelsize=tick_fontsize)
        ax.grid(axis="x", linestyle="--", alpha=0.35)
        ax.set_axisbelow(True)
        ax.text(
            -0.12,
            1.03,
            label,
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=base_fontsize,
        )

    axes_flat[-1].set_xlabel("Time (s)")
    axes_flat[-1].set_xlim(0.0, max_end_seconds * 1.03)

    legend_handles = [
        Patch(facecolor=task_colors[task], edgecolor="black", label=task)
        for task in task_categories
    ]
    legend = fig.legend(
        handles=legend_handles,
        title="Task",
        loc="upper center",
        bbox_to_anchor=(0.5, 0.98),
        frameon=True,
        ncol=max(1, min(2, len(legend_handles))),
        borderpad=0.8,
        labelspacing=0.5,
    )
    legend.get_title().set_fontsize(base_fontsize)

    output_path = args.output.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format=output_path.suffix.lstrip(".") or "pdf")
    plt.close(fig)

    print(f'wrote stacked Gantt to "{output_path}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

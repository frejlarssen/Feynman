from __future__ import annotations

import datetime as dt
import json
import os
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
import requests

from scripts.sweeplib.plot_style import (
    SINGLE_COLUMN_FIGURE_HEIGHT_IN,
    apply_plot_fontsizes,
    configure_headless_matplotlib,
    ieee_column_width_inches,
)
from constants import (
    AIRFLOW_BEARER_TOKEN,
    AIRFLOW_PASSWORD,
    AIRFLOW_SESSION_COOKIE,
    AIRFLOW_USERNAME,
    BASE_URL,
)

configure_headless_matplotlib()


def _auth_candidates() -> list[tuple[str, dict[str, str]]]:
    candidates: list[tuple[str, dict[str, str]]] = []
    if AIRFLOW_BEARER_TOKEN:
        candidates.append(("bearer_token", {"authorization": f"Bearer {AIRFLOW_BEARER_TOKEN}"}))
    if AIRFLOW_SESSION_COOKIE:
        candidates.append(("session_cookie", {"session_cookie": AIRFLOW_SESSION_COOKIE}))
    if AIRFLOW_USERNAME and AIRFLOW_PASSWORD:
        candidates.append(
            (
                "basic_auth",
                {
                    "username": AIRFLOW_USERNAME,
                    "password": AIRFLOW_PASSWORD,
                },
            )
        )
    candidates.append(("none", {}))
    return candidates


def build_session(auth_mode: str, auth_payload: dict[str, str]) -> requests.Session:
    session = requests.Session()
    session.headers["Content-type"] = "application/json"
    session.headers["Accept"] = "application/json"

    if auth_mode == "bearer_token":
        session.headers["Authorization"] = auth_payload["authorization"]
    elif auth_mode == "session_cookie":
        session.cookies.set("session", auth_payload["session_cookie"])
    elif auth_mode == "basic_auth":
        session.auth = (auth_payload["username"], auth_payload["password"])

    return session


def get_json(session: requests.Session, url: str) -> dict[str, Any]:
    response = session.get(url, timeout=30)
    if response.status_code == 401:
        raise RuntimeError("Airflow API returned 401 Unauthorized.")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object from Airflow API, got {type(payload).__name__}.")
    return payload


def fetch_task_instances(*, dag_id: str, run_id: str, base_url: str = BASE_URL) -> dict[str, Any]:
    url = f"{base_url}/dags/{dag_id}/dagRuns/{run_id}/taskInstances"
    unauthorized_modes: list[str] = []
    last_error: Exception | None = None
    for auth_mode, auth_payload in _auth_candidates():
        session = build_session(auth_mode, auth_payload)
        try:
            return get_json(session, url)
        except RuntimeError as err:
            if "401 Unauthorized" not in str(err):
                raise
            unauthorized_modes.append(auth_mode)
            last_error = err
            continue
    tried = ", ".join(unauthorized_modes) if unauthorized_modes else "none"
    raise RuntimeError(
        "Airflow API returned 401 Unauthorized for auth mode(s): "
        f"{tried}. Set a working AIRFLOW_USERNAME/AIRFLOW_PASSWORD, "
        "AIRFLOW_BEARER_TOKEN, or AIRFLOW_SESSION_COOKIE."
    ) from last_error


def _normalize_map_index(value: Any) -> int | str:
    if value in (None, "", -1, "-1"):
        return -1
    try:
        return int(value)
    except (TypeError, ValueError):
        return str(value)


def normalize_task_instances_payload(
    payload: dict[str, Any],
    *,
    default_run_id: str = "",
    default_pool: str = "unknown_pool",
    default_pool_slots: int = 1,
) -> dict[str, Any]:
    task_instances = payload.get("task_instances")
    if not isinstance(task_instances, list):
        raise ValueError("Expected payload with a task_instances array.")

    normalized_task_instances: list[dict[str, Any]] = []
    for task_instance in task_instances:
        if not isinstance(task_instance, dict):
            continue
        normalized = dict(task_instance)
        # `airflow tasks states-for-dag-run --output json` does not include pool
        # metadata, so use an explicit unknown placeholder.
        normalized["pool"] = str(task_instance.get("pool") or default_pool)
        try:
            normalized["pool_slots"] = int(task_instance.get("pool_slots", default_pool_slots))
        except (TypeError, ValueError):
            normalized["pool_slots"] = default_pool_slots
        normalized["dag_run_id"] = str(task_instance.get("dag_run_id") or default_run_id)
        normalized["map_index"] = _normalize_map_index(task_instance.get("map_index"))
        normalized_task_instances.append(normalized)

    return {"task_instances": normalized_task_instances}


def load_task_instances_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(payload).__name__}.")
    return normalize_task_instances_payload(payload)


def load_task_states_json(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"Expected JSON array in {path}, got {type(payload).__name__}.")
    return [row for row in payload if isinstance(row, dict)]


def task_states_to_task_instances_payload(
    rows: list[dict[str, Any]],
    *,
    run_id: str,
) -> dict[str, Any]:
    return normalize_task_instances_payload({"task_instances": rows}, default_run_id=run_id)


def _parse_dates(payload: dict[str, Any]) -> list[tuple[dt.datetime, dict[str, Any], str]]:
    task_instances = payload.get("task_instances")
    if not isinstance(task_instances, list):
        raise ValueError("Expected payload with a task_instances array.")

    dates: list[tuple[dt.datetime, dict[str, Any], str]] = []
    for ti in task_instances:
        if not isinstance(ti, dict):
            continue
        start_raw = ti.get("start_date")
        end_raw = ti.get("end_date")
        if not start_raw or not end_raw:
            continue
        execution_date = dt.datetime.fromisoformat(str(start_raw))
        end_date = dt.datetime.fromisoformat(str(end_raw))
        dates.append((execution_date, ti, "start"))
        dates.append((end_date, ti, "stop"))

    dates.sort(key=lambda item: item[0])
    return dates


def _compute_pool_sizes(
    dates: list[tuple[dt.datetime, dict[str, Any], str]],
) -> dict[str, int]:
    pool_sizes: defaultdict[str, int] = defaultdict(int)
    current: defaultdict[str, int] = defaultdict(int)

    for _, ti, event in dates:
        pool = str(ti["pool"])
        pool_slots = int(ti["pool_slots"])
        if event == "start":
            current[pool] += pool_slots
        else:
            current[pool] -= pool_slots
        pool_sizes[pool] = max(pool_sizes[pool], current[pool])

    return dict(pool_sizes)


def build_gantt_records(
    payloads: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    dates: list[tuple[dt.datetime, dict[str, Any], str]] = []
    for payload in payloads:
        dates.extend(_parse_dates(payload))

    if not dates:
        raise RuntimeError("No finished Airflow task instances found for Gantt plotting.")

    dates.sort(key=lambda item: item[0])
    pool_sizes = _compute_pool_sizes(dates)

    slots = {
        pool: [None] * pool_size
        for pool, pool_size in pool_sizes.items()
    }
    records: list[dict[str, Any]] = []

    for timestamp, ti, event in dates:
        if event != "start":
            continue

        pool = str(ti["pool"])
        slot_pool = slots[pool]
        found = False
        for index, next_available in enumerate(slot_pool):
            if next_available is None or next_available <= timestamp:
                found = True
                break
        if not found:
            raise ValueError("incoherent planning :(")

        end_time = dt.datetime.fromisoformat(str(ti["end_date"]))
        slot_pool[index] = end_time

        map_index_raw = _normalize_map_index(ti.get("map_index", -1))
        map_index = None if map_index_raw == -1 else str(map_index_raw)
        records.append(
            {
                "task": ti["task_id"],
                "start": timestamp,
                "end": end_time,
                "resource": f"Slot {index}",
                "map_index": map_index,
                "dag_run_id": ti.get("dag_run_id", ""),
            }
        )

    t0 = dates[0][0]
    delta = t0 - dt.datetime.fromtimestamp(0, tz=t0.tzinfo)
    for record in records:
        record["start"] = record["start"] - delta
        record["end"] = record["end"] - delta

    records.sort(key=lambda item: float(_seconds_from_relative_datetime(item["start"])))
    return records


def _seconds_from_relative_datetime(value: dt.datetime) -> float:
    return value.timestamp()


def _categorical_colors(values: list[str]) -> dict[str, tuple[float, float, float, float]]:
    palette = list(plt.get_cmap("tab10").colors)
    return {
        value: palette[index % len(palette)]
        for index, value in enumerate(values)
    }


def _render_timeline(
    records: list[dict[str, Any]],
    *,
    y_key: str,
    color_key: str,
    output_path: Path,
    x_label: str,
    annotate_map_indices: bool = True,
) -> Path:
    if not records:
        raise RuntimeError("No records available to render.")

    y_categories = list(dict.fromkeys(str(record[y_key]) for record in records))
    color_categories = list(dict.fromkeys(str(record[color_key]) for record in records))
    y_positions = {category: index for index, category in enumerate(y_categories)}
    colors = _categorical_colors(color_categories)
    task_counts = Counter(str(record.get("task", "")) for record in records)

    base_fontsize = apply_plot_fontsizes(plt=plt)
    dense_timeline = len(y_categories) >= 16
    tick_fontsize = max(1.0, base_fontsize - (1.7 if dense_timeline else 0.9))
    annotation_fontsize = max(1.0, base_fontsize - (2.1 if dense_timeline else 1.5))

    fig_width = ieee_column_width_inches()
    # Keep enough height for every row without producing poster-length figures
    # for pools with dozens of slots.  The legend needs fixed space; dense
    # timelines then grow by only 0.115 inches per row.
    fig_height = max(
        SINGLE_COLUMN_FIGURE_HEIGHT_IN + 0.40,
        1.65 + 0.115 * len(y_categories),
    )
    fig, ax = plt.subplots(figsize=(fig_width, fig_height))

    for record in records:
        start = _seconds_from_relative_datetime(record["start"])
        end = _seconds_from_relative_datetime(record["end"])
        width = max(0.0, end - start)
        y_value = str(record[y_key])
        color_value = str(record[color_key])
        y_position = y_positions[y_value]

        ax.barh(
            y_position,
            width,
            left=start,
            height=0.68 if dense_timeline else 0.7,
            color=colors[color_value],
            edgecolor="black",
            linewidth=0.35 if dense_timeline else 0.5,
        )

        label = str(record.get("map_index") or "").strip()
        task = str(record.get("task", ""))
        suppress_dense_simulate_labels = task == "simulate_batch" and task_counts[task] > 12
        if (
            annotate_map_indices
            and not suppress_dense_simulate_labels
            and label
            and width >= 0.25
        ):
            ax.text(
                start + width / 2.0,
                y_position,
                label,
                ha="center",
                va="center",
                fontsize=annotation_fontsize,
                color="black",
            )

    ax.set_yticks(range(len(y_categories)))
    if y_key == "resource" and all(category.startswith("Slot ") for category in y_categories):
        ax.set_yticklabels([category.removeprefix("Slot ") for category in y_categories])
        ax.set_ylabel("Slot")
    else:
        ax.set_yticklabels(y_categories)
    ax.set_xlabel(x_label)
    ax.tick_params(axis="both", labelsize=tick_fontsize)
    ax.grid(axis="x", linestyle="--", alpha=0.35)
    ax.set_axisbelow(True)

    legend_handles = [
        Patch(facecolor=colors[value], edgecolor="black", label=value)
        for value in color_categories
    ]
    legend = ax.legend(
        handles=legend_handles,
        title=color_key.replace("_", " ").title(),
        loc="upper center",
        bbox_to_anchor=(0.50, 0.985),
        bbox_transform=fig.transFigure,
        borderaxespad=0.0,
        borderpad=0.8,
        labelspacing=0.5,
        ncol=max(1, min(2, len(legend_handles))),
    )
    legend.get_title().set_fontsize(base_fontsize)
    legend.set_in_layout(False)

    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    legend_bbox = legend.get_window_extent(renderer).transformed(fig.transFigure.inverted())
    timeline_top = max(0.48, legend_bbox.y0 - 0.025)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, timeline_top), pad=0.25)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, format=output_path.suffix.lstrip(".") or "svg")
    plt.close(fig)
    return output_path


def render_gantt_byresources(records: list[dict[str, Any]], *, output_path: Path) -> Path:
    return _render_timeline(
        records,
        y_key="resource",
        color_key="task",
        output_path=output_path,
        x_label="Time (s)",
    )


def render_gantt_bytask(records: list[dict[str, Any]], *, output_path: Path) -> Path:
    return _render_timeline(
        records,
        y_key="task",
        color_key="task",
        output_path=output_path,
        x_label="Time (s)",
        annotate_map_indices=False,
    )


def render_gantt_multiexec(records: list[dict[str, Any]], *, output_path: Path) -> Path:
    return _render_timeline(
        records,
        y_key="resource",
        color_key="dag_run_id",
        output_path=output_path,
        x_label="Time (s)",
    )

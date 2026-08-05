from __future__ import annotations

import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import plotly.express as px
import requests

from constants import (
    AIRFLOW_BEARER_TOKEN,
    AIRFLOW_PASSWORD,
    AIRFLOW_SESSION_COOKIE,
    AIRFLOW_USERNAME,
    BASE_URL,
    POOL_ALIAS,
)


def build_session() -> requests.Session:
    session = requests.Session()
    session.headers["Content-type"] = "application/json"
    session.headers["Accept"] = "application/json"

    if AIRFLOW_BEARER_TOKEN:
        session.headers["Authorization"] = f"Bearer {AIRFLOW_BEARER_TOKEN}"
    elif AIRFLOW_SESSION_COOKIE:
        session.cookies.set("session", AIRFLOW_SESSION_COOKIE)
    elif AIRFLOW_USERNAME and AIRFLOW_PASSWORD:
        session.auth = (AIRFLOW_USERNAME, AIRFLOW_PASSWORD)

    return session


def get_json(session: requests.Session, url: str) -> dict[str, Any]:
    response = session.get(url, timeout=30)
    if response.status_code == 401:
        raise RuntimeError(
            "Airflow API returned 401 Unauthorized. Set AIRFLOW_USERNAME and "
            "AIRFLOW_PASSWORD, AIRFLOW_BEARER_TOKEN, or AIRFLOW_SESSION_COOKIE."
        )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object from Airflow API, got {type(payload).__name__}.")
    return payload


def fetch_task_instances(*, dag_id: str, run_id: str, base_url: str = BASE_URL) -> dict[str, Any]:
    session = build_session()
    return get_json(session, f"{base_url}/dags/{dag_id}/dagRuns/{run_id}/taskInstances")


def load_task_instances_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}, got {type(payload).__name__}.")
    task_instances = payload.get("task_instances")
    if not isinstance(task_instances, list):
        raise ValueError(f"Expected key 'task_instances' with a JSON array in {path}.")
    return payload


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

        map_index_raw = ti.get("map_index", -1)
        map_index = None if int(map_index_raw) == -1 else str(map_index_raw)
        pool_alias = POOL_ALIAS.get(pool, pool)
        records.append(
            {
                "task": ti["task_id"],
                "start": timestamp,
                "end": end_time,
                "resource": f"{pool_alias}.{index}",
                "map_index": map_index,
                "dag_run_id": ti.get("dag_run_id", ""),
            }
        )

    t0 = dates[0][0]
    delta = t0 - dt.datetime.fromtimestamp(0, tz=t0.tzinfo)
    for record in records:
        record["start"] = record["start"] - delta
        record["end"] = record["end"] - delta

    records.sort(key=lambda item: (str(item["resource"]), str(item["task"])))
    return records


def render_gantt_byresources(records: list[dict[str, Any]], *, output_path: Path) -> Path:
    fig = px.timeline(
        records,
        x_start="start",
        x_end="end",
        y="resource",
        color="task",
        text="map_index",
        labels={
            "resource": "Resources",
            "task": "Task",
            "map_index": "Batch ID",
        },
        width=28 * 30,
        height=12 * 30,
        color_discrete_sequence=px.colors.qualitative.G10,
    )
    fig.update_xaxes(tickformat="%s", title="Time (s)")
    fig.update_traces(textposition="inside")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_image(output_path)
    return output_path


def render_gantt_bytask(records: list[dict[str, Any]], *, output_path: Path) -> Path:
    fig = px.timeline(
        records,
        x_start="start",
        x_end="end",
        y="task",
        labels={
            "resource": "Resources",
            "task": "Task",
            "map_index": "Batch ID",
        },
        width=28 * 30,
        height=12 * 30,
        color_discrete_sequence=px.colors.qualitative.G10,
    )
    fig.update_xaxes(tickformat="%s", title="Time (s)")
    fig.update_traces(textposition="inside")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_image(output_path)
    return output_path


def render_gantt_multiexec(records: list[dict[str, Any]], *, output_path: Path) -> Path:
    fig = px.timeline(
        records,
        x_start="start",
        x_end="end",
        y="resource",
        color="dag_run_id",
        labels={
            "resource": "Resources",
            "task": "Task",
            "map_index": "Batch ID",
            "dag_run_id": "DAG run",
        },
        width=28 * 30,
        height=12 * 30,
        color_discrete_sequence=px.colors.qualitative.G10,
    )
    fig.update_xaxes(tickformat="%s", title="Time (s)")
    fig.update_traces(textposition="inside")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.write_image(output_path)
    return output_path

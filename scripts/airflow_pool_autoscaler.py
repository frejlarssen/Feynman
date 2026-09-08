#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import math
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


TERMINAL_TASK_STATES = {
    "success",
    "failed",
    "skipped",
    "upstream_failed",
    "removed",
}
TERMINAL_DAG_STATES = {"success", "failed", "canceled"}


@dataclasses.dataclass(frozen=True)
class AutoscalerConfig:
    enabled: bool
    pool_name: str
    initial_pool_slots: int
    max_pool_slots: int
    target_completion_seconds: float
    check_interval_seconds: float
    warmup_seconds: float
    cooldown_seconds: float
    scale_factor: float
    task_id: str = "simulate_batch"
    restore_pool_on_exit: bool = True


@dataclasses.dataclass(frozen=True)
class Progress:
    total: int
    succeeded: int
    terminal: int
    running: int
    queued: int


@dataclasses.dataclass(frozen=True)
class ScaleDecision:
    should_scale: bool
    reason: str
    next_pool_slots: int
    throughput_batches_per_second: float | None
    projected_remaining_seconds: float | None
    target_remaining_seconds: float


def load_autoscaler_config(path: Path) -> AutoscalerConfig:
    with path.open("r", encoding="utf-8") as handle:
        root = json.load(handle)
    if not isinstance(root, dict):
        raise ValueError("Cloud benchmark config must be a JSON object.")
    raw = root.get("autoscaler")
    if not isinstance(raw, dict):
        raise ValueError("Cloud benchmark config must contain an 'autoscaler' object.")

    allowed = {field.name for field in dataclasses.fields(AutoscalerConfig)}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f"Unknown autoscaler config fields: {', '.join(unknown)}")

    required = {
        "enabled",
        "pool_name",
        "initial_pool_slots",
        "max_pool_slots",
        "target_completion_seconds",
        "check_interval_seconds",
        "warmup_seconds",
        "cooldown_seconds",
        "scale_factor",
    }
    missing = sorted(required - set(raw))
    if missing:
        raise ValueError(f"Missing autoscaler config fields: {', '.join(missing)}")

    def require_bool(name: str, default: bool | None = None) -> bool:
        value = raw.get(name, default)
        if not isinstance(value, bool):
            raise ValueError(f"autoscaler.{name} must be a JSON boolean.")
        return value

    config = AutoscalerConfig(
        enabled=require_bool("enabled"),
        pool_name=str(raw["pool_name"]).strip(),
        initial_pool_slots=int(raw["initial_pool_slots"]),
        max_pool_slots=int(raw["max_pool_slots"]),
        target_completion_seconds=float(raw["target_completion_seconds"]),
        check_interval_seconds=float(raw["check_interval_seconds"]),
        warmup_seconds=float(raw["warmup_seconds"]),
        cooldown_seconds=float(raw["cooldown_seconds"]),
        scale_factor=float(raw["scale_factor"]),
        task_id=str(raw.get("task_id", "simulate_batch")).strip(),
        restore_pool_on_exit=require_bool("restore_pool_on_exit", True),
    )
    if not config.enabled:
        raise ValueError("autoscaler.enabled must be true for an autoscaled run.")
    if not config.pool_name:
        raise ValueError("autoscaler.pool_name must be non-empty.")
    if not config.task_id:
        raise ValueError("autoscaler.task_id must be non-empty.")
    if config.initial_pool_slots <= 0:
        raise ValueError("autoscaler.initial_pool_slots must be > 0.")
    if config.max_pool_slots < config.initial_pool_slots:
        raise ValueError(
            "autoscaler.max_pool_slots must be >= autoscaler.initial_pool_slots."
        )
    if config.target_completion_seconds <= 0:
        raise ValueError("autoscaler.target_completion_seconds must be > 0.")
    if config.check_interval_seconds <= 0:
        raise ValueError("autoscaler.check_interval_seconds must be > 0.")
    if config.warmup_seconds < 0:
        raise ValueError("autoscaler.warmup_seconds must be >= 0.")
    if config.cooldown_seconds < 0:
        raise ValueError("autoscaler.cooldown_seconds must be >= 0.")
    if config.scale_factor <= 1:
        raise ValueError("autoscaler.scale_factor must be > 1.")
    return config


def summarize_progress(rows: list[dict[str, Any]], task_id: str) -> Progress:
    matching = []
    for row in rows:
        if str(row.get("task_id", "")).strip() != task_id:
            continue
        map_index = row.get("map_index")
        if map_index is not None and int(map_index) < 0:
            continue
        matching.append(row)
    states = [str(row.get("state", "")).strip().lower() for row in matching]
    return Progress(
        total=len(states),
        succeeded=sum(state == "success" for state in states),
        terminal=sum(state in TERMINAL_TASK_STATES for state in states),
        running=sum(state == "running" for state in states),
        queued=sum(state in {"scheduled", "queued"} for state in states),
    )


def decide_scale(
    *,
    config: AutoscalerConfig,
    progress: Progress,
    current_pool_slots: int,
    elapsed_seconds: float,
    window_elapsed_seconds: float,
    window_completed_batches: int,
    cooldown_remaining_seconds: float,
) -> ScaleDecision:
    target_remaining = max(0.0, config.target_completion_seconds - elapsed_seconds)
    throughput = None
    projected_remaining = None
    next_slots = current_pool_slots

    if progress.total == 0:
        reason = "waiting_for_mapped_tasks"
    elif progress.succeeded >= progress.total:
        reason = "all_batches_succeeded"
    elif current_pool_slots >= config.max_pool_slots:
        reason = "at_max_pool_slots"
    elif elapsed_seconds < config.warmup_seconds:
        reason = "warmup"
    elif cooldown_remaining_seconds > 0:
        reason = "cooldown"
    else:
        if window_elapsed_seconds > 0 and window_completed_batches > 0:
            throughput = window_completed_batches / window_elapsed_seconds
            projected_remaining = (progress.total - progress.succeeded) / throughput
        else:
            projected_remaining = math.inf

        if projected_remaining <= target_remaining:
            reason = "projected_to_meet_target"
        else:
            next_slots = min(
                config.max_pool_slots,
                max(current_pool_slots + 1, math.ceil(current_pool_slots * config.scale_factor)),
            )
            return ScaleDecision(
                should_scale=True,
                reason="projected_to_miss_target",
                next_pool_slots=next_slots,
                throughput_batches_per_second=throughput,
                projected_remaining_seconds=projected_remaining,
                target_remaining_seconds=target_remaining,
            )

    return ScaleDecision(
        should_scale=False,
        reason=reason,
        next_pool_slots=next_slots,
        throughput_batches_per_second=throughput,
        projected_remaining_seconds=projected_remaining,
        target_remaining_seconds=target_remaining,
    )


def _run_json(command: list[str]) -> Any:
    proc = subprocess.run(command, check=True, capture_output=True, text=True)
    return json.loads(proc.stdout)


def _task_states(dag_id: str, run_id: str) -> list[dict[str, Any]]:
    payload = _run_json(
        ["airflow", "tasks", "states-for-dag-run", dag_id, run_id, "--output", "json"]
    )
    if not isinstance(payload, list):
        raise ValueError("Expected Airflow task-state output to be a JSON array.")
    return [row for row in payload if isinstance(row, dict)]


def _dag_state(dag_id: str, run_id: str) -> str:
    proc = subprocess.run(
        ["airflow", "dags", "state", dag_id, run_id],
        check=True,
        capture_output=True,
        text=True,
    )
    lines = proc.stdout.strip().splitlines()
    if not lines:
        return ""
    last = lines[-1].strip()
    return last.split(",", 1)[0].strip().lower()


def _set_pool(config: AutoscalerConfig, slots: int) -> None:
    subprocess.run(
        [
            "airflow",
            "pools",
            "set",
            config.pool_name,
            str(slots),
            "Feynman adaptive simulation concurrency",
        ],
        check=True,
    )


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def _json_number(value: float | None) -> float | str | None:
    if value is None:
        return None
    if math.isinf(value):
        return "infinity"
    return value


def run_controller(
    *,
    config: AutoscalerConfig,
    dag_id: str,
    run_id: str,
    events_path: Path,
    summary_path: Path,
    stop_file: Path | None,
) -> int:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    window_started = started
    window_completed = 0
    last_scale_at: float | None = None
    current_slots = config.initial_pool_slots
    scale_events = 0
    final_reason = "unknown"
    last_progress = Progress(0, 0, 0, 0, 0)
    pool_initialized = False

    try:
        _set_pool(config, current_slots)
        pool_initialized = True
        with events_path.open("a", encoding="utf-8", buffering=1) as events:
            while True:
                now = time.monotonic()
                elapsed = now - started
                if stop_file is not None and stop_file.exists():
                    final_reason = "stop_requested"
                    break

                rows = _task_states(dag_id, run_id)
                progress = summarize_progress(rows, config.task_id)
                last_progress = progress
                cooldown_remaining = 0.0
                if last_scale_at is not None:
                    cooldown_remaining = max(
                        0.0, config.cooldown_seconds - (now - last_scale_at)
                    )
                decision = decide_scale(
                    config=config,
                    progress=progress,
                    current_pool_slots=current_slots,
                    elapsed_seconds=elapsed,
                    window_elapsed_seconds=now - window_started,
                    window_completed_batches=max(0, progress.succeeded - window_completed),
                    cooldown_remaining_seconds=cooldown_remaining,
                )
                event = {
                    "observed_at_utc": _iso_now(),
                    "elapsed_seconds": elapsed,
                    "pool_slots": current_slots,
                    "total_batches": progress.total,
                    "succeeded_batches": progress.succeeded,
                    "terminal_batches": progress.terminal,
                    "running_batches": progress.running,
                    "queued_batches": progress.queued,
                    "throughput_batches_per_second": (
                        decision.throughput_batches_per_second
                    ),
                    "projected_remaining_seconds": _json_number(
                        decision.projected_remaining_seconds
                    ),
                    "target_remaining_seconds": decision.target_remaining_seconds,
                    "decision": "scale" if decision.should_scale else "hold",
                    "reason": decision.reason,
                    "next_pool_slots": decision.next_pool_slots,
                }
                events.write(json.dumps(event, separators=(",", ":")) + "\n")
                print(json.dumps(event, separators=(",", ":")), flush=True)

                if decision.should_scale:
                    _set_pool(config, decision.next_pool_slots)
                    current_slots = decision.next_pool_slots
                    scale_events += 1
                    last_scale_at = time.monotonic()
                    window_started = last_scale_at
                    window_completed = progress.succeeded

                if progress.total > 0 and progress.terminal >= progress.total:
                    final_reason = "all_batches_terminal"
                    break
                try:
                    if _dag_state(dag_id, run_id) in TERMINAL_DAG_STATES:
                        final_reason = "dag_terminal"
                        break
                except subprocess.CalledProcessError:
                    pass

                deadline = time.monotonic() + config.check_interval_seconds
                while time.monotonic() < deadline:
                    if stop_file is not None and stop_file.exists():
                        final_reason = "stop_requested"
                        break
                    time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
                if final_reason == "stop_requested":
                    break
    finally:
        finished_slots = current_slots
        restore_error = ""
        if (
            pool_initialized
            and config.restore_pool_on_exit
            and current_slots != config.initial_pool_slots
        ):
            try:
                _set_pool(config, config.initial_pool_slots)
            except subprocess.CalledProcessError as exc:
                restore_error = str(exc)
        summary = {
            "schema_version": 1,
            "dag_id": dag_id,
            "run_id": run_id,
            "finished_at_utc": _iso_now(),
            "final_reason": final_reason,
            "initial_pool_slots": config.initial_pool_slots,
            "final_pool_slots": finished_slots,
            "restored_pool_slots": config.initial_pool_slots
            if pool_initialized and config.restore_pool_on_exit and not restore_error
            else None,
            "restore_error": restore_error,
            "scale_event_count": scale_events,
            "last_progress": dataclasses.asdict(last_progress),
            "config": dataclasses.asdict(config),
            "events_file": str(events_path),
        }
        summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        if stop_file is not None:
            stop_file.unlink(missing_ok=True)
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Adapt an Airflow pool to keep a Feynman DAG run within a target time."
    )
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--dag-id")
    parser.add_argument("--run-id")
    parser.add_argument("--events-jsonl", type=Path)
    parser.add_argument("--summary-json", type=Path)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--validate-config", action="store_true")
    parser.add_argument(
        "--print-field",
        choices=[field.name for field in dataclasses.fields(AutoscalerConfig)],
    )
    args = parser.parse_args()
    if not args.validate_config and not args.print_field:
        missing = [
            name
            for name in ("dag_id", "run_id", "events_jsonl", "summary_json")
            if getattr(args, name) is None
        ]
        if missing:
            parser.error(
                "Controller mode requires: "
                + ", ".join(f"--{name.replace('_', '-')}" for name in missing)
            )
    return args


def main() -> int:
    args = parse_args()
    config = load_autoscaler_config(args.config.resolve())
    if args.validate_config:
        print(json.dumps(dataclasses.asdict(config), indent=2))
        return 0
    if args.print_field:
        value = getattr(config, args.print_field)
        if isinstance(value, bool):
            print("true" if value else "false")
        else:
            print(value)
        return 0
    return run_controller(
        config=config,
        dag_id=args.dag_id,
        run_id=args.run_id,
        events_path=args.events_jsonl.resolve(),
        summary_path=args.summary_json.resolve(),
        stop_file=args.stop_file.resolve() if args.stop_file else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())

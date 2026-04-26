from __future__ import annotations

import csv
import datetime as dt
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Callable

from .utils import ensure_text, now_utc, sanitize


def create_sweep_dir(output_root: Path, experiment_name: str) -> tuple[Path, dt.datetime]:
    created_at = now_utc()
    stamp = created_at.strftime("%Y%m%d_%H%M%S")
    sweep_dir = output_root / f"{stamp}_{sanitize(experiment_name)}"
    sweep_dir.mkdir(parents=True, exist_ok=False)
    return sweep_dir, created_at


def execute_command(
    *,
    cmd: list[str],
    cwd: Path,
    timeout_seconds: float | None,
    dry_run: bool,
) -> tuple[int, float, str, str]:
    if dry_run:
        return 0, 0.0, f"[dry-run] {shlex.join(cmd)}\n", ""

    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
        elapsed = time.perf_counter() - t0
        return proc.returncode, elapsed, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        elapsed = time.perf_counter() - t0
        stdout_text = ensure_text(exc.stdout)
        stderr_text = ensure_text(exc.stderr) + (
            f"\n[runner] timeout after {timeout_seconds} seconds\n"
        )
        return 124, elapsed, stdout_text, stderr_text


def run_sweep(
    *,
    output_root: Path,
    experiment_name: str,
    summary_fields: list[str],
    values: list[Any],
    repeat: int,
    continue_on_error: bool,
    run_one: Callable[[Path, int, int, Any], tuple[dict[str, Any], int]],
    build_metadata: Callable[[Path, dt.datetime], dict[str, Any]],
    metadata_filename: str = "sweep_metadata.json",
) -> int:
    sweep_dir, created_at = create_sweep_dir(output_root, experiment_name)
    summary_path = sweep_dir / "summary.csv"
    metadata_path = sweep_dir / metadata_filename

    metadata = build_metadata(sweep_dir, created_at)
    metadata_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")

    run_index = 0
    failures = 0
    last_rc = 0
    last_row: dict[str, Any] | None = None
    failing_run_index: int | None = None

    with summary_path.open("w", newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=summary_fields)
        writer.writeheader()

        for value in values:
            for rep in range(1, repeat + 1):
                run_index += 1
                row, rc = run_one(sweep_dir, run_index, rep, value)
                writer.writerow(row)
                csvfile.flush()

                last_row = row
                last_rc = rc
                if rc != 0:
                    failures += 1
                    failing_run_index = run_index
                    if not continue_on_error:
                        assert last_row is not None
                        print(
                            f"Run failed (index={failing_run_index}, rc={last_rc}). "
                            f"See {last_row['stdout_file']} and {last_row['stderr_file']}.",
                            file=sys.stderr,
                        )
                        print(f"Sweep directory: {sweep_dir}", file=sys.stderr)
                        return int(last_rc)

    print(f"Sweep directory: {sweep_dir}")
    print(f"Summary CSV: {summary_path}")
    print(f"Sweep metadata: {metadata_path}")
    if failures > 0:
        print(f"Completed with {failures} failed run(s).", file=sys.stderr)
        return 1
    return 0

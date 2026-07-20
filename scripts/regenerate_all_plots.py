#!/usr/bin/env python
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
RUN_PIPELINE = [sys.executable, str((REPO_ROOT / "scripts" / "run_pipeline.py").resolve())]


@dataclass(frozen=True)
class ReplotStats:
    perf_sweep: int = 0
    perf_cases: int = 0
    perf_case_lines: int = 0
    qaoa_pruning: int = 0
    qwalk_quimb: int = 0
    qaoa_qiskit: int = 0
    qft_demo: int = 0


def _with_stats(stats: ReplotStats, **updates: int) -> ReplotStats:
    values = {
        "perf_sweep": stats.perf_sweep,
        "perf_cases": stats.perf_cases,
        "perf_case_lines": stats.perf_case_lines,
        "qaoa_pruning": stats.qaoa_pruning,
        "qwalk_quimb": stats.qwalk_quimb,
        "qaoa_qiskit": stats.qaoa_qiskit,
        "qft_demo": stats.qft_demo,
    }
    values.update(updates)
    return ReplotStats(**values)


def _run(cmd: list[str], *, dry_run: bool) -> tuple[bool, str]:
    if dry_run:
        print("DRY-RUN:", " ".join(cmd))
        return True, ""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        return True, proc.stdout.strip()
    except subprocess.CalledProcessError as exc:
        err = exc.stderr.strip() or exc.stdout.strip() or str(exc)
        return False, err


def _has_multiple_cases(summary_csv: Path) -> bool:
    names: set[str] = set()
    with summary_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            name = (row.get("case_name") or "").strip()
            if name:
                names.add(name)
    return len(names) > 1


def _existing_qft_path(summary_json: Path, paths: dict[str, object], key: str, fallback_name: str) -> Path | None:
    recorded = paths.get(key)
    if isinstance(recorded, str) and recorded:
        recorded_path = Path(recorded)
        if recorded_path.exists():
            return recorded_path
    fallback = summary_json.parent / fallback_name
    return fallback if fallback.exists() else None


def _collect_qft_demo_summaries(validation_root: Path) -> list[Path]:
    summaries: list[Path] = []
    for summary_json in sorted(validation_root.glob("*/summary.json")):
        try:
            payload = json.loads(summary_json.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        paths = payload.get("paths", {})
        if not isinstance(paths, dict):
            continue
        pop_csv = _existing_qft_path(summary_json, paths, "output_population_csv", "output_population.csv")
        input_hsv = _existing_qft_path(summary_json, paths, "input_statevector_used", "input_normalized.hsv")
        if pop_csv is None or input_hsv is None:
            continue
        summaries.append(summary_json)
    return summaries


def _qft_replot_paths(summary_json: Path) -> tuple[Path, Path]:
    payload = json.loads(summary_json.read_text(encoding="utf-8"))
    paths = payload.get("paths", {})
    if not isinstance(paths, dict):
        paths = {}
    pop_csv = _existing_qft_path(summary_json, paths, "output_population_csv", "output_population.csv")
    input_hsv = _existing_qft_path(summary_json, paths, "input_statevector_used", "input_normalized.hsv")
    if pop_csv is None or input_hsv is None:
        raise FileNotFoundError(f"Missing qft-demo replot inputs next to {summary_json}")
    return pop_csv, input_hsv


def _is_qwalk_quimb_summary(summary_csv: Path) -> bool:
    if "qwalk_quimb" in summary_csv.parent.name:
        return True
    try:
        with summary_csv.open("r", newline="", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            fields = set(reader.fieldnames or [])
    except (OSError, csv.Error):
        return False
    return {"quimb_status", "feynman_status", "transpiled_qiskit_ops"}.issubset(fields)


def regenerate_all_plots(*, dry_run: bool, fail_fast: bool) -> int:
    errors: list[str] = []
    stats = ReplotStats()

    experiments_root = REPO_ROOT / "data" / "outputs" / "experiments"
    validation_root = REPO_ROOT / "data" / "outputs" / "validation"

    if experiments_root.exists():
        for summary_csv in sorted(experiments_root.glob("*/summary.csv")):
            run_name = summary_csv.parent.name
            if "qaoa_pruning_sweep" in run_name:
                ok, err = _run(
                    [*RUN_PIPELINE, "plot", "qaoa-pruning", "--summary-csv", str(summary_csv)],
                    dry_run=dry_run,
                )
                if ok:
                    stats = _with_stats(stats, qaoa_pruning=stats.qaoa_pruning + 1)
                else:
                    errors.append(f"qaoa-pruning {summary_csv.parent}: {err}")
                    if fail_fast:
                        break
                continue

            if _is_qwalk_quimb_summary(summary_csv):
                ok, err = _run(
                    [
                        *RUN_PIPELINE,
                        "qwalk-quimb-sweep",
                        "--plot-only",
                        "--summary-csv",
                        str(summary_csv),
                    ],
                    dry_run=dry_run,
                )
                if ok:
                    stats = _with_stats(stats, qwalk_quimb=stats.qwalk_quimb + 1)
                else:
                    errors.append(f"qwalk-quimb {summary_csv.parent}: {err}")
                    if fail_fast:
                        break
                continue

            ok, err = _run(
                [
                    *RUN_PIPELINE,
                    "plot",
                    "perf-sweep",
                    "--summary-csv",
                    str(summary_csv),
                    "--y-column",
                    "total_full_s",
                    "--mode",
                    "meanstd",
                ],
                dry_run=dry_run,
            )
            if ok:
                stats = _with_stats(stats, perf_sweep=stats.perf_sweep + 1)
            else:
                errors.append(f"perf-sweep {summary_csv.parent}: {err}")
                if fail_fast:
                    break

            try:
                if _has_multiple_cases(summary_csv):
                    ok_case, err_case = _run(
                        [
                            *RUN_PIPELINE,
                            "plot",
                            "perf-cases",
                            "--summary-csv",
                            str(summary_csv),
                            "--y-column",
                            "total_full_s",
                        ],
                        dry_run=dry_run,
                    )
                    if ok_case:
                        stats = _with_stats(stats, perf_cases=stats.perf_cases + 1)
                    else:
                        errors.append(f"perf-cases {summary_csv.parent}: {err_case}")
                        if fail_fast:
                            break

                    ok_lines, err_lines = _run(
                        [
                            *RUN_PIPELINE,
                            "plot",
                            "perf-case-lines",
                            "--summary-csv",
                            str(summary_csv),
                        ],
                        dry_run=dry_run,
                    )
                    if ok_lines:
                        stats = _with_stats(stats, perf_case_lines=stats.perf_case_lines + 1)
                    else:
                        errors.append(f"perf-case-lines {summary_csv.parent}: {err_lines}")
                        if fail_fast:
                            break
            except (OSError, csv.Error) as exc:
                errors.append(f"case-detect {summary_csv.parent}: {exc}")
                if fail_fast:
                    break

    if validation_root.exists() and (not fail_fast or not errors):
        for comparison_csv in sorted(validation_root.glob("*/comparison.csv")):
            ok, err = _run(
                [*RUN_PIPELINE, "plot", "qaoa-qiskit", "--comparison-csv", str(comparison_csv)],
                dry_run=dry_run,
            )
            if ok:
                stats = _with_stats(stats, qaoa_qiskit=stats.qaoa_qiskit + 1)
            else:
                errors.append(f"qaoa-qiskit {comparison_csv.parent}: {err}")
                if fail_fast:
                    break

    qft_roots = [root for root in (experiments_root, validation_root) if root.exists()]
    seen_qft_summaries: set[Path] = set()
    if qft_roots and (not fail_fast or not errors):
        for summary_json in [
            summary
            for root in qft_roots
            for summary in _collect_qft_demo_summaries(root)
            if summary not in seen_qft_summaries and not seen_qft_summaries.add(summary)
        ]:
            try:
                population_csv, input_statevector = _qft_replot_paths(summary_json)
            except (OSError, json.JSONDecodeError) as exc:
                errors.append(f"qft-demo {summary_json.parent}: {exc}")
                if fail_fast:
                    break
                continue
            ok, err = _run(
                [
                    *RUN_PIPELINE,
                    "validation",
                    "qft-demo",
                    "--config",
                    "scripts/experiments/paper/validation/qft_demo.json",
                    "--",
                    "--from-csv",
                    "--summary-json",
                    str(summary_json),
                    "--population-csv",
                    str(population_csv),
                    "--input-statevector",
                    str(input_statevector),
                ],
                dry_run=dry_run,
            )
            if ok:
                stats = _with_stats(stats, qft_demo=stats.qft_demo + 1)
            else:
                errors.append(f"qft-demo {summary_json.parent}: {err}")
                if fail_fast:
                    break

    print("Replot summary:")
    print(f"  perf-sweep plots: {stats.perf_sweep}")
    print(f"  perf-case plots:  {stats.perf_cases}")
    print(f"  perf-lines plots: {stats.perf_case_lines}")
    print(f"  qaoa-pruning:     {stats.qaoa_pruning}")
    print(f"  qwalk-quimb:      {stats.qwalk_quimb}")
    print(f"  qaoa-qiskit:      {stats.qaoa_qiskit}")
    print(f"  qft-demo:         {stats.qft_demo}")

    if errors:
        print(f"Errors: {len(errors)}")
        for err in errors:
            print(f"  - {err}")
        return 1
    return 0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Regenerate all plots from existing data/outputs artifacts."
    )
    parser.add_argument("--dry-run", action="store_true", help="Print commands without executing.")
    parser.add_argument("--fail-fast", action="store_true", help="Stop after first failure.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    return regenerate_all_plots(dry_run=args.dry_run, fail_fast=args.fail_fast)


if __name__ == "__main__":
    raise SystemExit(main())

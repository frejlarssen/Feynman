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
    qaoa_qiskit: int = 0
    qft_demo: int = 0


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
        pop_csv = paths.get("output_population_csv")
        if not isinstance(pop_csv, str) or not pop_csv:
            continue
        if not Path(pop_csv).exists():
            continue
        summaries.append(summary_json)
    return summaries


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
                    stats = ReplotStats(
                        perf_sweep=stats.perf_sweep,
                        perf_cases=stats.perf_cases,
                        perf_case_lines=stats.perf_case_lines,
                        qaoa_pruning=stats.qaoa_pruning + 1,
                        qaoa_qiskit=stats.qaoa_qiskit,
                        qft_demo=stats.qft_demo,
                    )
                else:
                    errors.append(f"qaoa-pruning {summary_csv.parent}: {err}")
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
                stats = ReplotStats(
                    perf_sweep=stats.perf_sweep + 1,
                    perf_cases=stats.perf_cases,
                    perf_case_lines=stats.perf_case_lines,
                    qaoa_pruning=stats.qaoa_pruning,
                    qaoa_qiskit=stats.qaoa_qiskit,
                    qft_demo=stats.qft_demo,
                )
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
                        stats = ReplotStats(
                            perf_sweep=stats.perf_sweep,
                            perf_cases=stats.perf_cases + 1,
                            perf_case_lines=stats.perf_case_lines,
                            qaoa_pruning=stats.qaoa_pruning,
                            qaoa_qiskit=stats.qaoa_qiskit,
                            qft_demo=stats.qft_demo,
                        )
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
                        stats = ReplotStats(
                            perf_sweep=stats.perf_sweep,
                            perf_cases=stats.perf_cases,
                            perf_case_lines=stats.perf_case_lines + 1,
                            qaoa_pruning=stats.qaoa_pruning,
                            qaoa_qiskit=stats.qaoa_qiskit,
                            qft_demo=stats.qft_demo,
                        )
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
                stats = ReplotStats(
                    perf_sweep=stats.perf_sweep,
                    perf_cases=stats.perf_cases,
                    perf_case_lines=stats.perf_case_lines,
                    qaoa_pruning=stats.qaoa_pruning,
                    qaoa_qiskit=stats.qaoa_qiskit + 1,
                    qft_demo=stats.qft_demo,
                )
            else:
                errors.append(f"qaoa-qiskit {comparison_csv.parent}: {err}")
                if fail_fast:
                    break

    if validation_root.exists() and (not fail_fast or not errors):
        for summary_json in _collect_qft_demo_summaries(validation_root):
            ok, err = _run(
                [
                    *RUN_PIPELINE,
                    "validation",
                    "qft-demo",
                    "--config",
                    "scripts/experiments/exploratory/validation/qft_demo.json",
                    "--",
                    "--from-csv",
                    "--summary-json",
                    str(summary_json),
                ],
                dry_run=dry_run,
            )
            if ok:
                stats = ReplotStats(
                    perf_sweep=stats.perf_sweep,
                    perf_cases=stats.perf_cases,
                    perf_case_lines=stats.perf_case_lines,
                    qaoa_pruning=stats.qaoa_pruning,
                    qaoa_qiskit=stats.qaoa_qiskit,
                    qft_demo=stats.qft_demo + 1,
                )
            else:
                errors.append(f"qft-demo {summary_json.parent}: {err}")
                if fail_fast:
                    break

    print("Replot summary:")
    print(f"  perf-sweep plots: {stats.perf_sweep}")
    print(f"  perf-case plots:  {stats.perf_cases}")
    print(f"  perf-lines plots: {stats.perf_case_lines}")
    print(f"  qaoa-pruning:     {stats.qaoa_pruning}")
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

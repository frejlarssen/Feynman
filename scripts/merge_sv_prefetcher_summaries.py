#!/usr/bin/env python3
"""Merge multiple sweep summary.csv files into one table."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Merge sv_prefetcher summary CSV files.")
    parser.add_argument(
        "--summary-csv",
        action="append",
        required=True,
        help="Path to summary.csv. Repeat this flag for multiple files.",
    )
    parser.add_argument(
        "--label",
        action="append",
        default=[],
        help="Optional source label. If provided, count must match --summary-csv.",
    )
    parser.add_argument("--output", required=True, help="Output merged CSV path.")
    return parser.parse_args()


def read_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        rows = list(reader)
        fields = reader.fieldnames or []
    return rows, fields


def main() -> int:
    args = parse_args()
    summary_paths = [Path(p).resolve() for p in args.summary_csv]
    for path in summary_paths:
        if not path.exists():
            raise FileNotFoundError(f"Summary CSV not found: {path}")

    labels = args.label
    if labels and len(labels) != len(summary_paths):
        raise ValueError("If --label is used, provide exactly one label per --summary-csv.")
    if not labels:
        labels = [path.parent.name for path in summary_paths]

    all_rows: list[dict[str, str]] = []
    all_fields: list[str] = []
    seen_fields: set[str] = set()
    for idx, path in enumerate(summary_paths):
        rows, fields = read_rows(path)
        for field in fields:
            if field not in seen_fields:
                seen_fields.add(field)
                all_fields.append(field)
        label = labels[idx]
        for row in rows:
            row["source_label"] = label
            if not row.get("case_name"):
                row["case_name"] = label
            all_rows.append(row)

    if "case_name" not in seen_fields:
        all_fields.append("case_name")
    if "source_label" not in seen_fields:
        all_fields.append("source_label")

    output_path = Path(args.output).resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=all_fields)
        writer.writeheader()
        for row in all_rows:
            writer.writerow({field: row.get(field, "") for field in all_fields})

    print(f"Merged {len(summary_paths)} summaries into: {output_path}")
    print(f"Rows written: {len(all_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

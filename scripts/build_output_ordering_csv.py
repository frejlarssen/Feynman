#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from pathlib import Path


PROXY_MODES = ("stable_proxy_v1", "stable_proxy_reverse")


def _load_counts(path: Path) -> dict[str, dict[str, int]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: dict[str, dict[str, int]] = {}
        for row in reader:
            bitstring = (row.get("bitstring_hex") or "").strip().upper()
            if not bitstring:
                continue
            rows[bitstring] = {
                "count": int(row.get("count") or 0),
                "count_nonzero": int(row.get("count_nonzero") or 0),
            }
    if not rows:
        raise ValueError(f"No rows found in {path}")
    return rows


def _load_status(path: Path) -> dict[str, str]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows: dict[str, str] = {}
        for row in reader:
            bitstring = (row.get("bitstring_hex") or "").strip().upper()
            if not bitstring:
                continue
            rows[bitstring] = (row.get("status") or "").strip().lower()
    if not rows:
        raise ValueError(f"No rows found in {path}")
    return rows


def _score_row(
    *,
    proxy_mode: str,
    is_supported: int,
    contribution2_count_nonzero: int,
    contribution1_count: int,
    contribution1_count_nonzero: int,
    contribution0_count: int,
    contribution0_count_nonzero: int,
) -> int:
    if proxy_mode == "stable_proxy_v1":
        return (
            is_supported * 1_000_000_000
            + contribution2_count_nonzero * 1_000_000
            + contribution1_count * 1_000
            + contribution0_count
        )
    if proxy_mode == "stable_proxy_reverse":
        return (
            1_000_000 * (4 * contribution2_count_nonzero + 16 * contribution1_count_nonzero)
            - 1_000 * contribution0_count_nonzero
            - is_supported
        )
    raise ValueError(f"Unsupported proxy mode: {proxy_mode!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a deterministic output-ordering CSV from one run's stable "
            "status/contribution artifacts."
        )
    )
    parser.add_argument(
        "--run-dir",
        type=Path,
        required=True,
        help="Run directory containing timeBitstrings.csv and contribution{2,1,0}AbsMinMax.csv.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        required=True,
        help="Output CSV path with bitstring_hex,score and proxy metadata columns.",
    )
    parser.add_argument(
        "--proxy-mode",
        choices=PROXY_MODES,
        default="stable_proxy_v1",
        help="Named deterministic proxy to use when constructing the score column.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    run_dir = args.run_dir.resolve()
    output_path = args.output.resolve()

    status_path = run_dir / "timeBitstrings.csv"
    contribution2_path = run_dir / "contribution2AbsMinMax.csv"
    contribution1_path = run_dir / "contribution1AbsMinMax.csv"
    contribution0_path = run_dir / "contribution0AbsMinMax.csv"

    status_by_hex = _load_status(status_path)
    contribution2_by_hex = _load_counts(contribution2_path)
    contribution1_by_hex = _load_counts(contribution1_path)
    contribution0_by_hex = _load_counts(contribution0_path)

    keys = sorted(status_by_hex)
    missing = [
        bitstring
        for bitstring in keys
        if bitstring not in contribution2_by_hex
        or bitstring not in contribution1_by_hex
        or bitstring not in contribution0_by_hex
    ]
    if missing:
        preview = ", ".join(missing[:5])
        raise ValueError(f"Missing contribution rows for {len(missing)} bitstrings, for example {preview}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "bitstring_hex",
                "score",
                "proxy_mode",
                "is_supported",
                "status",
                "contribution2_count_nonzero",
                "contribution1_count",
                "contribution1_count_nonzero",
                "contribution0_count",
                "contribution0_count_nonzero",
            ]
        )
        for bitstring in keys:
            status = status_by_hex[bitstring]
            is_supported = 1 if status == "supported" else 0
            contribution2_count_nonzero = contribution2_by_hex[bitstring]["count_nonzero"]
            contribution1_count = contribution1_by_hex[bitstring]["count"]
            contribution1_count_nonzero = contribution1_by_hex[bitstring]["count_nonzero"]
            contribution0_count = contribution0_by_hex[bitstring]["count"]
            contribution0_count_nonzero = contribution0_by_hex[bitstring]["count_nonzero"]
            score = _score_row(
                proxy_mode=args.proxy_mode,
                is_supported=is_supported,
                contribution2_count_nonzero=contribution2_count_nonzero,
                contribution1_count=contribution1_count,
                contribution1_count_nonzero=contribution1_count_nonzero,
                contribution0_count=contribution0_count,
                contribution0_count_nonzero=contribution0_count_nonzero,
            )
            writer.writerow(
                [
                    bitstring,
                    score,
                    args.proxy_mode,
                    is_supported,
                    status,
                    contribution2_count_nonzero,
                    contribution1_count,
                    contribution1_count_nonzero,
                    contribution0_count,
                    contribution0_count_nonzero,
                ]
            )

    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

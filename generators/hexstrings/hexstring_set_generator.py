#!/usr/bin/env python
import argparse
from pathlib import Path

DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2] / "data/generated/hexstring_sets"
)

# One-interval presets
BULK_ONE_INTERVAL = [
    (1, 10),
    (2, 10),
    (3, 10),
    (4, 10),
    (5, 10),
    (16, 10),
    (32, 10),
    (128, 10),
    (1024, 10),
    (2048, 10),
    (4096, 10),
    (8192, 10),
    (16384, 10),
    (32768, 10),
    (65536, 10),
    (131072, 10),
    (262144, 10),
]
# Heavy presets
HEAVY_ONE_INTERVAL = [(1, 256), (2, 65536), (3, 16777216)]
# Two-interval sizes
INTERVAL_SIZES = [1, 2, 3, 4, 5, 6, 7, 8]


def write_one_interval(size: int, nr_hexstrings: int, out_dir: Path) -> Path:
    if size <= 0:
        raise ValueError("size must be > 0")
    if nr_hexstrings <= 0:
        raise ValueError("nr_hexstrings must be > 0")

    # Range
    start = 0
    end = nr_hexstrings  # exclusive
    nr_nibbles = size * 2
    out_dir.mkdir(parents=True, exist_ok=True)

    # Filename
    if size < 10:
        filename = f"nrhex{nr_hexstrings}_size{size}_from0x{start:X}_to0x{end:X}.hs"
    else:
        filename = f"nrhex{nr_hexstrings}_size{size}.hs"
    out_path = out_dir / filename

    with out_path.open("w", encoding="utf-8") as f:
        # Header
        f.write(f"{nr_hexstrings}\n")
        f.write(f"{size}\n")
        # Values
        for value in range(start, end):
            f.write(f"0x{value:0{nr_nibbles}X}\n")

    return out_path


def write_two_intervals(size: int, interval1: list[int], interval2: list[int], out_dir: Path) -> Path:
    if size <= 0:
        raise ValueError("size must be > 0")
    if not interval1 or not interval2:
        raise ValueError("interval1 and interval2 must be non-empty")

    nr_hexstrings = len(interval1) + len(interval2)
    nr_nibbles = size * 2
    out_dir.mkdir(parents=True, exist_ok=True)

    # Filename
    if size < 2:
        filename = (
            f"size{size}_from{interval1[0]}_to{interval1[-1]}_and_from{interval2[0]}_to{interval2[-1]}.hs"
        )
    elif size < 10:
        filename = (
            f"size{size}_from0x{interval1[0]:X}_to0x{interval1[-1]:X}_and_from0x{interval2[0]:X}_to0x{interval2[-1]:X}.hs"
        )
    else:
        filename = f"size{size}.hs"
    out_path = out_dir / filename

    with out_path.open("w", encoding="utf-8") as f:
        # Header
        f.write(f"{nr_hexstrings}\n")
        f.write(f"{size}\n")
        # Interval 1
        for value in interval1:
            f.write(f"0x{value:0{nr_nibbles}X}\n")
        # Interval 2
        for value in interval2:
            f.write(f"0x{value:0{nr_nibbles}X}\n")

    return out_path


def bulk_generate(out_dir: Path) -> list[Path]:
    created: list[Path] = []

    # One interval
    for size, nr_hexstrings in BULK_ONE_INTERVAL:
        created.append(write_one_interval(size=size, nr_hexstrings=nr_hexstrings, out_dir=out_dir))

    # Heavy one interval
    for size, nr_hexstrings in HEAVY_ONE_INTERVAL:
        created.append(write_one_interval(size=size, nr_hexstrings=nr_hexstrings, out_dir=out_dir))

    # Two intervals
    for size in INTERVAL_SIZES:
        middle = int((2 ** (size * 8)) / 4)
        interval1 = list(range(10))
        interval2 = list(range(middle - 5, middle + 5))
        created.append(
            write_two_intervals(size=size, interval1=interval1, interval2=interval2, out_dir=out_dir)
        )

    return created


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate full bulk .hs hexstring preset set."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for path in bulk_generate(out_dir=args.output_dir):
        print(path)


if __name__ == "__main__":
    main()

#!/usr/bin/env python
import argparse
import random
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


def write_random_uniform(
    size: int,
    nr_hexstrings: int,
    seed: int,
    out_dir: Path,
) -> Path:
    if size <= 0:
        raise ValueError("size must be > 0")
    if nr_hexstrings <= 0:
        raise ValueError("nr_hexstrings must be > 0")

    max_states = 1 << (size * 8)
    if nr_hexstrings > max_states:
        raise ValueError(
            f"nr_hexstrings={nr_hexstrings} exceeds the {max_states} distinct values "
            f"available for size={size} byte(s)."
        )

    nr_nibbles = size * 2
    out_dir.mkdir(parents=True, exist_ok=True)
    values = random.Random(seed).sample(range(max_states), nr_hexstrings)

    filename = f"randhex{nr_hexstrings}_size{size}_seed{seed}.hs"
    out_path = out_dir / filename
    with out_path.open("w", encoding="utf-8") as f:
        f.write(f"{nr_hexstrings}\n")
        f.write(f"{size}\n")
        for value in values:
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
        description="Generate .hs output-bitstring sets."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR}).",
    )
    parser.add_argument(
        "--single",
        action="store_true",
        help="Generate one set instead of the preset bulk collection.",
    )
    parser.add_argument(
        "--generator",
        choices=["one_interval", "two_intervals", "random_uniform"],
        default="one_interval",
        help="Generator to use with --single.",
    )
    parser.add_argument("--size", type=int, help="Output bitstring width in bytes.")
    parser.add_argument(
        "--count",
        type=int,
        help="Number of bitstrings to generate for --single.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Seed for --generator random_uniform.",
    )
    parser.add_argument(
        "--interval1",
        type=str,
        help="Comma-separated values for two_intervals interval1.",
    )
    parser.add_argument(
        "--interval2",
        type=str,
        help="Comma-separated values for two_intervals interval2.",
    )
    return parser.parse_args()


def _parse_interval_arg(raw: str | None, label: str) -> list[int]:
    if raw is None:
        raise ValueError(f"{label} is required.")
    values = [int(token.strip(), 0) for token in raw.split(",") if token.strip()]
    if not values:
        raise ValueError(f"{label} must not be empty.")
    if min(values) < 0:
        raise ValueError(f"{label} contains negative values.")
    return values


def main() -> None:
    args = parse_args()
    if args.single:
        if args.size is None:
            raise SystemExit("--single requires --size.")
        if args.generator == "one_interval":
            if args.count is None:
                raise SystemExit("--generator one_interval requires --count.")
            print(
                write_one_interval(
                    size=args.size,
                    nr_hexstrings=args.count,
                    out_dir=args.output_dir,
                )
            )
            return
        if args.generator == "two_intervals":
            print(
                write_two_intervals(
                    size=args.size,
                    interval1=_parse_interval_arg(args.interval1, "--interval1"),
                    interval2=_parse_interval_arg(args.interval2, "--interval2"),
                    out_dir=args.output_dir,
                )
            )
            return
        if args.generator == "random_uniform":
            if args.count is None:
                raise SystemExit("--generator random_uniform requires --count.")
            print(
                write_random_uniform(
                    size=args.size,
                    nr_hexstrings=args.count,
                    seed=args.seed,
                    out_dir=args.output_dir,
                )
            )
            return
        raise SystemExit(f"Unsupported generator: {args.generator}")

    for path in bulk_generate(out_dir=args.output_dir):
        print(path)


if __name__ == "__main__":
    main()

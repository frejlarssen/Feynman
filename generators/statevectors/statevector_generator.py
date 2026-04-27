#!/usr/bin/env python3
import argparse
from pathlib import Path

import numpy as np

DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2] / "data/generated/statevectors"
)

# Ket0 presets
BULK_KET0_SIZES = [
    1,
    3,
    4,
    5,
    8,
    16,
    32,
    64,
    128,
    1024,
    2048,
    4096,
    8192,
    16384,
    32768,
    65536,
    1048576,
]

# Signal presets
BULK_TWO_FREQ = [
    (1, 6, float((2 ** (1 * 8)) / 4), 0.2, 0.5),
    (2, 6, float((2 ** (2 * 8)) / 4), 0.2, 0.9999),
    (2, 6, float((2 ** (2 * 8)) / 4), 0.2, 0.99999),
    (3, 6, float((2 ** (3 * 8)) / 4), 0.2, 0.99999999),
    (3, 6, float((2 ** (3 * 8)) / 4), 0.2, 0.999999999),
    (4, 6, float((2 ** (4 * 8)) / 4), 0.2, 0.99999999999999),
    (4, 6, float((2 ** (4 * 8)) / 4), 0.2, 0.999999999999999),
    (5, 6, float((2 ** (5 * 8)) / 4), 0.2, 1.0),
]


def write_ket0(size: int, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"ket0_size{size}.hsv"
    nr_nibbles = size * 2

    with out_path.open("w", encoding="utf-8") as f:
        # |0...0>
        f.write(f"0x{'0' * nr_nibbles}:1+0i\n")

    return out_path


def _two_freq_name(size: int, f1: int, f2: float, f2_amp: float, threshold: float) -> str:
    return f"amplitude_signal_size{size}QB_f{f1}_f{f2}_relamp{f2_amp}_t{threshold}.hsv"


def _margin_from_threshold(n_states: int, delta_theta: float, threshold: float) -> int:
    # First crossing
    for i in range(n_states):
        if np.cos(i * delta_theta) < threshold:
            return i - 1
    raise ValueError("Threshold too small; no margin found.")


def write_two_freq(
    size: int, f1: int, f2: float, f2_amp: float, threshold: float, out_dir: Path
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    nr_nibbles = size * 2
    n_states = 2 ** (size * 8)
    delta_theta1 = f1 * 2 * np.pi / n_states
    delta_theta2 = f2 * 2 * np.pi / n_states
    margin = _margin_from_threshold(
        n_states=n_states, delta_theta=delta_theta1, threshold=threshold
    )
    out_path = out_dir / _two_freq_name(
        size=size, f1=f1, f2=f2, f2_amp=f2_amp, threshold=threshold
    )

    with out_path.open("w", encoding="utf-8") as file:
        # Adaptive window
        for half_period in range(2 * f1):
            middle = int(half_period * n_states / (2 * f1))
            for i in range(max(middle - margin, 0), min(middle + margin + 1, n_states)):
                real_part = np.cos(i * delta_theta1) + f2_amp * np.cos(i * delta_theta2)
                file.write(f"0x{i:0{nr_nibbles}X}:{real_part}+0i\n")

    return out_path


def bulk_generate(out_dir: Path) -> list[Path]:
    created: list[Path] = []

    # Ket0
    for size in BULK_KET0_SIZES:
        created.append(write_ket0(size=size, out_dir=out_dir))

    # Two-freq
    for size, f1, f2, f2_amp, threshold in BULK_TWO_FREQ:
        created.append(
            write_two_freq(
                size=size,
                f1=f1,
                f2=f2,
                f2_amp=f2_amp,
                threshold=threshold,
                out_dir=out_dir,
            )
        )

    return created


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate bulk statevectors (ket0 + two-frequency signals)."
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

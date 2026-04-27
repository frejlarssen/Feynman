#!/usr/bin/env python3
import argparse
import math
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


def _size_bytes_from_n_qubits(n_qubits: int) -> int:
    if n_qubits <= 0:
        raise ValueError("n_qubits must be > 0")
    return max(1, math.ceil(n_qubits / 8))


def _two_tone_name(n_qubits: int, f1: int, f2: int, rel_amp: float) -> str:
    return f"two_tone_n{n_qubits}_f{f1}_{f2}_rel{rel_amp}.hsv"


def _format_complex_token(z: complex) -> str:
    return f"{z.real:.18f}+{z.imag:.18f}i"


def write_two_tone_dense(
    n_qubits: int, f1: int, f2: int, rel_amp: float, out_dir: Path
) -> Path:
    if n_qubits <= 0:
        raise ValueError("n_qubits must be > 0")
    out_dir.mkdir(parents=True, exist_ok=True)

    dim = 1 << n_qubits
    x = np.arange(dim)
    vec = np.exp(2j * np.pi * f1 * x / dim) + rel_amp * np.exp(2j * np.pi * f2 * x / dim)
    norm = np.linalg.norm(vec)
    if norm <= 0:
        raise ValueError("Two-tone vector has zero norm.")
    vec = vec / norm

    size_bytes = _size_bytes_from_n_qubits(n_qubits)
    nr_nibbles = size_bytes * 2
    out_path = out_dir / _two_tone_name(n_qubits=n_qubits, f1=f1, f2=f2, rel_amp=rel_amp)
    with out_path.open("w", encoding="utf-8") as fh:
        for idx, amp in enumerate(vec):
            fh.write(f"0x{idx:0{nr_nibbles}X}:{_format_complex_token(complex(amp))}\n")
    return out_path


def _two_freq_name(
    size: int,
    f1: int,
    f2: float,
    f2_amp: float,
    threshold: float,
    complex_signal: bool = False,
    full_support: bool = False,
) -> str:
    suffix = ""
    if complex_signal:
        suffix += "_complex"
    if full_support:
        suffix += "_full"
    return f"amplitude_signal_size{size}QB_f{f1}_f{f2}_relamp{f2_amp}_t{threshold}{suffix}.hsv"


def _two_freq_name_n_qubits(
    n_qubits: int,
    f1: int,
    f2: float,
    f2_amp: float,
    threshold: float,
    complex_signal: bool = False,
    full_support: bool = False,
) -> str:
    suffix = ""
    if complex_signal:
        suffix += "_complex"
    if full_support:
        suffix += "_full"
    return f"amplitude_signal_n{n_qubits}Q_f{f1}_f{f2}_relamp{f2_amp}_t{threshold}{suffix}.hsv"


def _margin_from_threshold(n_states: int, delta_theta: float, threshold: float) -> int:
    # First crossing
    for i in range(n_states):
        if np.cos(i * delta_theta) < threshold:
            return i - 1
    raise ValueError("Threshold too small; no margin found.")


def _write_two_freq_with_path(
    *,
    out_path: Path,
    n_qubits: int,
    f1: int,
    f2: float,
    f2_amp: float,
    threshold: float,
    complex_signal: bool = False,
    full_support: bool = False,
) -> Path:
    if n_qubits <= 0:
        raise ValueError("n_qubits must be > 0")
    if f1 <= 0:
        raise ValueError("f1 must be > 0")

    size_bytes = _size_bytes_from_n_qubits(n_qubits)
    nr_nibbles = size_bytes * 2
    n_states = 1 << n_qubits
    delta_theta1 = f1 * 2 * np.pi / n_states
    delta_theta2 = f2 * 2 * np.pi / n_states
    with out_path.open("w", encoding="utf-8") as file:
        if full_support:
            index_iter = range(n_states)
        else:
            margin = _margin_from_threshold(
                n_states=n_states, delta_theta=delta_theta1, threshold=threshold
            )
            indices: set[int] = set()
            # Adaptive window. Indices are byte-padded in the .hsv output.
            for half_period in range(2 * f1):
                middle = int(half_period * n_states / (2 * f1))
                lo = max(middle - margin, 0)
                hi = min(middle + margin + 1, n_states)
                indices.update(range(lo, hi))
            index_iter = sorted(indices)

        for i in index_iter:
            if complex_signal:
                amp = np.exp(1j * i * delta_theta1) + f2_amp * np.exp(1j * i * delta_theta2)
                file.write(f"0x{i:0{nr_nibbles}X}:{_format_complex_token(complex(amp))}\n")
            else:
                real_part = np.cos(i * delta_theta1) + f2_amp * np.cos(i * delta_theta2)
                file.write(f"0x{i:0{nr_nibbles}X}:{real_part}+0i\n")
    return out_path


def write_two_freq_n_qubits(
    n_qubits: int,
    f1: int,
    f2: float,
    f2_amp: float,
    threshold: float,
    out_dir: Path,
    complex_signal: bool = False,
    full_support: bool = False,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / _two_freq_name_n_qubits(
        n_qubits=n_qubits,
        f1=f1,
        f2=f2,
        f2_amp=f2_amp,
        threshold=threshold,
        complex_signal=complex_signal,
        full_support=full_support,
    )
    return _write_two_freq_with_path(
        out_path=out_path,
        n_qubits=n_qubits,
        f1=f1,
        f2=f2,
        f2_amp=f2_amp,
        threshold=threshold,
        complex_signal=complex_signal,
        full_support=full_support,
    )


def write_two_freq(
    size: int,
    f1: int,
    f2: float,
    f2_amp: float,
    threshold: float,
    out_dir: Path,
    complex_signal: bool = False,
    full_support: bool = False,
) -> Path:
    """Backward-compatible byte-based interface.

    `size` is bytes; use `write_two_freq_n_qubits` for arbitrary qubit counts.
    """
    if size <= 0:
        raise ValueError("size must be > 0")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / _two_freq_name(
        size=size,
        f1=f1,
        f2=f2,
        f2_amp=f2_amp,
        threshold=threshold,
        complex_signal=complex_signal,
        full_support=full_support,
    )
    return _write_two_freq_with_path(
        out_path=out_path,
        n_qubits=size * 8,
        f1=f1,
        f2=f2,
        f2_amp=f2_amp,
        threshold=threshold,
        complex_signal=complex_signal,
        full_support=full_support,
    )


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

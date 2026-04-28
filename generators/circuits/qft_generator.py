#!/usr/bin/env python3
import argparse
import math
from pathlib import Path

DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2] / "data/generated/circuits/qft"
)
# Bulk presets
PRESETS = [
    (8, 2),
    (8, 4),
    (16, 1),
    (16, 2),
    (16, 4),
    (16, 16),
    (24, 1),
    (24, 2),
    (24, 24),
    (32, 1),
    (32, 2),
    (32, 10),
    (32, 20),
    (32, 40),
    (40, 2),
    (40, 4),
    (40, 6),
    (40, 8),
    (40, 40),
    (48, 40),
    (56, 40),
    (64, 40),
]


def generate_qft(n: int, k: int, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"qft_n{n}_k{k}.qasm"

    with out_path.open("w", encoding="utf-8") as f:
        # Header
        f.write("OPENQASM 3.0;\n")
        f.write('include "stdgates.inc";\n')
        f.write(f"qreg q[{n}];\n")

        # QFT core
        for group in range(n):
            f.write(f"h q[{n - 1 - group}];\n")
            for c in range(1, min(n - group, k + 1)):
                f.write(
                    f"cp({-math.pi / (2 ** c)}) q[{n - 1 - group - c}],q[{n - 1 - group}];\n"
                )
        # Bit-reversal
        for i in range(n // 2):
            f.write(f"swap q[{i}],q[{n - 1 - i}];\n")

    return out_path


def bulk_generate(out_dir: Path) -> list[Path]:
    return [generate_qft(n=n, k=k, out_dir=out_dir) for n, k in PRESETS]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate full bulk QFT preset set.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for out_path in bulk_generate(out_dir=args.output_dir):
        print(out_path)


if __name__ == "__main__":
    main()

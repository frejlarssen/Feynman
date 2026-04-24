#!/usr/bin/env python3
import argparse
from pathlib import Path

DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2] / "data/generated/circuits/qrng"
)
# Presets
BULK_PRESETS = [1, 2, 4, 8, 16]


def generate_qrng(n: int, out_dir: Path) -> Path:
    if n <= 0:
        raise ValueError("n must be > 0")

    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"qrng_n{n}.qasm"

    with out_path.open("w", encoding="utf-8") as f:
        # Header
        f.write("OPENQASM 3.0;\n")
        f.write('include "stdgates.inc";\n')
        f.write(f"qreg q[{n}];\n")
        # Uniform state
        for i in range(n):
            f.write(f"h q[{i}];\n")

    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate full bulk QRNG preset set.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for n in BULK_PRESETS:
        print(generate_qrng(n=n, out_dir=args.output_dir))


if __name__ == "__main__":
    main()

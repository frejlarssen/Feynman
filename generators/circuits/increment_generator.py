#!/usr/bin/env python
import argparse
from pathlib import Path

DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2] / "data/generated/circuits/increment"
)
# Presets
PRESETS = [8, 32, 64, 128, 256, 1024]


def generate_increment(n: int, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"increment_n{n}.qasm"

    with out_path.open("w", encoding="utf-8") as f:
        # Header
        f.write("OPENQASM 3.0;\n")
        f.write('include "stdgates.inc";\n')
        f.write(f"qreg q[{n}];\n")
        # Ripple
        for i in range(n):
            gate = "c" * (n - 1 - i) + "x "
            for a in range(n - i):
                gate += f"q[{a}]"
                if a != n - i - 1:
                    gate += ","
            f.write(f"{gate};\n")

    return out_path


def bulk_generate(out_dir: Path) -> list[Path]:
    return [generate_increment(n=n, out_dir=out_dir) for n in PRESETS]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate full bulk increment circuit preset set."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for out_path in bulk_generate(out_dir=args.output_dir):
        print(out_path)


if __name__ == "__main__":
    main()

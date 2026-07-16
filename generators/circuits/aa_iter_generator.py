#!/usr/bin/env python
import argparse
from pathlib import Path

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data/generated/circuits/aa"
# Presets
PRESETS = [(2, 1, 1), (2, 2, 1), (3, 2, 1), (3, 3, 1), (4, 3, 5)]


def write_aa_iteration(f, n: int, mark_bits: list[int]) -> None:
    # Oracle
    for i in range(n):
        if mark_bits[i] == 0:
            f.write(f"x q[{i}];\n")

    multi_cz = "c" * (n - 1) + "z "
    for i in range(n):
        multi_cz += f"q[{i}]"
        if i < n - 1:
            multi_cz += ","
    f.write(f"{multi_cz};\n")

    for i in range(n):
        if mark_bits[i] == 0:
            f.write(f"x q[{i}];\n")

    # Diffusion
    for i in range(n):
        f.write(f"h q[{i}];\n")
    for i in range(n):
        f.write(f"x q[{i}];\n")

    f.write(f"{multi_cz};\n")

    for i in range(n):
        f.write(f"x q[{i}];\n")
    for i in range(n):
        f.write(f"h q[{i}];\n")


def generate_aa(n: int, it: int, mark: int, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"aa_n{n}_it{it}_mark{mark}.qasm"
    # Mark bits
    mark_bits = [int(b) for b in bin(mark)[2:].zfill(n)]
    # Little-endian
    mark_bits.reverse()

    with out_path.open("w", encoding="utf-8") as f:
        # Header
        f.write("OPENQASM 3.0;\n")
        f.write('include "stdgates.inc";\n')
        f.write(f"qreg q[{n}];\n")

        # Prep
        for i in range(n):
            f.write(f"h q[{i}];\n")
        for _ in range(it):
            write_aa_iteration(f=f, n=n, mark_bits=mark_bits)

    return out_path


def bulk_generate(out_dir: Path) -> list[Path]:
    return [generate_aa(n=n, it=it, mark=mark, out_dir=out_dir) for n, it, mark in PRESETS]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate full bulk amplitude-amplification preset set."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for out_path in bulk_generate(out_dir=args.output_dir):
        print(out_path)


if __name__ == "__main__":
    main()

#!/usr/bin/env python
import argparse
import math
from pathlib import Path

DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2] / "data/generated/circuits/qwalk"
)
# Presets
PRESETS = [
    (2, 1),
    (2, 2),
    (3, 1),
    (3, 2),
    (4, 1),
    (4, 2),
    (4, 3),
    (4, 4),
    (4, 10),
    (4, 15),
    (4, 20),
    (4, 21),
    (4, 22),
    (4, 23),
    (4, 25),
    (10, 16),
    (16, 1),
    (16, 2),
    (16, 5),
    (16, 6),
    (16, 7),
    (16, 16),
    (30, 16),
    (50, 16),
    (127, 16),
    (128, 1),
    (128, 2),
    (128, 3),
    (128, 4),
    (128, 5),
    (128, 6),
    (128, 7),
    (128, 10),
    (128, 16),
    (129, 16),
    (256, 1),
    (256, 2),
    (256, 3),
    (1024, 1),
]


def write_cinc(f, n: int) -> None:
    # Forward step
    for i in range(n - 1):
        gate = "c" * (n - i - 1) + "x "
        for a in range(n - i):
            gate += f"q[{a}]"
            if a != n - i - 1:
                gate += ","
        f.write(f"{gate};\n")


def write_cdec(f, n: int) -> None:
    # Backward step
    for i in range(1, n):
        gate = "c" * i + "x "
        for a in range(i + 1):
            gate += f"q[{a}]"
            if a != i:
                gate += ","
        f.write(f"{gate};\n")


def generate_qwalk(
    n: int, it: int, out_dir: Path, biased: bool = False, coin_angle: float = math.pi / 3
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    if biased:
        out_path = out_dir / f"qwalk_n{n}_it{it}_biased.qasm"
    else:
        out_path = out_dir / f"qwalk_n{n}_it{it}.qasm"

    with out_path.open("w", encoding="utf-8") as f:
        # Header
        f.write("OPENQASM 3.0;\n")
        f.write('include "stdgates.inc";\n')
        f.write(f"qreg q[{n}];\n")

        # Iterations
        for _ in range(it):
            # Coin
            if biased:
                f.write(f"rx({coin_angle}) q[0];\n")
            else:
                f.write("h q[0];\n")
            # Shift
            write_cinc(f, n)
            f.write("x q[0];\n")
            write_cdec(f, n)
            f.write("x q[0];\n")

    return out_path


def bulk_generate(out_dir: Path) -> list[Path]:
    created = [generate_qwalk(n=n, it=it, out_dir=out_dir) for n, it in PRESETS]
    created.append(generate_qwalk(n=4, it=1, out_dir=out_dir, biased=True, coin_angle=math.pi / 3))
    return created


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate full bulk quantum-walk preset set."
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for out_path in bulk_generate(out_dir=args.output_dir):
        print(out_path)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
import argparse
from pathlib import Path

DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2] / "data/generated/circuits/ghz"
)
# Presets
QUBITS = [512]
QUBYTES = [2048, 4096, 8192, 16384, 32768, 65536, 131072, 262144]


def generate_ghz(n_qubits: int, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    if n_qubits < 1024:
        filename = f"ghz_n{n_qubits}.qasm"
    else:
        filename = f"ghz_size{n_qubits // 8}.qasm"
    out_path = out_dir / filename

    with out_path.open("w", encoding="utf-8") as f:
        # Header
        f.write("OPENQASM 3.0;\n")
        f.write('include "stdgates.inc";\n')
        f.write(f"qreg q[{n_qubits}];\n")
        # Seed
        f.write("h q[0];\n")
        # Chain
        for i in range(n_qubits - 1):
            f.write(f"cx q[{i}],q[{i + 1}];\n")

    return out_path


def bulk_generate(out_dir: Path) -> list[Path]:
    created = [generate_ghz(n_qubits=n, out_dir=out_dir) for n in QUBITS]
    created.extend(generate_ghz(n_qubits=size * 8, out_dir=out_dir) for size in QUBYTES)
    return created


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate full bulk GHZ preset set.")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    for out_path in bulk_generate(out_dir=args.output_dir):
        print(out_path)


if __name__ == "__main__":
    main()

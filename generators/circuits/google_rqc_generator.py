#!/usr/bin/env python
import argparse
import math
import random
from pathlib import Path

DEFAULT_OUTPUT_DIR = (
    Path(__file__).resolve().parents[2] / "data/generated/circuits/google_rqc"
)

# (rows, cols, cycles, seed, variant)
PRESETS = [
    (4, 4, 8, 7, "sycamore"),
    (4, 6, 12, 11, "sycamore"),
    (4, 8, 14, 13, "sycamore"),
]

SYCAMORE_PATTERN = "ABCDCDAB"
HALF_PI = math.pi / 2.0
SYCAMORE_PHI = math.pi / 6.0
QUARTER_PI = math.pi / 4.0


def _format_angle(theta: float) -> str:
    return f"{theta:.16g}"


def _num_qubits(rows: int, cols: int) -> int:
    return rows * cols


def _padded_num_qubits(rows: int, cols: int) -> int:
    num_qubits = _num_qubits(rows, cols)
    return ((num_qubits + 7) // 8) * 8


def _append_gate(lines: list[str], name: str, qubit: int) -> None:
    lines.append(f"{name} q[{qubit}];")


def _append_param_gate(lines: list[str], name: str, theta: float, qubit: int) -> None:
    lines.append(f"{name}({_format_angle(theta)}) q[{qubit}];")


def _apply_sqrt_x(lines: list[str], qubit: int) -> None:
    _append_param_gate(lines, "rx", HALF_PI, qubit)


def _apply_sqrt_y(lines: list[str], qubit: int) -> None:
    _append_param_gate(lines, "ry", HALF_PI, qubit)


def _apply_sqrt_w(lines: list[str], qubit: int) -> None:
    # Up to global phase, this is a pi/2 rotation around the (X + Y) / sqrt(2) axis.
    _append_param_gate(lines, "p", QUARTER_PI, qubit)
    _apply_sqrt_x(lines, qubit)
    _append_param_gate(lines, "p", -QUARTER_PI, qubit)


def _apply_single_qubit_gate(lines: list[str], qubit: int, gate_name: str) -> None:
    if gate_name == "sqrt_x":
        _apply_sqrt_x(lines, qubit)
        return
    if gate_name == "sqrt_y":
        _apply_sqrt_y(lines, qubit)
        return
    if gate_name == "sqrt_w":
        _apply_sqrt_w(lines, qubit)
        return
    if gate_name == "t":
        _append_gate(lines, "t", qubit)
        return
    raise ValueError(f"Unsupported single-qubit gate '{gate_name}'.")


def _select_gate_pool(variant: str) -> tuple[str, ...]:
    if variant == "sycamore":
        return ("sqrt_x", "sqrt_y", "sqrt_w")
    raise ValueError(f"Unsupported Google RQC variant '{variant}'.")


def _pattern_edges(rows: int, cols: int, pattern: str) -> list[tuple[int, int]]:
    edges: list[tuple[int, int]] = []

    if pattern == "A":
        for row in range(rows):
            for col in range(0, cols - 1, 2):
                edges.append((row * cols + col, row * cols + col + 1))
        return edges

    if pattern == "B":
        for row in range(rows):
            for col in range(1, cols - 1, 2):
                edges.append((row * cols + col, row * cols + col + 1))
        return edges

    if pattern == "C":
        for row in range(0, rows - 1, 2):
            for col in range(cols):
                edges.append((row * cols + col, (row + 1) * cols + col))
        return edges

    if pattern == "D":
        for row in range(1, rows - 1, 2):
            for col in range(cols):
                edges.append((row * cols + col, (row + 1) * cols + col))
        return edges

    raise ValueError(f"Unsupported coupler pattern '{pattern}'.")


def _select_single_qubit_gate(
    rng: random.Random,
    gate_pool: tuple[str, ...],
    previous_gate: str | None,
) -> str:
    choices = [gate for gate in gate_pool if gate != previous_gate]
    return rng.choice(choices)


def _build_random_layers(
    rows: int,
    cols: int,
    cycles: int,
    seed: int,
    variant: str,
) -> list[str]:
    num_qubits = _num_qubits(rows, cols)
    rng = random.Random(seed)
    gate_pool = _select_gate_pool(variant)
    previous_single_qubit_gates: list[str | None] = [None] * num_qubits
    lines: list[str] = [
        "OPENQASM 3.0;",
        'include "stdgates.inc";',
        f"qreg q[{num_qubits}];",
    ]

    # Start in a uniformly spread product state before the random layers.
    for qubit in range(num_qubits):
        _append_gate(lines, "h", qubit)

    for cycle in range(cycles):
        for qubit in range(num_qubits):
            gate_name = _select_single_qubit_gate(
                rng=rng,
                gate_pool=gate_pool,
                previous_gate=previous_single_qubit_gates[qubit],
            )
            _apply_single_qubit_gate(lines, qubit, gate_name)
            previous_single_qubit_gates[qubit] = gate_name

        pattern = SYCAMORE_PATTERN[cycle % len(SYCAMORE_PATTERN)]
        for q0, q1 in _pattern_edges(rows=rows, cols=cols, pattern=pattern):
            lines.append(
                f"fsim({_format_angle(HALF_PI)},{_format_angle(SYCAMORE_PHI)}) "
                f"q[{q0}],q[{q1}];"
            )

    return lines


def generate_google_rqc(
    rows: int,
    cols: int,
    cycles: int,
    seed: int,
    out_dir: Path,
    variant: str = "sycamore",
    name: str | None = None,
) -> Path:
    if rows <= 0 or cols <= 0 or cycles <= 0:
        raise ValueError("rows, cols, and cycles must all be > 0.")
    num_qubits = _num_qubits(rows, cols)

    out_dir.mkdir(parents=True, exist_ok=True)

    if name is None:
        filename = (
            f"google_rqc_{variant}_r{rows}_c{cols}_m{cycles}_seed{seed}.qasm"
        )
    else:
        filename = name if name.endswith(".qasm") else f"{name}.qasm"

    out_path = out_dir / filename
    lines = _build_random_layers(
        rows=rows,
        cols=cols,
        cycles=cycles,
        seed=seed,
        variant=variant,
    )
    out_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out_path


def bulk_generate(out_dir: Path) -> list[Path]:
    created: list[Path] = []
    for rows, cols, cycles, seed, variant in PRESETS:
        created.append(
            generate_google_rqc(
                rows=rows,
                cols=cols,
                cycles=cycles,
                seed=seed,
                out_dir=out_dir,
                variant=variant,
            )
        )
    return created


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Generate Google-style random quantum circuits in OpenQASM 3.0 "
            "using native fsim Sycamore-style entangling layers."
        )
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument(
        "--single",
        action="store_true",
        help="Generate one circuit instead of the preset bulk set.",
    )
    parser.add_argument("--rows", type=int, help="Number of qubit rows.")
    parser.add_argument("--cols", type=int, help="Number of qubit columns.")
    parser.add_argument("--cycles", type=int, help="Number of entangling cycles.")
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Seed for the single-qubit gate RNG.",
    )
    parser.add_argument(
        "--variant",
        choices=["sycamore"],
        default="sycamore",
        help="Google Sycamore-style RQC family using fsim(pi/2, pi/6).",
    )
    parser.add_argument(
        "--name", type=str, help="Output filename stem or explicit .qasm filename."
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.single:
        if args.rows is None or args.cols is None or args.cycles is None:
            raise SystemExit("--single requires --rows, --cols, and --cycles.")
        print(
            generate_google_rqc(
                rows=args.rows,
                cols=args.cols,
                cycles=args.cycles,
                seed=args.seed,
                out_dir=args.output_dir,
                variant=args.variant,
                name=args.name,
            )
        )
        return

    for out_path in bulk_generate(out_dir=args.output_dir):
        print(out_path)


if __name__ == "__main__":
    main()

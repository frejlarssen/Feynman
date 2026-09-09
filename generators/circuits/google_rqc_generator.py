#!/usr/bin/env python
"""Generate scalable analogues of the 2019 Google Sycamore RQCs.

The circuit structure follows Arute et al., Nature 574, 505-510 (2019),
Supplementary Information Sections VII.C-E:

* start in the all-zero computational-basis state (state preparation is left to
  the simulator input);
* apply ``m`` full cycles, each comprising a random single-qubit layer followed
  by a two-qubit layer in the repeating pattern ABCDCDAB;
* apply one final random single-qubit half-cycle before measurement; and
* choose each single-qubit gate from sqrt(X), sqrt(Y), and sqrt(W), excluding
  the gate used on that qubit in the preceding layer.

Documented approximations:

* The rectangular grid and four brickwork matchings are a scalable square-grid
  representation of the staggered A-D matchings in Fig. S25. They do not encode
  the exact 53-qubit device outline, broken qubit, or paper-specific qubit order.
* Every pair uses the idealized fSim(pi/2, pi/6). The experiment instead used
  pair-specific, inferred five-parameter two-qubit unitaries near these angles,
  including implicit single-qubit Z rotations.
* Sections VII.C-E specify the PRNG nesting property but not a reproducible PRNG
  algorithm. This generator therefore uses a documented counter-based SHA-256
  choice keyed by (seed, qubit, layer), rather than claiming Google's instances.
* Measurement operations are omitted because this repository computes selected
  output amplitudes in the computational basis.
"""

import argparse
import hashlib
import math
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


def _append_param_gate(lines: list[str], name: str, theta: float, qubit: int) -> None:
    lines.append(f"{name}({_format_angle(theta)}) q[{qubit}];")


def _apply_sqrt_x(lines: list[str], qubit: int) -> None:
    _append_param_gate(lines, "rx", HALF_PI, qubit)


def _apply_sqrt_y(lines: list[str], qubit: int) -> None:
    _append_param_gate(lines, "ry", HALF_PI, qubit)


def _apply_sqrt_w(lines: list[str], qubit: int) -> None:
    # P(pi/4) RX(pi/2) P(-pi/4), in operator order, equals RX+Y(pi/2).
    # QASM instructions act left-to-right, so emit the rightmost factor first.
    _append_param_gate(lines, "p", -QUARTER_PI, qubit)
    _apply_sqrt_x(lines, qubit)
    _append_param_gate(lines, "p", QUARTER_PI, qubit)


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


def _counter_random_index(
    seed: int,
    qubit: int,
    layer: int,
    upper_bound: int,
) -> int:
    """Return an unbiased deterministic choice independent of circuit shape."""
    if upper_bound <= 0:
        raise ValueError("upper_bound must be > 0.")

    modulus = 1 << 256
    acceptance_limit = modulus - (modulus % upper_bound)
    nonce = 0
    while True:
        counter = f"feynman-google-rqc-v1:{seed}:{qubit}:{layer}:{nonce}".encode()
        value = int.from_bytes(hashlib.sha256(counter).digest(), "big")
        if value < acceptance_limit:
            return value % upper_bound
        nonce += 1


def _select_single_qubit_gate(
    seed: int,
    qubit: int,
    layer: int,
    gate_pool: tuple[str, ...],
    previous_gate: str | None,
) -> str:
    choices = [gate for gate in gate_pool if gate != previous_gate]
    return choices[
        _counter_random_index(
            seed=seed,
            qubit=qubit,
            layer=layer,
            upper_bound=len(choices),
        )
    ]


def _select_single_qubit_layers(
    num_qubits: int,
    cycles: int,
    seed: int,
    variant: str,
) -> list[list[str]]:
    """Select the m full-cycle layers plus the final half-cycle layer."""
    gate_pool = _select_gate_pool(variant)
    previous_gates: list[str | None] = [None] * num_qubits
    layers: list[list[str]] = []

    for layer in range(cycles + 1):
        current_layer: list[str] = []
        for qubit in range(num_qubits):
            gate_name = _select_single_qubit_gate(
                seed=seed,
                qubit=qubit,
                layer=layer,
                gate_pool=gate_pool,
                previous_gate=previous_gates[qubit],
            )
            current_layer.append(gate_name)
            previous_gates[qubit] = gate_name
        layers.append(current_layer)

    return layers


def _build_random_layers(
    rows: int,
    cols: int,
    cycles: int,
    seed: int,
    variant: str,
) -> list[str]:
    num_qubits = _num_qubits(rows, cols)
    single_qubit_layers = _select_single_qubit_layers(
        num_qubits=num_qubits,
        cycles=cycles,
        seed=seed,
        variant=variant,
    )
    lines: list[str] = [
        "OPENQASM 3.0;",
        'include "stdgates.inc";',
        f"qreg q[{num_qubits}];",
    ]

    for layer, gate_names in enumerate(single_qubit_layers):
        for qubit, gate_name in enumerate(gate_names):
            _apply_single_qubit_gate(lines, qubit, gate_name)

        # The final single-qubit layer is the half-cycle before measurement.
        if layer == cycles:
            continue

        pattern = SYCAMORE_PATTERN[layer % len(SYCAMORE_PATTERN)]
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

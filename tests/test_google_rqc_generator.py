import cmath
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from generators.circuits import google_rqc_generator as rqc
from scripts.sweeplib.materialize import resolve_circuit_input


def _single_gate_lines(name: str, qubit: int) -> list[str]:
    lines: list[str] = []
    rqc._apply_single_qubit_gate(lines, qubit, name)
    return lines


def _fsim_lines(rows: int, cols: int, pattern: str) -> list[str]:
    theta = rqc._format_angle(rqc.HALF_PI)
    phi = rqc._format_angle(rqc.SYCAMORE_PHI)
    return [
        f"fsim({theta},{phi}) q[{q0}],q[{q1}];"
        for q0, q1 in rqc._pattern_edges(rows, cols, pattern)
    ]


class GoogleRqcGeneratorTests(unittest.TestCase):
    def test_m1_is_full_cycle_then_final_half_cycle(self):
        """Supplement VII.C: S1, F_A, S2, then measurement."""
        rows, cols = 2, 3
        layers = [
            ["sqrt_x"] * (rows * cols),
            ["sqrt_y"] * (rows * cols),
        ]
        with mock.patch.object(rqc, "_select_single_qubit_layers", return_value=layers):
            lines = rqc._build_random_layers(rows, cols, cycles=1, seed=7, variant="sycamore")

        expected_body = [
            *[line for q in range(rows * cols) for line in _single_gate_lines("sqrt_x", q)],
            *_fsim_lines(rows, cols, "A"),
            *[line for q in range(rows * cols) for line in _single_gate_lines("sqrt_y", q)],
        ]
        self.assertEqual(lines[3:], expected_body)
        self.assertFalse(any(line.startswith("h ") for line in lines))

    def test_m2_is_two_full_cycles_then_final_half_cycle(self):
        """Supplement VII.C: S1, F_A, S2, F_B, S3, then measurement."""
        rows, cols = 2, 3
        layers = [
            ["sqrt_x"] * (rows * cols),
            ["sqrt_y"] * (rows * cols),
            ["sqrt_x"] * (rows * cols),
        ]
        with mock.patch.object(rqc, "_select_single_qubit_layers", return_value=layers):
            lines = rqc._build_random_layers(rows, cols, cycles=2, seed=7, variant="sycamore")

        expected_body = [
            *[line for q in range(rows * cols) for line in _single_gate_lines("sqrt_x", q)],
            *_fsim_lines(rows, cols, "A"),
            *[line for q in range(rows * cols) for line in _single_gate_lines("sqrt_y", q)],
            *_fsim_lines(rows, cols, "B"),
            *[line for q in range(rows * cols) for line in _single_gate_lines("sqrt_x", q)],
        ]
        self.assertEqual(lines[3:], expected_body)

    def test_random_layers_follow_gate_and_nonrepetition_rules(self):
        layers = rqc._select_single_qubit_layers(
            num_qubits=12,
            cycles=8,
            seed=29,
            variant="sycamore",
        )
        self.assertEqual(len(layers), 9)
        self.assertTrue(all(len(layer) == 12 for layer in layers))
        self.assertTrue(
            all(gate in {"sqrt_x", "sqrt_y", "sqrt_w"} for layer in layers for gate in layer)
        )
        for previous, current in zip(layers, layers[1:]):
            self.assertTrue(all(a != b for a, b in zip(previous, current)))

    def test_random_choices_are_nested_across_size_and_depth(self):
        """Supplement VII.D requires shared qubit/cycle choices to be stable."""
        small = rqc._select_single_qubit_layers(6, cycles=2, seed=31, variant="sycamore")
        large = rqc._select_single_qubit_layers(10, cycles=4, seed=31, variant="sycamore")
        for layer in range(3):
            self.assertEqual(small[layer], large[layer][:6])

    def test_patterns_are_disjoint_matchings_covering_the_grid(self):
        rows, cols = 4, 5
        patterns = {
            pattern: rqc._pattern_edges(rows, cols, pattern)
            for pattern in "ABCD"
        }
        for edges in patterns.values():
            endpoints = [q for edge in edges for q in edge]
            self.assertEqual(len(endpoints), len(set(endpoints)))

        horizontal = {
            (row * cols + col, row * cols + col + 1)
            for row in range(rows)
            for col in range(cols - 1)
        }
        vertical = {
            (row * cols + col, (row + 1) * cols + col)
            for row in range(rows - 1)
            for col in range(cols)
        }
        self.assertEqual(set().union(*map(set, patterns.values())), horizontal | vertical)

    def test_native_u2_sqrt_w_matches_supplement_equation_52(self):
        lines: list[str] = []
        rqc._apply_sqrt_w(lines, qubit=0)
        self.assertEqual(
            lines,
            [
                f"u2({rqc._format_angle(-rqc.QUARTER_PI)},"
                f"{rqc._format_angle(rqc.QUARTER_PI)}) q[0];",
            ],
        )

        inv_sqrt2 = 1 / math.sqrt(2)
        phi = -math.pi / 4
        lambda_ = math.pi / 4
        actual = [
            [inv_sqrt2, -cmath.exp(1j * lambda_) * inv_sqrt2],
            [cmath.exp(1j * phi) * inv_sqrt2, cmath.exp(1j * (phi + lambda_)) * inv_sqrt2],
        ]
        expected = [
            [1 * inv_sqrt2, -cmath.sqrt(1j) * inv_sqrt2],
            [cmath.sqrt(-1j) * inv_sqrt2, 1 * inv_sqrt2],
        ]
        for actual_row, expected_row in zip(actual, expected):
            for actual_value, expected_value in zip(actual_row, expected_row):
                self.assertAlmostEqual(actual_value.real, expected_value.real)
                self.assertAlmostEqual(actual_value.imag, expected_value.imag)

    def test_native_sqrt_w_keeps_one_instruction_per_logical_single_qubit_gate(self):
        lines = rqc._build_random_layers(
            rows=2,
            cols=6,
            cycles=1,
            seed=1,
            variant="sycamore",
        )
        # Two 12-qubit single-qubit layers plus the six pattern-A fSim gates.
        self.assertEqual(len(lines[3:]), 30)
        self.assertFalse(any(line.startswith("p(") for line in lines))

    def test_materializer_defaults_to_the_supported_sycamore_variant(self):
        with tempfile.TemporaryDirectory() as directory:
            path, metadata = resolve_circuit_input(
                {
                    "generator": "google_rqc",
                    "rows": 2,
                    "cols": 3,
                    "cycles": 1,
                    "seed": 7,
                    "output_dir": directory,
                },
                Path.cwd(),
            )
            generated = path.read_text()
        self.assertEqual(metadata["variant"], "sycamore")
        self.assertNotIn("\nh q[", generated)


if __name__ == "__main__":
    unittest.main()

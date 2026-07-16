"""Qiskit transpilation helpers for quimb tensor-circuit experiments."""

from __future__ import annotations

from qiskit import transpile


# Gates supported by quimb's Circuit interface, expressed using Qiskit names.
# Keep CCX/CCZ/CSWAP as native 3-qubit gates instead of decomposing arithmetic
# all the way down to one- and two-qubit gates.
QUIMB_QISKIT_BASIS = [
    "id",
    "x",
    "y",
    "z",
    "h",
    "s",
    "sdg",
    "sx",
    "sxdg",
    "t",
    "tdg",
    "rx",
    "ry",
    "rz",
    "p",
    "u1",
    "u2",
    "u3",
    "cx",
    "cy",
    "cz",
    "swap",
    "ccx",
    "ccz",
    "cswap",
    "crx",
    "cry",
    "crz",
    "cp",
    "rxx",
    "ryy",
    "rzz",
]


def transpile_for_quimb(qc, *, optimization_level: int = 1):
    """Lower a Qiskit circuit to a quimb-compatible gate basis."""
    return transpile(
        qc,
        basis_gates=QUIMB_QISKIT_BASIS,
        optimization_level=optimization_level,
    )

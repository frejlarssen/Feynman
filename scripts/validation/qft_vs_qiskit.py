#!/usr/bin/env python3
"""Validate sv_prefetcher amplitudes against a Qiskit statevector reference.

This script is intentionally separate from the performance-sweep workflow.
It targets correctness validation for small instances (paper-quality figures),
while the sweep stack remains focused on timing/ablation experiments.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import HGate, PhaseGate, SwapGate, XGate, ZGate
from qiskit.quantum_info import Statevector


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")


def _sanitize(name: str) -> str:
    out = []
    for ch in name.strip():
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "validation"


def _parse_complex_token(token: str) -> complex:
    s = token.strip()
    plus = s.find("+", 1)
    i_pos = s.find("i", 1)
    if plus == -1 or i_pos == -1:
        raise ValueError(f"Invalid complex token: {token!r}")
    re_val = float(s[:plus])
    im_val = float(s[plus + 1 : i_pos])
    return complex(re_val, im_val)


def _format_complex_token(z: complex) -> str:
    return f"{z.real:.18f}+{z.imag:.18f}i"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    return payload


def _merge_config(args: argparse.Namespace) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    cfg: dict[str, Any] = {}
    config_path_str: str | None = None
    if args.config:
        config_path = Path(args.config).resolve()
        cfg = _load_json(config_path)
        config_path_str = str(config_path)

    def pick(key: str, cli_value: Any, default: Any = None) -> Any:
        return cli_value if cli_value is not None else cfg.get(key, default)

    merged = {
        "experiment_name": pick("experiment_name", args.experiment_name, "qft_vs_qiskit"),
        "binary": pick("binary", args.binary, "build/sv_prefetcher_subset_mpi.x"),
        "mpirun": pick("mpirun", args.mpirun, "mpirun"),
        "ranks": int(pick("ranks", args.ranks, 1)),
        "circuit": pick("circuit", args.circuit),
        "output_bitstrings": pick("output_bitstrings", args.output_bitstrings),
        "input_statevector": pick("input_statevector", args.input_statevector),
        "fraction": float(pick("fraction", args.fraction, 1.0)),
        "threshold": float(pick("threshold", args.threshold, 0.0)),
        "batch_size": int(pick("batch_size", args.batch_size, 32)),
        "verbosity": int(pick("verbosity", args.verbosity, 1)),
        "dense": bool(pick("dense", args.dense, False)),
        "p": pick("p", args.p, None),
        "r": pick("r", args.r, None),
        "output_root": pick("output_root", args.output_root, "data/outputs/validation"),
        "repo_root": pick("repo_root", args.repo_root, "."),
        "two_tone": cfg.get("two_tone", None),
    }

    if merged["circuit"] is None:
        raise ValueError("Missing required parameter: circuit")
    if merged["output_bitstrings"] is None:
        raise ValueError("Missing required parameter: output_bitstrings")
    if merged["input_statevector"] is None and merged["two_tone"] is None:
        raise ValueError(
            "Provide either input_statevector or two_tone in config/CLI."
        )
    if merged["ranks"] < 1:
        raise ValueError("ranks must be >= 1")
    if merged["batch_size"] < 0:
        raise ValueError("batch_size must be >= 0")
    return merged, cfg, config_path_str


@dataclass(frozen=True)
class QasmInstruction:
    base_gate: str
    num_controls: int
    params: list[float]
    args: list[int]


@dataclass(frozen=True)
class ParsedQasm:
    declared_qubits: int
    simulator_qubits: int
    instructions: list[QasmInstruction]


def _parse_openqasm_subset(path: Path) -> ParsedQasm:
    lines = path.read_text(encoding="utf-8").splitlines()
    declared_n: int | None = None
    instructions: list[QasmInstruction] = []

    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("OPENQASM ") or line.startswith("include "):
            continue
        if line.startswith("qreg ") or line.startswith("qubit "):
            left = line.find("[")
            right = line.find("]")
            if left == -1 or right == -1 or right <= left:
                raise ValueError(f"Invalid qubit declaration: {line}")
            declared_n = int(line[left + 1 : right])
            continue

        if not line.endswith(";"):
            raise ValueError(f"Expected ';' terminated instruction: {line}")
        line = line[:-1]
        split_at = line.find(" ")
        if split_at == -1:
            raise ValueError(f"Invalid gate line: {line}")
        gate_head = line[:split_at].strip()
        qubits_part = line[split_at + 1 :].strip()

        left_par = gate_head.find("(")
        right_par = gate_head.rfind(")")
        if left_par != -1:
            if right_par == -1 or right_par < left_par:
                raise ValueError(f"Invalid param list: {gate_head}")
            gate_name = gate_head[:left_par]
            params_part = gate_head[left_par + 1 : right_par]
            params = [float(tok.strip()) for tok in params_part.split(",") if tok.strip()]
        else:
            gate_name = gate_head
            params = []

        num_controls = 0
        for ch in gate_name:
            if ch == "c":
                num_controls += 1
            else:
                break
        base_gate = gate_name[num_controls:]
        if not base_gate:
            raise ValueError(f"Invalid controlled gate name: {gate_name}")

        args: list[int] = []
        for tok in qubits_part.split(","):
            tok = tok.strip()
            lb = tok.find("[")
            rb = tok.find("]")
            if lb == -1 or rb == -1 or rb <= lb:
                raise ValueError(f"Invalid qubit token: {tok}")
            args.append(int(tok[lb + 1 : rb]))

        instructions.append(
            QasmInstruction(
                base_gate=base_gate,
                num_controls=num_controls,
                params=params,
                args=args,
            )
        )

    if declared_n is None:
        raise ValueError(f"No qubit register declaration found in {path}")
    n_sim = ((declared_n + 7) // 8) * 8
    return ParsedQasm(
        declared_qubits=declared_n,
        simulator_qubits=n_sim,
        instructions=instructions,
    )


def _gate_num_targets(base_gate: str) -> int:
    if base_gate in ("h", "x", "z", "p"):
        return 1
    if base_gate == "swap":
        return 2
    raise ValueError(f"Unsupported gate base '{base_gate}' in QASM subset parser.")


def _make_base_gate(base_gate: str, params: list[float]):
    if base_gate == "h":
        if params:
            raise ValueError("h gate must not have parameters")
        return HGate()
    if base_gate == "x":
        if params:
            raise ValueError("x gate must not have parameters")
        return XGate()
    if base_gate == "z":
        if params:
            raise ValueError("z gate must not have parameters")
        return ZGate()
    if base_gate == "p":
        if len(params) != 1:
            raise ValueError("p gate requires exactly one parameter")
        return PhaseGate(params[0])
    if base_gate == "swap":
        if params:
            raise ValueError("swap gate must not have parameters")
        return SwapGate()
    raise ValueError(f"Unsupported base gate '{base_gate}'")


def _build_qiskit_circuit(parsed: ParsedQasm) -> QuantumCircuit:
    qc = QuantumCircuit(parsed.simulator_qubits)
    for ins in parsed.instructions:
        expected_targets = _gate_num_targets(ins.base_gate)
        if len(ins.args) != ins.num_controls + expected_targets:
            raise ValueError(
                f"Gate arity mismatch for '{ins.base_gate}': args={ins.args}, "
                f"controls={ins.num_controls}"
            )
        controls = ins.args[: ins.num_controls]
        targets = ins.args[ins.num_controls :]
        base = _make_base_gate(ins.base_gate, ins.params)
        if ins.num_controls == 0:
            qc.append(base, targets)
        else:
            qc.append(base.control(ins.num_controls), controls + targets)
    return qc


def _read_output_bitstrings(path: Path) -> tuple[list[int], int]:
    lines = [ln.strip() for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    if len(lines) < 2:
        raise ValueError(f"Invalid output bitstring file: {path}")
    expected_count = int(lines[0])
    size_bytes = int(lines[1])
    values = [int(ln, 16) for ln in lines[2:]]
    if expected_count != len(values):
        raise ValueError(
            f"Header count mismatch in {path}: header={expected_count}, actual={len(values)}"
        )
    return values, size_bytes


def _read_hsv_sparse(path: Path) -> dict[int, complex]:
    out: dict[int, complex] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        idx_s, amp_s = line.split(":", 1)
        out[int(idx_s, 16)] = _parse_complex_token(amp_s)
    return out


def _build_dense_input_vector(path: Path, n_qubits: int) -> np.ndarray:
    dim = 1 << n_qubits
    vec = np.zeros(dim, dtype=np.complex128)
    sparse = _read_hsv_sparse(path)
    for idx, amp in sparse.items():
        if idx < 0 or idx >= dim:
            raise ValueError(
                f"Input index 0x{idx:X} is outside dimension 2^{n_qubits} ({dim})."
            )
        vec[idx] = amp
    return vec


def _build_two_tone_input(n_qubits: int, f1: int, f2: int, rel_amp: float) -> np.ndarray:
    dim = 1 << n_qubits
    x = np.arange(dim)
    vec = np.exp(2j * np.pi * f1 * x / dim) + rel_amp * np.exp(2j * np.pi * f2 * x / dim)
    vec = vec / np.linalg.norm(vec)
    return vec.astype(np.complex128)


def _write_hsv_dense(path: Path, vec: np.ndarray, size_bytes: int) -> None:
    width = size_bytes * 2
    with path.open("w", encoding="utf-8") as fh:
        for idx, amp in enumerate(vec):
            fh.write(f"0x{idx:0{width}X}:{_format_complex_token(complex(amp))}\n")


def _run_sv_prefetcher(
    *,
    repo_root: Path,
    mpirun: str,
    ranks: int,
    binary: Path,
    circuit: Path,
    input_statevector: Path,
    output_bitstrings: Path,
    output_hsv: Path,
    batch_size: int,
    fraction: float,
    threshold: float,
    verbosity: int,
    dense: bool,
    p: int | None,
    r: int | None,
) -> tuple[list[str], int, str, str]:
    cmd = [
        mpirun,
        "-n",
        str(ranks),
        str(binary),
        "-c",
        str(circuit),
        "-i",
        str(input_statevector),
        "-b",
        str(output_bitstrings),
        "-o",
        str(output_hsv),
        "-s",
        str(batch_size),
        "-f",
        str(fraction),
        "-t",
        str(threshold),
        "-v",
        str(verbosity),
    ]
    if p is not None and r is not None:
        cmd.extend(["-p", str(p), "-r", str(r)])
    if dense:
        cmd.append("-D")

    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )
    return cmd, proc.returncode, proc.stdout, proc.stderr


def _safe_fidelity(a: np.ndarray, b: np.ndarray) -> float:
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    ov = np.vdot(a, b) / (na * nb)
    return float(abs(ov) ** 2)


def _render_plot(
    *,
    out_png: Path,
    input_vec: np.ndarray,
    bins: list[int],
    feynman_amp: np.ndarray,
    qiskit_amp: np.ndarray,
    title: str,
) -> None:
    # Configure a writable cache path in restricted environments.
    out_png.parent.mkdir(parents=True, exist_ok=True)
    import os

    os.environ.setdefault("MPLCONFIGDIR", str(out_png.parent / ".mplconfig"))
    os.environ.setdefault("XDG_CACHE_HOME", str(out_png.parent / ".cache"))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    x_in = np.arange(len(input_vec))
    in_real = np.real(input_vec)

    x_out = np.arange(len(bins))
    f_pop = np.abs(feynman_amp) ** 2
    q_pop = np.abs(qiskit_amp) ** 2

    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))

    axes[0].plot(x_in, in_real, linewidth=1.2)
    axes[0].set_title("Input Signal (Real Part)")
    axes[0].set_xlabel("Basis Index")
    axes[0].set_ylabel("Amplitude")
    axes[0].grid(True, axis="y", alpha=0.25)

    axes[1].plot(x_out, q_pop, label="Qiskit reference", linewidth=1.8)
    axes[1].plot(x_out, f_pop, label="Feynman", linewidth=1.0, alpha=0.9)
    axes[1].set_title("Output Population")
    axes[1].set_xlabel("Requested Output Index")
    axes[1].set_ylabel(r"$|amp|^2$")
    axes[1].grid(True, axis="y", alpha=0.25)
    axes[1].legend()

    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(out_png, dpi=180)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Validate sv_prefetcher amplitudes against a Qiskit statevector "
            "reference on small circuits."
        )
    )
    parser.add_argument("--config", default=None, help="JSON config path.")
    parser.add_argument("--experiment-name", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--binary", default=None)
    parser.add_argument("--mpirun", default=None)
    parser.add_argument("--ranks", type=int, default=None)
    parser.add_argument("--circuit", default=None)
    parser.add_argument("--input-statevector", default=None)
    parser.add_argument("--output-bitstrings", default=None)
    parser.add_argument("--fraction", type=float, default=None)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--verbosity", type=int, default=None)
    parser.add_argument("--dense", action="store_true", default=None)
    parser.add_argument("--p", type=int, default=None)
    parser.add_argument("--r", type=int, default=None)
    parser.add_argument("--output-root", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg, raw_cfg, config_path_str = _merge_config(args)

    repo_root = Path(cfg["repo_root"]).resolve()
    binary = (repo_root / cfg["binary"]).resolve()
    circuit = (repo_root / cfg["circuit"]).resolve()
    output_bitstrings = (repo_root / cfg["output_bitstrings"]).resolve()
    output_root = (repo_root / cfg["output_root"]).resolve()

    if not binary.exists():
        raise FileNotFoundError(f"Binary not found: {binary}")
    if not circuit.exists():
        raise FileNotFoundError(f"Circuit not found: {circuit}")
    if not output_bitstrings.exists():
        raise FileNotFoundError(f"Output bitstrings not found: {output_bitstrings}")

    sweep_dir = output_root / f"{_utc_stamp()}_{_sanitize(cfg['experiment_name'])}"
    sweep_dir.mkdir(parents=True, exist_ok=False)

    parsed_qasm = _parse_openqasm_subset(circuit)
    qiskit_circuit = _build_qiskit_circuit(parsed_qasm)

    subset_indices, subset_size_bytes = _read_output_bitstrings(output_bitstrings)
    dim = 1 << parsed_qasm.simulator_qubits
    for idx in subset_indices:
        if idx < 0 or idx >= dim:
            raise ValueError(
                f"Output subset index 0x{idx:X} outside 2^{parsed_qasm.simulator_qubits}."
            )

    if cfg["input_statevector"] is not None:
        input_path = (repo_root / cfg["input_statevector"]).resolve()
        if not input_path.exists():
            raise FileNotFoundError(f"Input statevector not found: {input_path}")
        input_vec = _build_dense_input_vector(input_path, parsed_qasm.simulator_qubits)
    else:
        two_tone = cfg["two_tone"]
        if not isinstance(two_tone, dict):
            raise ValueError("two_tone must be an object when input_statevector is not set.")
        f1 = int(two_tone.get("f1"))
        f2 = int(two_tone.get("f2"))
        rel_amp = float(two_tone.get("rel_amp", 1.0))
        input_vec = _build_two_tone_input(parsed_qasm.simulator_qubits, f1, f2, rel_amp)
        input_path = sweep_dir / "input_two_tone.hsv"
        # The simulator reads hex indices as full-width values.
        _write_hsv_dense(input_path, input_vec, subset_size_bytes)

    output_hsv = sweep_dir / "feynman_output.hsv"
    cmd, rc, stdout_text, stderr_text = _run_sv_prefetcher(
        repo_root=repo_root,
        mpirun=cfg["mpirun"],
        ranks=cfg["ranks"],
        binary=binary,
        circuit=circuit,
        input_statevector=input_path,
        output_bitstrings=output_bitstrings,
        output_hsv=output_hsv,
        batch_size=cfg["batch_size"],
        fraction=cfg["fraction"],
        threshold=cfg["threshold"],
        verbosity=cfg["verbosity"],
        dense=cfg["dense"],
        p=cfg["p"],
        r=cfg["r"],
    )
    (sweep_dir / "stdout.log").write_text(stdout_text, encoding="utf-8")
    (sweep_dir / "stderr.log").write_text(stderr_text, encoding="utf-8")
    (sweep_dir / "command.txt").write_text(shlex.join(cmd) + "\n", encoding="utf-8")
    if rc != 0:
        raise RuntimeError(
            f"sv_prefetcher failed with return code {rc}. See {sweep_dir / 'stderr.log'}"
        )

    feynman_sparse = _read_hsv_sparse(output_hsv)
    feynman_subset = np.array(
        [feynman_sparse.get(idx, 0.0 + 0.0j) for idx in subset_indices], dtype=np.complex128
    )

    sv_in = Statevector(input_vec)
    sv_out = sv_in.evolve(qiskit_circuit)
    qiskit_subset = np.array([sv_out.data[idx] for idx in subset_indices], dtype=np.complex128)

    abs_err = np.abs(feynman_subset - qiskit_subset)
    f_pop = np.abs(feynman_subset) ** 2
    q_pop = np.abs(qiskit_subset) ** 2
    prob_err = np.abs(f_pop - q_pop)

    compare_csv = sweep_dir / "comparison.csv"
    with compare_csv.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(
            [
                "ordinal",
                "bin_dec",
                "bin_hex",
                "feynman_real",
                "feynman_imag",
                "qiskit_real",
                "qiskit_imag",
                "abs_amp_err",
                "feynman_pop",
                "qiskit_pop",
                "abs_pop_err",
            ]
        )
        hex_width = subset_size_bytes * 2
        for i, idx in enumerate(subset_indices):
            fa = feynman_subset[i]
            qa = qiskit_subset[i]
            writer.writerow(
                [
                    i,
                    idx,
                    f"0x{idx:0{hex_width}X}",
                    f"{fa.real:.18e}",
                    f"{fa.imag:.18e}",
                    f"{qa.real:.18e}",
                    f"{qa.imag:.18e}",
                    f"{abs_err[i]:.18e}",
                    f"{f_pop[i]:.18e}",
                    f"{q_pop[i]:.18e}",
                    f"{prob_err[i]:.18e}",
                ]
            )

    # Also emit Qiskit subset as .hsv for direct inspection.
    qiskit_hsv = sweep_dir / "qiskit_reference_subset.hsv"
    with qiskit_hsv.open("w", encoding="utf-8") as fh:
        hex_width = subset_size_bytes * 2
        for idx, amp in zip(subset_indices, qiskit_subset):
            fh.write(f"0x{idx:0{hex_width}X}:{_format_complex_token(complex(amp))}\n")

    max_abs_err = float(np.max(abs_err)) if abs_err.size else 0.0
    rmse_abs_err = float(math.sqrt(np.mean(abs_err**2))) if abs_err.size else 0.0
    max_prob_err = float(np.max(prob_err)) if prob_err.size else 0.0
    l2_abs_err = float(np.linalg.norm(feynman_subset - qiskit_subset))
    fidelity_subset = _safe_fidelity(feynman_subset, qiskit_subset)
    fidelity_full = _safe_fidelity(np.array(sv_out.data), np.array(sv_out.data))

    top_k = min(10, len(subset_indices))
    top_order = np.argsort(q_pop)[::-1][:top_k]
    top_bins = [
        {
            "rank": int(rank + 1),
            "bin_dec": int(subset_indices[i]),
            "feynman_pop": float(f_pop[i]),
            "qiskit_pop": float(q_pop[i]),
            "abs_pop_err": float(prob_err[i]),
        }
        for rank, i in enumerate(top_order)
    ]

    summary = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "experiment_name": cfg["experiment_name"],
        "config_file": config_path_str,
        "config_from_file": raw_cfg,
        "config_effective": cfg,
        "command": shlex.join(cmd),
        "paths": {
            "repo_root": str(repo_root),
            "binary": str(binary),
            "circuit": str(circuit),
            "output_bitstrings": str(output_bitstrings),
            "input_statevector_used": str(input_path),
            "run_dir": str(sweep_dir),
            "feynman_output": str(output_hsv),
            "qiskit_reference_subset": str(qiskit_hsv),
            "comparison_csv": str(compare_csv),
            "plot_png": str(sweep_dir / "agreement_plot.png"),
            "stdout_log": str(sweep_dir / "stdout.log"),
            "stderr_log": str(sweep_dir / "stderr.log"),
        },
        "circuit_info": {
            "declared_qubits": parsed_qasm.declared_qubits,
            "simulator_qubits": parsed_qasm.simulator_qubits,
            "num_instructions": len(parsed_qasm.instructions),
        },
        "subset_info": {
            "num_requested_outputs": len(subset_indices),
            "size_bytes": subset_size_bytes,
        },
        "metrics": {
            "max_abs_amp_err": max_abs_err,
            "rmse_abs_amp_err": rmse_abs_err,
            "l2_abs_amp_err": l2_abs_err,
            "max_abs_pop_err": max_prob_err,
            "fidelity_subset": fidelity_subset,
            "norm_feynman_subset": float(np.sum(f_pop)),
            "norm_qiskit_subset": float(np.sum(q_pop)),
            # This is always 1 by construction and is included as a sanity field.
            "fidelity_full_selfcheck": fidelity_full,
        },
        "top_bins_by_qiskit_population": top_bins,
    }

    _render_plot(
        out_png=sweep_dir / "agreement_plot.png",
        input_vec=input_vec,
        bins=subset_indices,
        feynman_amp=feynman_subset,
        qiskit_amp=qiskit_subset,
        title="Feynman vs Qiskit Amplitudes",
    )

    summary_path = sweep_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"Validation run directory: {sweep_dir}")
    print(f"Summary: {summary_path}")
    print(f"Max abs amplitude error: {max_abs_err:.3e}")
    print(f"Max abs population error: {max_prob_err:.3e}")
    print(f"Subset fidelity: {fidelity_subset:.12f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

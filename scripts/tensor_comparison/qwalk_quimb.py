#!/usr/bin/env python
"""Compare quantum-walk selected amplitudes with quimb tensor contraction."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parents[1]
for path in (SCRIPT_REPO_ROOT, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from scripts.sweeplib.materialize import (  # noqa: E402
    resolve_circuit_input,
    resolve_output_bitstrings_input,
    resolve_statevector_input,
)
from scripts.tensor_comparison.quimb_transpile import transpile_for_quimb  # noqa: E402
from scripts.validation.qaoa_qiskit_validation import (  # noqa: E402
    build_qiskit_circuit,
    parse_hs,
    parse_hsv_sparse,
    parse_qasm,
)


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")


def _sanitize(name: str) -> str:
    out = []
    for ch in name.strip():
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "qwalk_quimb"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    return payload


def _resolve_path(path_like: str | Path, repo_root: Path) -> Path:
    p = Path(path_like)
    return p.resolve() if p.is_absolute() else (repo_root / p).resolve()


def _merge_config(args: argparse.Namespace) -> dict[str, Any]:
    raw = _load_json(args.config.resolve())

    def pick(key: str, default: Any = None) -> Any:
        return getattr(args, key, None) if getattr(args, key, None) is not None else raw.get(key, default)

    cfg = {
        "experiment_name": pick("experiment_name", "qwalk_quimb"),
        "repo_root": pick("repo_root", "."),
        "output_root": pick("output_root", "data/outputs/validation"),
        "circuit": raw.get("circuit"),
        "input_statevector": raw.get("input_statevector"),
        "output_bitstrings": raw.get("output_bitstrings"),
        "qiskit_optimization_level": int(raw.get("qiskit_optimization_level", 1)),
        "quimb_optimize": str(raw.get("quimb_optimize", "greedy")),
        "quimb_rehearse": bool(raw.get("quimb_rehearse", False)),
        "run_feynman": bool(raw.get("run_feynman", True)),
        "binary": raw.get("binary", "build-release/sv_prefetcher_subset_mpi.x"),
        "mpirun": raw.get("mpirun", "mpirun"),
        "ranks": int(raw.get("ranks", 1)),
        "batch_size": int(raw.get("batch_size", 32)),
        "fraction": float(raw.get("fraction", 1.0)),
        "threshold": float(raw.get("threshold", 0.0)),
        "verbosity": int(raw.get("verbosity", 1)),
        "notes": raw.get("notes", ""),
    }
    for key in ("circuit", "input_statevector", "output_bitstrings"):
        if cfg[key] is None:
            raise ValueError(f"Missing required config key: {key}")
    return cfg


def _complex_to_token(value: complex) -> str:
    return f"{value.real:.18e}+{value.imag:.18e}i"


def _write_hsv(path: Path, values: list[int], amps: list[complex]) -> None:
    width = max(2, max((v.bit_length() + 3) // 4 for v in values) if values else 2)
    with path.open("w", encoding="utf-8") as fh:
        for idx, amp in zip(values, amps):
            fh.write(f"0x{idx:0{width}x}:{_complex_to_token(amp)}\n")


def _parse_feynman_internal_runtime(stdout: str) -> float | None:
    m = re.search(r"Total clocktime \(including I/O\) for sv\.cpp:\s+([0-9eE+.\-]+) seconds", stdout)
    return float(m.group(1)) if m else None


def _run_feynman(
    *,
    cfg: dict[str, Any],
    repo_root: Path,
    circuit: Path,
    input_statevector: Path,
    output_bitstrings: Path,
    output_file: Path,
) -> tuple[float, float | None, str, str]:
    binary = _resolve_path(cfg["binary"], repo_root)
    if not binary.exists():
        raise FileNotFoundError(f"Feynman binary not found: {binary}")

    cmd = [
        str(cfg["mpirun"]),
        "-n",
        str(int(cfg["ranks"])),
        str(binary),
        "-c",
        str(circuit),
        "-i",
        str(input_statevector),
        "-b",
        str(output_bitstrings),
        "-o",
        str(output_file),
        "-s",
        str(int(cfg["batch_size"])),
        "-f",
        str(float(cfg["fraction"])),
        "-t",
        str(float(cfg["threshold"])),
        "-v",
        str(int(cfg["verbosity"])),
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, check=True)
    walltime_s = time.perf_counter() - t0
    return walltime_s, _parse_feynman_internal_runtime(proc.stdout), proc.stdout, proc.stderr


def _single_input_basis_state(input_statevector: Path) -> tuple[int, complex]:
    sparse = parse_hsv_sparse(input_statevector)
    nonzero = [(idx, amp) for idx, amp in sparse.items() if abs(amp) > 0.0]
    if len(nonzero) != 1:
        raise ValueError(
            "The quimb amplitude comparison supports a single-basis input state. "
            f"Found {len(nonzero)} nonzero input amplitudes in {input_statevector}."
        )
    return nonzero[0]


def _index_to_quimb_bitstring(index: int, n_qubits: int) -> str:
    # Repository .hs/.hsv indices treat q[0] as the least significant bit.
    # quimb bitstrings are ordered by site index, so reverse the binary label.
    return format(index, f"0{n_qubits}b")[::-1]


_QISKIT_TO_QUIMB_GATE = {
    "id": "IDEN",
    "x": "X",
    "y": "Y",
    "z": "Z",
    "h": "H",
    "s": "S",
    "sdg": "SDG",
    "sx": "SX",
    "sxdg": "SXDG",
    "t": "T",
    "tdg": "TDG",
    "rx": "RX",
    "ry": "RY",
    "rz": "RZ",
    "p": "PHASE",
    "u1": "U1",
    "u2": "U2",
    "u3": "U3",
    "cx": "CX",
    "cy": "CY",
    "cz": "CZ",
    "swap": "SWAP",
    "ccx": "CCX",
    "ccz": "CCZ",
    "cswap": "CSWAP",
    "crx": "CRX",
    "cry": "CRY",
    "crz": "CRZ",
    "cp": "CPHASE",
    "rxx": "RXX",
    "ryy": "RYY",
    "rzz": "RZZ",
}


def _qiskit_to_quimb_circuit(qc):
    import quimb.tensor as qtn

    circ = qtn.Circuit(qc.num_qubits)
    for inst in qc.data:
        op = inst.operation
        name = op.name.lower()
        if name in {"barrier", "measure", "delay"}:
            continue
        gate = _QISKIT_TO_QUIMB_GATE.get(name)
        if gate is None:
            raise ValueError(f"Unsupported transpiled Qiskit gate for quimb: {op.name}")
        qubits = [qc.find_bit(q).index for q in inst.qubits]
        params = [float(p) for p in op.params]
        circ.apply_gate(gate, *params, *qubits)
    return circ


def _compute_quimb_amplitudes(
    *,
    circuit: Path,
    output_indices: list[int],
    input_index: int,
    input_amplitude: complex,
    optimization_level: int,
    optimize: str,
    rehearse: bool,
) -> tuple[list[complex], dict[str, Any], float, float, float]:
    declared_n, instructions = parse_qasm(circuit)
    sim_n = ((declared_n + 7) // 8) * 8
    if input_index != 0:
        raise ValueError("quimb Circuit.amplitude evaluates amplitudes from |0...0> input.")

    t0 = time.perf_counter()
    qc = build_qiskit_circuit(sim_n, instructions)
    tqc = transpile_for_quimb(qc, optimization_level=optimization_level)
    transpile_s = time.perf_counter() - t0

    t1 = time.perf_counter()
    quimb_circ = _qiskit_to_quimb_circuit(tqc)
    build_s = time.perf_counter() - t1

    amps: list[complex] = []
    t2 = time.perf_counter()
    for idx in output_indices:
        bitstring = _index_to_quimb_bitstring(idx, sim_n)
        if rehearse:
            quimb_circ.amplitude(bitstring, rehearse=True, optimize=optimize)
        amp = quimb_circ.amplitude(bitstring, optimize=optimize)
        amps.append(complex(amp) * input_amplitude)
    amplitude_s = time.perf_counter() - t2

    meta = {
        "declared_qubits": declared_n,
        "simulator_qubits": sim_n,
        "original_qiskit_ops": qc.size(),
        "transpiled_qiskit_ops": tqc.size(),
        "transpiled_gate_counts": dict(tqc.count_ops()),
    }
    return amps, meta, transpile_s, build_s, amplitude_s


def _write_comparison_csv(
    path: Path,
    output_indices: list[int],
    quimb_amps: list[complex],
    feynman_sparse: dict[int, complex] | None,
) -> dict[str, float | None]:
    abs_amp_errors: list[float] = []
    abs_pop_errors: list[float] = []
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "bitstring_hex",
                "quimb_real",
                "quimb_imag",
                "quimb_population",
                "feynman_real",
                "feynman_imag",
                "feynman_population",
                "abs_amp_error",
                "abs_population_error",
            ]
        )
        for idx, q_amp in zip(output_indices, quimb_amps):
            q_pop = float(abs(q_amp) ** 2)
            if feynman_sparse is None:
                f_amp = None
                f_pop = None
                abs_amp_error = None
                abs_pop_error = None
            else:
                f_amp = feynman_sparse.get(idx, 0.0 + 0.0j)
                f_pop = float(abs(f_amp) ** 2)
                abs_amp_error = float(abs(q_amp - f_amp))
                abs_pop_error = abs(q_pop - f_pop)
                abs_amp_errors.append(abs_amp_error)
                abs_pop_errors.append(abs_pop_error)
            w.writerow(
                [
                    f"0x{idx:x}",
                    f"{q_amp.real:.18e}",
                    f"{q_amp.imag:.18e}",
                    f"{q_pop:.18e}",
                    "" if f_amp is None else f"{f_amp.real:.18e}",
                    "" if f_amp is None else f"{f_amp.imag:.18e}",
                    "" if f_pop is None else f"{f_pop:.18e}",
                    "" if abs_amp_error is None else f"{abs_amp_error:.18e}",
                    "" if abs_pop_error is None else f"{abs_pop_error:.18e}",
                ]
            )
    return {
        "max_abs_amp_error": max(abs_amp_errors) if abs_amp_errors else None,
        "mean_abs_amp_error": sum(abs_amp_errors) / len(abs_amp_errors) if abs_amp_errors else None,
        "max_abs_population_error": max(abs_pop_errors) if abs_pop_errors else None,
        "mean_abs_population_error": sum(abs_pop_errors) / len(abs_pop_errors) if abs_pop_errors else None,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--experiment-name", default=None)
    parser.add_argument("--repo-root", default=None)
    parser.add_argument("--output-root", default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = _merge_config(args)
    repo_root = _resolve_path(cfg["repo_root"], Path.cwd()).resolve()
    output_root = _resolve_path(cfg["output_root"], repo_root).resolve()
    run_dir = output_root / f"{_utc_stamp()}_{_sanitize(str(cfg['experiment_name']))}"
    run_dir.mkdir(parents=True, exist_ok=False)

    circuit, circuit_generated = resolve_circuit_input(cfg["circuit"], repo_root)
    input_statevector, input_generated = resolve_statevector_input(cfg["input_statevector"], repo_root)
    output_bitstrings, output_generated = resolve_output_bitstrings_input(cfg["output_bitstrings"], repo_root)
    output_indices, output_size_bytes = parse_hs(output_bitstrings)
    input_index, input_amplitude = _single_input_basis_state(input_statevector)

    quimb_amps, quimb_meta, transpile_s, build_s, amplitude_s = _compute_quimb_amplitudes(
        circuit=circuit,
        output_indices=output_indices,
        input_index=input_index,
        input_amplitude=input_amplitude,
        optimization_level=int(cfg["qiskit_optimization_level"]),
        optimize=str(cfg["quimb_optimize"]),
        rehearse=bool(cfg["quimb_rehearse"]),
    )
    quimb_output = run_dir / "quimb_output.hsv"
    _write_hsv(quimb_output, output_indices, quimb_amps)

    feynman_sparse: dict[int, complex] | None = None
    feynman_metrics: dict[str, Any] = {
        "enabled": bool(cfg["run_feynman"]),
        "walltime_s": None,
        "internal_total_s": None,
    }
    if cfg["run_feynman"]:
        feynman_output = run_dir / "feynman_output.hsv"
        wall_s, internal_s, stdout, stderr = _run_feynman(
            cfg=cfg,
            repo_root=repo_root,
            circuit=circuit,
            input_statevector=input_statevector,
            output_bitstrings=output_bitstrings,
            output_file=feynman_output,
        )
        (run_dir / "feynman_stdout.log").write_text(stdout, encoding="utf-8")
        (run_dir / "feynman_stderr.log").write_text(stderr, encoding="utf-8")
        feynman_sparse = parse_hsv_sparse(feynman_output)
        feynman_metrics.update(
            {
                "walltime_s": wall_s,
                "internal_total_s": internal_s,
                "output": str(feynman_output),
            }
        )

    comparison_csv = run_dir / "comparison.csv"
    agreement_metrics = _write_comparison_csv(
        comparison_csv,
        output_indices=output_indices,
        quimb_amps=quimb_amps,
        feynman_sparse=feynman_sparse,
    )

    summary = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "experiment_name": cfg["experiment_name"],
        "notes": cfg["notes"],
        "config": cfg,
        "config_file": str(args.config.resolve()),
        "paths": {
            "run_dir": str(run_dir),
            "circuit": str(circuit),
            "input_statevector": str(input_statevector),
            "output_bitstrings": str(output_bitstrings),
            "quimb_output": str(quimb_output),
            "comparison_csv": str(comparison_csv),
        },
        "generated": {
            "circuit": circuit_generated,
            "input_statevector": input_generated,
            "output_bitstrings": output_generated,
        },
        "problem": {
            "output_count": len(output_indices),
            "output_size_bytes": output_size_bytes,
            "input_index": input_index,
            "input_amplitude": _complex_to_token(input_amplitude),
            **quimb_meta,
        },
        "metrics": {
            "quimb_transpile_s": transpile_s,
            "quimb_build_s": build_s,
            "quimb_amplitude_s": amplitude_s,
            "quimb_total_s": transpile_s + build_s + amplitude_s,
            "feynman": feynman_metrics,
            **agreement_metrics,
        },
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Run directory: {run_dir}")
    print(f"Quimb total (s): {summary['metrics']['quimb_total_s']:.6f}")
    print(f"Quimb amplitudes only (s): {amplitude_s:.6f}")
    if cfg["run_feynman"]:
        print(f"Feynman walltime (s): {feynman_metrics['walltime_s']:.6f}")
        if feynman_metrics["internal_total_s"] is not None:
            print(f"Feynman internal total (s): {feynman_metrics['internal_total_s']:.6f}")
        print(f"Max amplitude error: {agreement_metrics['max_abs_amp_error']:.6e}")
    print(f"Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

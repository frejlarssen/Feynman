#!/usr/bin/env python
"""QAOA validation against Qiskit with config-driven outputs in data/outputs/validation."""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from qiskit import QuantumCircuit
from qiskit.circuit.library import HGate, PhaseGate, RXGate, RYGate, SwapGate, XGate, ZGate
from qiskit.quantum_info import Statevector
from sweeplib.materialize import (
    resolve_circuit_input,
    resolve_output_bitstrings_input,
    resolve_statevector_input,
)
from sweeplib.plot_style import apply_plot_fontsizes, configure_headless_matplotlib


SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class QasmInstruction:
    base_gate: str
    num_controls: int
    params: list[float]
    args: list[int]


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")


def _sanitize(name: str) -> str:
    out = []
    for ch in name.strip():
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "run"


def _resolve_path(path_like: str | Path, repo_root: Path) -> Path:
    p = Path(path_like)
    return p if p.is_absolute() else (repo_root / p)


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    return payload


def _merge_config(args: argparse.Namespace) -> dict[str, Any]:
    cfg: dict[str, Any] = {}
    if args.config:
        cfg = _load_json(Path(args.config).resolve())

    def pick(key: str, cli_value: Any, default: Any = None) -> Any:
        return cli_value if cli_value is not None else cfg.get(key, default)

    merged = {
        "experiment_name": pick("experiment_name", args.experiment_name, "qaoa_qiskit_validation"),
        "repo_root": pick("repo_root", args.repo_root, str(SCRIPT_REPO_ROOT)),
        "output_root": pick("output_root", args.output_root, "data/outputs/validation"),
        "binary": pick("binary", args.binary, "build-release/sv_prefetcher_subset_mpi.x"),
        "mpirun": pick("mpirun", args.mpirun, "mpirun"),
        "ranks": int(pick("ranks", args.ranks, 1)),
        "circuit": pick("circuit", args.circuit),
        "input_statevector": pick("input_statevector", args.input_statevector),
        "output_bitstrings": pick("output_bitstrings", args.output_bitstrings),
        "fraction": float(pick("fraction", args.fraction, 1.0)),
        "threshold": float(pick("threshold", args.threshold, 0.0)),
        "batch_size": int(pick("batch_size", args.batch_size, 32)),
        "verbosity": int(pick("verbosity", args.verbosity, 1)),
        "plot_label_fontsize": pick("plot_label_fontsize", args.plot_label_fontsize, None),
    }
    if merged["plot_label_fontsize"] is not None:
        merged["plot_label_fontsize"] = float(merged["plot_label_fontsize"])

    for key in ("circuit", "input_statevector", "output_bitstrings"):
        if not merged[key]:
            raise ValueError(f"Missing required parameter: {key}")
    if merged["ranks"] < 1:
        raise ValueError("ranks must be >= 1")
    if merged["batch_size"] < 0:
        raise ValueError("batch_size must be >= 0")

    return merged


def parse_hs(path: Path) -> tuple[list[int], int]:
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


_AMP_RE = re.compile(
    r"^([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)\+([+-]?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)i$"
)


def _parse_complex_token(token: str) -> complex:
    m = _AMP_RE.match(token.strip())
    if not m:
        raise ValueError(f"Invalid complex token: {token!r}")
    return complex(float(m.group(1)), float(m.group(2)))


def parse_hsv_sparse(path: Path) -> dict[int, complex]:
    out: dict[int, complex] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        idx_hex, amp_token = line.split(":", 1)
        out[int(idx_hex, 16)] = _parse_complex_token(amp_token)
    return out


def parse_qasm(path: Path) -> tuple[int, list[QasmInstruction]]:
    declared_n: int | None = None
    instructions: list[QasmInstruction] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("OPENQASM ") or line.startswith("include "):
            continue
        if line.startswith("qreg ") or line.startswith("qubit "):
            lb = line.find("[")
            rb = line.find("]")
            if lb == -1 or rb == -1 or rb <= lb:
                raise ValueError(f"Invalid qubit declaration: {line}")
            declared_n = int(line[lb + 1 : rb])
            continue
        if not line.endswith(";"):
            raise ValueError(f"Expected ';' terminated instruction: {line}")

        stmt = line[:-1]
        split_at = stmt.find(" ")
        if split_at == -1:
            raise ValueError(f"Invalid gate statement: {line}")
        gate_head = stmt[:split_at].strip()
        args_part = stmt[split_at + 1 :].strip()

        left_par = gate_head.find("(")
        if left_par != -1:
            right_par = gate_head.rfind(")")
            if right_par == -1 or right_par < left_par:
                raise ValueError(f"Invalid parameterized gate: {line}")
            gate_name = gate_head[:left_par]
            params_raw = gate_head[left_par + 1 : right_par]
            params = [float(tok.strip()) for tok in params_raw.split(",") if tok.strip()]
        else:
            gate_name = gate_head
            params = []

        num_controls = 0
        for ch in gate_name:
            if ch == "c":
                num_controls += 1
            else:
                break
        base_gate = gate_name[num_controls:].lower()
        if not base_gate:
            raise ValueError(f"Invalid controlled gate name: {gate_name}")

        args: list[int] = []
        for tok in args_part.split(","):
            tok = tok.strip()
            lb = tok.find("[")
            rb = tok.find("]")
            if lb == -1 or rb == -1 or rb <= lb:
                raise ValueError(f"Invalid qubit token: {tok}")
            args.append(int(tok[lb + 1 : rb]))

        instructions.append(
            QasmInstruction(
                base_gate=base_gate, num_controls=num_controls, params=params, args=args
            )
        )

    if declared_n is None:
        raise ValueError(f"No qreg/qubit declaration found in {path}")
    return declared_n, instructions


def _num_targets(base_gate: str) -> int:
    if base_gate in {"h", "x", "z", "p", "rx", "ry"}:
        return 1
    if base_gate == "swap":
        return 2
    raise ValueError(f"Unsupported gate base '{base_gate}' for Qiskit reconstruction")


def _base_gate_op(base_gate: str, params: list[float]):
    if base_gate == "h":
        return HGate()
    if base_gate == "x":
        return XGate()
    if base_gate == "z":
        return ZGate()
    if base_gate == "p":
        if len(params) != 1:
            raise ValueError("p gate expects exactly one parameter")
        return PhaseGate(params[0])
    if base_gate == "rx":
        if len(params) != 1:
            raise ValueError("rx gate expects exactly one parameter")
        return RXGate(params[0])
    if base_gate == "ry":
        if len(params) != 1:
            raise ValueError("ry gate expects exactly one parameter")
        return RYGate(params[0])
    if base_gate == "swap":
        return SwapGate()
    raise ValueError(f"Unsupported gate base '{base_gate}'")


def build_qiskit_circuit(sim_qubits: int, instructions: list[QasmInstruction]) -> QuantumCircuit:
    qc = QuantumCircuit(sim_qubits)
    for ins in instructions:
        expected_targets = _num_targets(ins.base_gate)
        if len(ins.args) != ins.num_controls + expected_targets:
            raise ValueError(
                f"Gate arity mismatch for {ins.base_gate}: args={ins.args}, controls={ins.num_controls}"
            )
        controls = ins.args[: ins.num_controls]
        targets = ins.args[ins.num_controls :]
        op = _base_gate_op(ins.base_gate, ins.params)
        if ins.num_controls > 0:
            op = op.control(ins.num_controls)
            qc.append(op, controls + targets)
        else:
            qc.append(op, targets)
    return qc


def build_dense_input(input_hsv: Path, sim_qubits: int) -> np.ndarray:
    dim = 1 << sim_qubits
    vec = np.zeros(dim, dtype=np.complex128)
    sparse = parse_hsv_sparse(input_hsv)
    for idx, amp in sparse.items():
        if idx >= dim:
            raise ValueError(f"Input index {idx} outside dimension {dim}")
        vec[idx] = amp
    return vec


def _parse_feynman_internal_runtime(stdout: str) -> float | None:
    m = re.search(r"Total clocktime \(including I/O\) for sv\.cpp:\s+([0-9eE+.\-]+) seconds", stdout)
    if not m:
        return None
    return float(m.group(1))


def run_feynman(
    *,
    binary: Path,
    mpirun: str,
    ranks: int,
    circuit: Path,
    input_statevector: Path,
    output_bitstrings: Path,
    output_file: Path,
    fraction: float,
    threshold: float,
    batch_size: int,
    verbosity: int,
) -> tuple[float, str, str]:
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
        str(output_file),
        "-f",
        str(fraction),
        "-t",
        str(threshold),
        "-s",
        str(batch_size),
        "-v",
        str(verbosity),
    ]
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    dt_s = time.perf_counter() - t0
    return dt_s, proc.stdout, proc.stderr


def _write_hsv(path: Path, values: list[int], amps: list[complex]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for idx, amp in zip(values, amps):
            fh.write(f"0x{idx:02x}:{amp.real:.6f}+{amp.imag:.6f}i\n")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare Feynman simulator vs Qiskit (config-driven) and report runtimes."
    )
    parser.add_argument("--config", type=Path, default=None)
    parser.add_argument("--experiment-name", type=str, default=None)
    parser.add_argument("--repo-root", type=Path, default=None)
    parser.add_argument("--output-root", type=Path, default=None)
    parser.add_argument("--circuit", type=Path, default=None)
    parser.add_argument("--input-statevector", type=Path, default=None)
    parser.add_argument("--output-bitstrings", type=Path, default=None)
    parser.add_argument("--binary", type=Path, default=None)
    parser.add_argument("--mpirun", type=str, default=None)
    parser.add_argument("--ranks", type=int, default=None)
    parser.add_argument("--fraction", type=float, default=None)
    parser.add_argument("--threshold", type=float, default=None)
    parser.add_argument("--batch-size", type=int, default=None)
    parser.add_argument("--verbosity", type=int, default=None)
    parser.add_argument("--plot-label-fontsize", type=float, default=None)
    return parser.parse_args(argv)


def plot_from_comparison_csv(
    comparison_csv: Path, output_path: Path | None = None, label_fontsize: float | None = None
) -> Path:
    xs: list[int] = []
    feynman_real: list[float] = []
    feynman_pop: list[float] = []
    qiskit_pop: list[float] = []
    with comparison_csv.open("r", newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        for i, row in enumerate(reader):
            xs.append(i)
            feynman_real.append(float(row["feynman_real"]))
            feynman_pop.append(float(row["feynman_population"]))
            qiskit_pop.append(float(row["qiskit_population"]))
    if not xs:
        raise ValueError(f"No rows found in comparison CSV: {comparison_csv}")

    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_plot_fontsizes(plt=plt, label_fontsize=label_fontsize)
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.5))
    axes[0].plot(xs, feynman_real, marker="o", linewidth=1.3, markersize=3)
    axes[0].set_xlabel("subset output index")
    axes[0].set_ylabel("feynman_real")
    axes[0].set_title("Feynman amplitude real part")
    axes[0].grid(True, alpha=0.25)

    axes[1].plot(xs, feynman_pop, marker="o", linewidth=1.3, markersize=3, label="Feynman")
    axes[1].plot(xs, qiskit_pop, marker="x", linewidth=1.1, markersize=3, label="Qiskit")
    axes[1].set_xlabel("subset output index")
    axes[1].set_ylabel("population")
    axes[1].set_title("Output population agreement")
    axes[1].grid(True, alpha=0.25)
    axes[1].legend()

    fig.tight_layout()
    out = output_path.resolve() if output_path else comparison_csv.with_name("agreement_plot.pdf")
    fig.savefig(out, dpi=180, bbox_inches="tight")
    plt.close(fig)
    return out


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    cfg = _merge_config(args)
    config_stem = Path(args.config).resolve().stem if args.config else _sanitize(str(cfg["experiment_name"]))

    repo_root = Path(cfg["repo_root"]).resolve()
    output_root = _resolve_path(cfg["output_root"], repo_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    run_dir = output_root / f"{_utc_stamp()}_{_sanitize(cfg['experiment_name'])}"
    run_dir.mkdir(parents=True, exist_ok=False)

    circuit, _ = resolve_circuit_input(cfg["circuit"], repo_root)
    input_statevector, _ = resolve_statevector_input(cfg["input_statevector"], repo_root)
    output_bitstrings, _ = resolve_output_bitstrings_input(cfg["output_bitstrings"], repo_root)
    binary = _resolve_path(cfg["binary"], repo_root).resolve()
    if not binary.exists():
        raise FileNotFoundError(f"Binary not found: {binary}")

    subset_ints, _ = parse_hs(output_bitstrings)
    declared_n, instructions = parse_qasm(circuit)
    sim_n = ((declared_n + 7) // 8) * 8

    qc = build_qiskit_circuit(sim_n, instructions)
    input_vec = build_dense_input(input_statevector, sim_n)

    qiskit_t0 = time.perf_counter()
    qiskit_sv = Statevector(input_vec).evolve(qc)
    qiskit_runtime_s = time.perf_counter() - qiskit_t0

    feynman_output = run_dir / "feynman_output.hsv"
    feynman_runtime_s, stdout, stderr = run_feynman(
        binary=binary,
        mpirun=str(cfg["mpirun"]),
        ranks=int(cfg["ranks"]),
        circuit=circuit,
        input_statevector=input_statevector,
        output_bitstrings=output_bitstrings,
        output_file=feynman_output,
        fraction=float(cfg["fraction"]),
        threshold=float(cfg["threshold"]),
        batch_size=int(cfg["batch_size"]),
        verbosity=int(cfg["verbosity"]),
    )

    (run_dir / "stdout.log").write_text(stdout, encoding="utf-8")
    (run_dir / "stderr.log").write_text(stderr, encoding="utf-8")

    feynman_sparse = parse_hsv_sparse(feynman_output)
    qiskit_subset = [qiskit_sv.data[idx] for idx in subset_ints]
    _write_hsv(run_dir / "qiskit_reference_subset.hsv", subset_ints, qiskit_subset)

    comparison_csv = run_dir / "comparison.csv"
    abs_errs: list[float] = []
    pop_errs: list[float] = []
    with comparison_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "bitstring_hex",
                "feynman_real",
                "feynman_imag",
                "qiskit_real",
                "qiskit_imag",
                "abs_amp_error",
                "feynman_population",
                "qiskit_population",
                "abs_population_error",
            ]
        )
        for idx, q_amp in zip(subset_ints, qiskit_subset):
            f_amp = feynman_sparse.get(idx, 0.0 + 0.0j)
            abs_err = abs(f_amp - q_amp)
            f_pop = float((f_amp.real * f_amp.real) + (f_amp.imag * f_amp.imag))
            q_pop = float((q_amp.real * q_amp.real) + (q_amp.imag * q_amp.imag))
            pop_err = abs(f_pop - q_pop)
            abs_errs.append(abs_err)
            pop_errs.append(pop_err)
            w.writerow(
                [
                    f"0x{idx:02x}",
                    f"{f_amp.real:.18e}",
                    f"{f_amp.imag:.18e}",
                    f"{q_amp.real:.18e}",
                    f"{q_amp.imag:.18e}",
                    f"{abs_err:.18e}",
                    f"{f_pop:.18e}",
                    f"{q_pop:.18e}",
                    f"{pop_err:.18e}",
                ]
            )

    max_abs_err = max(abs_errs) if abs_errs else 0.0
    mean_abs_err = float(np.mean(abs_errs)) if abs_errs else 0.0
    max_pop_err = max(pop_errs) if pop_errs else 0.0
    mean_pop_err = float(np.mean(pop_errs)) if pop_errs else 0.0
    agreement_plot = plot_from_comparison_csv(
        comparison_csv,
        output_path=run_dir / f"{config_stem}.pdf",
        label_fontsize=cfg.get("plot_label_fontsize"),
    )

    summary = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "experiment_name": cfg["experiment_name"],
        "paths": {
            "run_dir": str(run_dir),
            "circuit": str(circuit),
            "input_statevector": str(input_statevector),
            "output_bitstrings": str(output_bitstrings),
            "feynman_output": str(feynman_output),
            "qiskit_reference_subset": str(run_dir / "qiskit_reference_subset.hsv"),
            "comparison_csv": str(comparison_csv),
            "agreement_plot": str(agreement_plot),
            "stdout_log": str(run_dir / "stdout.log"),
            "stderr_log": str(run_dir / "stderr.log"),
        },
        "config": cfg,
        "config_file": str(Path(args.config).resolve()) if args.config else None,
        "circuit": {
            "declared_qubits": declared_n,
            "simulator_qubits": sim_n,
            "subset_size": len(subset_ints),
        },
        "metrics": {
            "feynman_runtime_s": feynman_runtime_s,
            "feynman_internal_total_s": _parse_feynman_internal_runtime(stdout),
            "qiskit_runtime_s": qiskit_runtime_s,
            "max_abs_amp_error": max_abs_err,
            "mean_abs_amp_error": mean_abs_err,
            "max_abs_population_error": max_pop_err,
            "mean_abs_population_error": mean_pop_err,
        },
    }

    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"Run directory: {run_dir}")
    print(f"Feynman runtime (s): {feynman_runtime_s:.6f}")
    if summary["metrics"]["feynman_internal_total_s"] is not None:
        print(f"Feynman internal total (s): {summary['metrics']['feynman_internal_total_s']:.6f}")
    print(f"Qiskit runtime (s): {qiskit_runtime_s:.6f}")
    print(f"Max |amp_feynman - amp_qiskit|: {max_abs_err:.6e}")
    print(f"Mean |amp_feynman - amp_qiskit|: {mean_abs_err:.6e}")
    print(f"Agreement plot: {agreement_plot}")
    print(f"Wrote: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

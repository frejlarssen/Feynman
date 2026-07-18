#!/usr/bin/env python
"""Compare quantum-walk selected amplitudes with quimb tensor contraction."""

from __future__ import annotations

import argparse
import builtins
import csv
import datetime as dt
import json
import re
import resource
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


def _log(message: str, *, verbosity: int, level: int = 1) -> None:
    if verbosity >= level:
        stamp = dt.datetime.now().strftime("%H:%M:%S")
        print(f"[{stamp}] {message}", flush=True)


def _rss_mb() -> float:
    return _usage_rss_mb(resource.getrusage(resource.RUSAGE_SELF))


def _children_rss_mb() -> float:
    return _usage_rss_mb(resource.getrusage(resource.RUSAGE_CHILDREN))


def _usage_rss_mb(usage: resource.struct_rusage) -> float:
    rss = usage.ru_maxrss
    if sys.platform == "darwin":
        return rss / (1024 * 1024)
    return rss / 1024


def _tn_stats(tn: Any) -> str:
    num_tensors = getattr(tn, "num_tensors", "?")
    num_indices = getattr(tn, "num_indices", "?")
    exponent = getattr(tn, "exponent", 0.0)
    return f"tensors={num_tensors}, indices={num_indices}, exponent={exponent}, maxrss_mb={_rss_mb():.1f}"


def _tree_stats(tree: Any) -> str:
    parts = []
    for label, method_name in (
        ("width", "contraction_width"),
        ("cost_log10", "contraction_cost"),
        ("max_size", "max_size"),
        ("peak_size", "peak_size"),
    ):
        method = getattr(tree, method_name, None)
        if not callable(method):
            continue
        try:
            value = method()
        except Exception:
            continue
        if label == "cost_log10":
            try:
                value = f"{max(float(value), 1.0):.3e}"
            except (TypeError, ValueError):
                pass
        parts.append(f"{label}={value}")
    return ", ".join(parts) if parts else "tree_stats=unavailable"


def _tree_size(tree: Any, method_name: str) -> int | None:
    method = getattr(tree, method_name, None)
    if not callable(method):
        return None
    try:
        return int(method())
    except Exception:
        return None


class QuimbContractionSizeError(MemoryError):
    def __init__(
        self,
        *,
        estimated_bytes: int,
        max_bytes: int,
        max_size: int | None,
        peak_size: int | None,
    ):
        self.estimated_bytes = estimated_bytes
        self.max_bytes = max_bytes
        self.max_size = max_size
        self.peak_size = peak_size
        super().__init__(
            "Refusing quimb contraction because the contraction tree exceeds the configured memory guard: "
            f"estimated_bytes={estimated_bytes}, quimb_max_contraction_bytes={max_bytes}."
        )


def _log_elapsed(message: str, start: float, *, verbosity: int, tn: Any | None = None) -> None:
    stats = f", {_tn_stats(tn)}" if tn is not None else f", maxrss_mb={_rss_mb():.1f}"
    _log(f"{message}: elapsed_s={time.perf_counter() - start:.3f}{stats}", verbosity=verbosity)


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
        "quimb_max_contraction_bytes": raw.get("quimb_max_contraction_bytes"),
        "quimb_optimize": str(raw.get("quimb_optimize", "greedy")),
        "quimb_rehearse": bool(raw.get("quimb_rehearse", False)),
        "quimb_simplify_sequence": raw.get("quimb_simplify_sequence", "ADCRS"),
        "quimb_simplify_atol": float(raw.get("quimb_simplify_atol", 1e-12)),
        "quimb_simplify_equalize_norms": bool(raw.get("quimb_simplify_equalize_norms", False)),
        "run_feynman": bool(raw.get("run_feynman", True)),
        "run_feynman_transpiled": bool(raw.get("run_feynman_transpiled", False)),
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


def _as_complex_scalar(value: Any) -> complex:
    item = getattr(value, "item", None)
    if callable(item):
        value = item()
    return complex(value)


def _write_hsv(path: Path, values: list[int], amps: list[complex]) -> None:
    width = max(2, max((v.bit_length() + 3) // 4 for v in values) if values else 2)
    with path.open("w", encoding="utf-8") as fh:
        for idx, amp in zip(values, amps):
            fh.write(f"0x{idx:0{width}x}:{_complex_to_token(amp)}\n")


def _parse_feynman_internal_runtime(stdout: str) -> float | None:
    m = re.search(r"Total clocktime \(including I/O\) for sv\.cpp:\s+([0-9eE+.\-]+) seconds", stdout)
    return float(m.group(1)) if m else None


class FeynmanRunError(RuntimeError):
    def __init__(self, cmd: list[str], returncode: int, stdout: str, stderr: str):
        self.cmd = cmd
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(f"Feynman command failed with exit code {returncode}: {' '.join(cmd)}")


class FeynmanOutputMissing(RuntimeError):
    def __init__(self, output_file: Path):
        self.output_file = output_file
        super().__init__(f"Feynman command returned successfully but did not write output: {output_file}")


class QuimbRunError(RuntimeError):
    def __init__(
        self,
        *,
        stage: str,
        meta: dict[str, Any],
        transpile_s: float,
        build_s: float | None,
        amplitude_s: float | None,
        original_error: BaseException,
    ):
        self.stage = stage
        self.meta = meta
        self.transpile_s = transpile_s
        self.build_s = build_s
        self.amplitude_s = amplitude_s
        self.original_error = original_error
        super().__init__(f"quimb failed during {stage}: {type(original_error).__name__}: {original_error}")


def _run_feynman(
    *,
    cfg: dict[str, Any],
    repo_root: Path,
    circuit: Path,
    input_statevector: Path,
    output_bitstrings: Path,
    output_file: Path,
) -> tuple[float, float | None, float, str, str]:
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
    proc = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, check=False)
    walltime_s = time.perf_counter() - t0
    peak_rss_mb = _children_rss_mb()
    if proc.returncode != 0:
        raise FeynmanRunError(cmd, proc.returncode, proc.stdout, proc.stderr)
    return walltime_s, _parse_feynman_internal_runtime(proc.stdout), peak_rss_mb, proc.stdout, proc.stderr


def _run_and_record_feynman(
    *,
    cfg: dict[str, Any],
    repo_root: Path,
    run_dir: Path,
    circuit: Path,
    input_statevector: Path,
    output_bitstrings: Path,
    label: str,
    output_name: str,
    verbosity: int,
) -> dict[str, Any]:
    output_file = run_dir / output_name
    _log(f"Running Feynman binary ({label})", verbosity=verbosity)
    try:
        wall_s, internal_s, peak_rss_mb, stdout, stderr = _run_feynman(
            cfg=cfg,
            repo_root=repo_root,
            circuit=circuit,
            input_statevector=input_statevector,
            output_bitstrings=output_bitstrings,
            output_file=output_file,
        )
    except FeynmanRunError as err:
        (run_dir / f"{label}_stdout.log").write_text(err.stdout, encoding="utf-8")
        (run_dir / f"{label}_stderr.log").write_text(err.stderr, encoding="utf-8")
        (run_dir / f"{label}_command.json").write_text(
            json.dumps({"returncode": err.returncode, "cmd": err.cmd}, indent=2),
            encoding="utf-8",
        )
        raise
    (run_dir / f"{label}_stdout.log").write_text(stdout, encoding="utf-8")
    (run_dir / f"{label}_stderr.log").write_text(stderr, encoding="utf-8")
    if not output_file.exists():
        (run_dir / f"{label}_command.json").write_text(
            json.dumps({"returncode": 0, "output_missing": str(output_file)}, indent=2),
            encoding="utf-8",
        )
        raise FeynmanOutputMissing(output_file)
    _log(f"Feynman run done ({label}): walltime_s={wall_s:.3f}", verbosity=verbosity)
    return {
        "enabled": True,
        "failed": False,
        "walltime_s": wall_s,
        "internal_total_s": internal_s,
        "peak_rss_mb": peak_rss_mb,
        "output": str(output_file),
        "circuit": str(circuit),
    }


def _failed_feynman_metrics(
    *,
    err: Exception,
    circuit: Path,
    output_file: Path,
) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "enabled": True,
        "failed": True,
        "walltime_s": None,
        "internal_total_s": None,
        "peak_rss_mb": None,
        "output": str(output_file),
        "circuit": str(circuit),
        "error_type": type(err).__name__,
        "error": str(err),
    }
    if isinstance(err, FeynmanRunError):
        metrics["returncode"] = err.returncode
        metrics["cmd"] = err.cmd
    return metrics


def _run_optional_feynman(
    *,
    cfg: dict[str, Any],
    repo_root: Path,
    run_dir: Path,
    circuit: Path,
    input_statevector: Path,
    output_bitstrings: Path,
    label: str,
    output_name: str,
    verbosity: int,
) -> dict[str, Any]:
    try:
        return _run_and_record_feynman(
            cfg=cfg,
            repo_root=repo_root,
            run_dir=run_dir,
            circuit=circuit,
            input_statevector=input_statevector,
            output_bitstrings=output_bitstrings,
            label=label,
            output_name=output_name,
            verbosity=verbosity,
        )
    except (FeynmanRunError, FeynmanOutputMissing) as err:
        _log(f"Feynman run failed ({label}): {err}", verbosity=verbosity)
        return _failed_feynman_metrics(
            err=err,
            circuit=circuit,
            output_file=run_dir / output_name,
        )


def _format_qasm_param(value: Any) -> str:
    return f"{float(value):.17g}"


def _qarg(q: int) -> str:
    return f"q[{q}]"


def _write_feynman_qasm_from_qiskit(qc: Any, path: Path) -> None:
    lines = [
        "OPENQASM 3.0;",
        'include "stdgates.inc";',
        f"qreg q[{qc.num_qubits}];",
    ]
    no_param_gates = {"h", "x", "z", "swap", "cx", "ccx", "cz", "ccz", "cswap", "t", "tdg"}
    param_gates = {"p", "u1", "u2", "u3", "rx", "ry", "cp", "crx", "cry"}
    for inst in qc.data:
        op = inst.operation
        name = op.name.lower()
        if name in {"barrier", "measure", "delay", "id"}:
            continue
        qubits = [qc.find_bit(q).index for q in inst.qubits]
        args = ",".join(_qarg(q) for q in qubits)
        if name in no_param_gates:
            if op.params:
                raise ValueError(f"Expected no parameters for {name}, got {len(op.params)}.")
            lines.append(f"{name} {args};")
        elif name in param_gates:
            params = ",".join(_format_qasm_param(p) for p in op.params)
            lines.append(f"{name}({params}) {args};")
        else:
            raise ValueError(
                "Cannot serialize quimb-transpiled circuit for Feynman: "
                f"unsupported gate {op.name!r}."
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


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


def _profiled_quimb_amplitude(
    quimb_circ: Any,
    bitstring: str,
    *,
    optimize: str,
    max_contraction_bytes: int | None,
    simplify_sequence: str,
    simplify_atol: float,
    simplify_equalize_norms: bool,
    verbosity: int,
) -> Any:
    fs_opts = {
        "seq": simplify_sequence,
        "atol": simplify_atol,
        "equalize_norms": simplify_equalize_norms,
    }

    start = time.perf_counter()
    quimb_circ._maybe_init_storage()
    _log_elapsed("  quimb storage ready", start, verbosity=verbosity)

    start = time.perf_counter()
    psi_b = quimb_circ.get_psi_simplified(**fs_opts)
    _log_elapsed("  get_psi_simplified done", start, verbosity=verbosity, tn=psi_b)

    start = time.perf_counter()
    for site, value in enumerate(bitstring):
        psi_b.isel_({psi_b.site_ind(site): value})
    _log_elapsed("  bitstring projection done", start, verbosity=verbosity, tn=psi_b)

    start = time.perf_counter()
    psi_b.full_simplify_(**fs_opts)
    _log_elapsed("  final full_simplify done", start, verbosity=verbosity, tn=psi_b)

    start = time.perf_counter()
    tree = psi_b.contraction_tree(output_inds=(), optimize=optimize)
    _log(
        f"  contraction tree ready: elapsed_s={time.perf_counter() - start:.3f}, "
        f"{_tree_stats(tree)}, maxrss_mb={_rss_mb():.1f}",
        verbosity=verbosity,
    )
    if max_contraction_bytes is not None:
        max_size = _tree_size(tree, "max_size")
        peak_size = _tree_size(tree, "peak_size")
        sizes = [size for size in (max_size, peak_size) if size is not None]
        if sizes:
            estimated_bytes = max(sizes) * 16
            if estimated_bytes > max_contraction_bytes:
                raise QuimbContractionSizeError(
                    estimated_bytes=estimated_bytes,
                    max_bytes=max_contraction_bytes,
                    max_size=max_size,
                    peak_size=peak_size,
                )

    start = time.perf_counter()
    amp = psi_b.contract(builtins.all, output_inds=(), optimize=tree)
    _log_elapsed("  contraction done", start, verbosity=verbosity)
    return amp


def _compute_quimb_amplitudes(
    *,
    circuit: Path,
    transpiled_qasm: Path,
    output_indices: list[int],
    input_index: int,
    input_amplitude: complex,
    optimization_level: int,
    optimize: str,
    max_contraction_bytes: int | None,
    rehearse: bool,
    simplify_sequence: str,
    simplify_atol: float,
    simplify_equalize_norms: bool,
    verbosity: int,
) -> tuple[list[complex] | None, dict[str, Any], float, float | None, float | None]:
    declared_n, instructions = parse_qasm(circuit)
    sim_n = ((declared_n + 7) // 8) * 8
    if input_index != 0:
        raise ValueError("quimb Circuit.amplitude evaluates amplitudes from |0...0> input.")

    _log(
        f"Building Qiskit circuit: declared_qubits={declared_n}, simulator_qubits={sim_n}, "
        f"instructions={len(instructions)}",
        verbosity=verbosity,
    )
    t0 = time.perf_counter()
    qc = build_qiskit_circuit(sim_n, instructions)
    _log(
        f"Transpiling for quimb: qiskit_ops={qc.size()}, optimization_level={optimization_level}",
        verbosity=verbosity,
    )
    tqc = transpile_for_quimb(qc, optimization_level=optimization_level)
    transpile_s = time.perf_counter() - t0
    gate_counts = dict(tqc.count_ops())
    transpiled_ops = tqc.size()
    _write_feynman_qasm_from_qiskit(tqc, transpiled_qasm)
    _log(
        f"Transpile done: transpiled_ops={transpiled_ops}, gate_counts={gate_counts}, "
        f"global_phase={tqc.global_phase}, elapsed_s={transpile_s:.3f}",
        verbosity=verbosity,
    )
    meta = {
        "declared_qubits": declared_n,
        "simulator_qubits": sim_n,
        "original_qiskit_ops": qc.size(),
        "transpiled_qiskit_ops": transpiled_ops,
        "transpiled_gate_counts": gate_counts,
        "transpiled_qasm": str(transpiled_qasm),
        "transpiled_global_phase": str(tqc.global_phase),
    }
    _log("Building quimb circuit from transpiled Qiskit circuit", verbosity=verbosity)
    t1 = time.perf_counter()
    try:
        quimb_circ = _qiskit_to_quimb_circuit(tqc)
    except Exception as err:
        raise QuimbRunError(
            stage="build",
            meta=meta,
            transpile_s=transpile_s,
            build_s=time.perf_counter() - t1,
            amplitude_s=None,
            original_error=err,
        ) from err
    build_s = time.perf_counter() - t1
    _log(f"quimb circuit built: elapsed_s={build_s:.3f}", verbosity=verbosity)

    amps: list[complex] = []
    t2 = time.perf_counter()
    amplitude_opts = {
        "optimize": optimize,
        "simplify_sequence": simplify_sequence,
        "simplify_atol": simplify_atol,
        "simplify_equalize_norms": simplify_equalize_norms,
    }
    _log(
        f"Computing {len(output_indices)} quimb amplitudes: optimize={optimize}, "
        f"simplify_sequence={simplify_sequence}, equalize_norms={simplify_equalize_norms}",
        verbosity=verbosity,
    )
    current_amp: dict[str, Any] | None = None
    try:
        for amp_i, idx in enumerate(output_indices, start=1):
            bitstring = _index_to_quimb_bitstring(idx, sim_n)
            current_amp = {"ordinal": amp_i, "hex": f"0x{idx:x}", "bitstring": bitstring}
            amp_t0 = time.perf_counter()
            _log(
                f"quimb amplitude {amp_i}/{len(output_indices)} start: hex=0x{idx:x}, bitstring={bitstring}",
                verbosity=verbosity,
            )
            if rehearse:
                quimb_circ.amplitude(bitstring, rehearse=True, **amplitude_opts)
            amp = _profiled_quimb_amplitude(
                quimb_circ,
                bitstring,
                optimize=optimize,
                max_contraction_bytes=max_contraction_bytes,
                simplify_sequence=simplify_sequence,
                simplify_atol=simplify_atol,
                simplify_equalize_norms=simplify_equalize_norms,
                verbosity=verbosity,
            )
            amp_value = _as_complex_scalar(amp) * input_amplitude
            amps.append(amp_value)
            _log(
                f"quimb amplitude {amp_i}/{len(output_indices)} done: hex=0x{idx:x}, "
                f"elapsed_s={time.perf_counter() - amp_t0:.3f}, abs={abs(amp_value):.6e}",
                verbosity=verbosity,
            )
    except Exception as err:
        meta["quimb_amplitude_options"] = amplitude_opts
        meta["quimb_completed_amplitudes"] = len(amps)
        meta["quimb_failed_amplitude"] = current_amp
        if isinstance(err, QuimbContractionSizeError):
            meta["quimb_contraction_estimate"] = {
                "estimated_bytes": err.estimated_bytes,
                "max_bytes": err.max_bytes,
                "max_size": err.max_size,
                "peak_size": err.peak_size,
            }
        raise QuimbRunError(
            stage="amplitude",
            meta=meta,
            transpile_s=transpile_s,
            build_s=build_s,
            amplitude_s=time.perf_counter() - t2,
            original_error=err,
        ) from err
    amplitude_s = time.perf_counter() - t2
    _log(f"quimb amplitudes done: elapsed_s={amplitude_s:.3f}", verbosity=verbosity)

    meta["quimb_amplitude_options"] = amplitude_opts
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
    verbosity = int(cfg["verbosity"])
    repo_root = _resolve_path(cfg["repo_root"], Path.cwd()).resolve()
    output_root = _resolve_path(cfg["output_root"], repo_root).resolve()
    run_dir = output_root / f"{_utc_stamp()}_{_sanitize(str(cfg['experiment_name']))}"
    run_dir.mkdir(parents=True, exist_ok=False)
    process_start_peak_rss_mb = _rss_mb()
    _log(f"Run directory: {run_dir}", verbosity=verbosity)

    _log("Materializing circuit, input statevector, and output bitstrings", verbosity=verbosity)
    circuit, circuit_generated = resolve_circuit_input(cfg["circuit"], repo_root)
    input_statevector, input_generated = resolve_statevector_input(cfg["input_statevector"], repo_root)
    output_bitstrings, output_generated = resolve_output_bitstrings_input(cfg["output_bitstrings"], repo_root)
    output_indices, output_size_bytes = parse_hs(output_bitstrings)
    input_index, input_amplitude = _single_input_basis_state(input_statevector)
    _log(
        f"Inputs ready: circuit={circuit}, input={input_statevector}, "
        f"outputs={output_bitstrings}, output_count={len(output_indices)}",
        verbosity=verbosity,
    )
    transpiled_qasm = run_dir / "quimb_transpiled.qasm"

    try:
        quimb_amps, quimb_meta, transpile_s, build_s, amplitude_s = _compute_quimb_amplitudes(
            circuit=circuit,
            transpiled_qasm=transpiled_qasm,
            output_indices=output_indices,
            input_index=input_index,
            input_amplitude=input_amplitude,
            optimization_level=int(cfg["qiskit_optimization_level"]),
            optimize=str(cfg["quimb_optimize"]),
            max_contraction_bytes=(
                None
                if cfg["quimb_max_contraction_bytes"] is None
                else int(cfg["quimb_max_contraction_bytes"])
            ),
            rehearse=bool(cfg["quimb_rehearse"]),
            simplify_sequence=str(cfg["quimb_simplify_sequence"]),
            simplify_atol=float(cfg["quimb_simplify_atol"]),
            simplify_equalize_norms=bool(cfg["quimb_simplify_equalize_norms"]),
            verbosity=verbosity,
        )
    except QuimbRunError as err:
        status = "quimb_failed"
        report_path = run_dir / "quimb_failed.json"
        report = {
            "status": status,
            "stage": err.stage,
            "error_type": type(err.original_error).__name__,
            "error": str(err.original_error),
            "config_file": str(args.config.resolve()),
            **err.meta,
        }
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        feynman_metrics: dict[str, Any] = {
            "enabled": bool(cfg["run_feynman"]),
            "walltime_s": None,
            "internal_total_s": None,
            "peak_rss_mb": None,
        }
        feynman_transpiled_metrics: dict[str, Any] = {
            "enabled": bool(cfg["run_feynman_transpiled"]),
            "walltime_s": None,
            "internal_total_s": None,
            "peak_rss_mb": None,
            "circuit": str(transpiled_qasm),
        }
        if cfg["run_feynman"]:
            _log(f"Running Feynman binary on original circuit after {status}", verbosity=verbosity)
            feynman_metrics = _run_and_record_feynman(
                cfg=cfg,
                repo_root=repo_root,
                run_dir=run_dir,
                circuit=circuit,
                input_statevector=input_statevector,
                output_bitstrings=output_bitstrings,
                label="feynman",
                output_name="feynman_output.hsv",
                verbosity=verbosity,
            )
        if cfg["run_feynman_transpiled"]:
            feynman_transpiled_metrics = _run_optional_feynman(
                cfg=cfg,
                repo_root=repo_root,
                run_dir=run_dir,
                circuit=transpiled_qasm,
                input_statevector=input_statevector,
                output_bitstrings=output_bitstrings,
                label="feynman_transpiled",
                output_name="feynman_transpiled_output.hsv",
                verbosity=verbosity,
            )
        summary_path = run_dir / "summary.json"
        summary = {
            "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "experiment_name": cfg["experiment_name"],
            "notes": cfg["notes"],
            "status": status,
            "config": cfg,
            "config_file": str(args.config.resolve()),
            "paths": {
                "run_dir": str(run_dir),
                "circuit": str(circuit),
                "input_statevector": str(input_statevector),
                "output_bitstrings": str(output_bitstrings),
                status: str(report_path),
                "transpiled_qasm": str(transpiled_qasm),
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
                **err.meta,
            },
            "metrics": {
                "quimb_transpile_s": err.transpile_s,
                "quimb_build_s": err.build_s,
                "quimb_amplitude_s": err.amplitude_s,
                "quimb_total_s": err.transpile_s + (err.build_s or 0.0) + (err.amplitude_s or 0.0),
                "process_start_peak_rss_mb": process_start_peak_rss_mb,
                "quimb_phase_peak_rss_mb": _rss_mb(),
                "process_peak_rss_mb": _rss_mb(),
                "quimb_failure_stage": err.stage,
                "quimb_error_type": type(err.original_error).__name__,
                "quimb_error": str(err.original_error),
                "feynman": feynman_metrics,
                "feynman_transpiled": feynman_transpiled_metrics,
            },
        }
        summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        _log(str(err), verbosity=verbosity)
        _log(f"Wrote quimb failure report: {report_path}", verbosity=verbosity)
        _log(f"Wrote summary: {summary_path}", verbosity=verbosity)
        return 3
    quimb_output = run_dir / "quimb_output.hsv"
    _write_hsv(quimb_output, output_indices, quimb_amps)
    _log(f"Wrote quimb output: {quimb_output}", verbosity=verbosity)
    quimb_phase_peak_rss_mb = _rss_mb()

    feynman_sparse: dict[int, complex] | None = None
    feynman_metrics: dict[str, Any] = {
        "enabled": bool(cfg["run_feynman"]),
        "walltime_s": None,
        "internal_total_s": None,
        "peak_rss_mb": None,
    }
    feynman_transpiled_sparse: dict[int, complex] | None = None
    feynman_transpiled_metrics: dict[str, Any] = {
        "enabled": bool(cfg["run_feynman_transpiled"]),
        "walltime_s": None,
        "internal_total_s": None,
        "peak_rss_mb": None,
        "circuit": str(transpiled_qasm),
    }
    if cfg["run_feynman"]:
        feynman_metrics = _run_and_record_feynman(
            cfg=cfg,
            repo_root=repo_root,
            run_dir=run_dir,
            circuit=circuit,
            input_statevector=input_statevector,
            output_bitstrings=output_bitstrings,
            label="feynman",
            output_name="feynman_output.hsv",
            verbosity=verbosity,
        )
        feynman_sparse = parse_hsv_sparse(Path(str(feynman_metrics["output"])))
    if cfg["run_feynman_transpiled"]:
        feynman_transpiled_metrics = _run_optional_feynman(
            cfg=cfg,
            repo_root=repo_root,
            run_dir=run_dir,
            circuit=transpiled_qasm,
            input_statevector=input_statevector,
            output_bitstrings=output_bitstrings,
            label="feynman_transpiled",
            output_name="feynman_transpiled_output.hsv",
            verbosity=verbosity,
        )
        if not feynman_transpiled_metrics.get("failed"):
            feynman_transpiled_sparse = parse_hsv_sparse(Path(str(feynman_transpiled_metrics["output"])))

    comparison_csv = run_dir / "comparison.csv"
    _log(f"Writing comparison CSV: {comparison_csv}", verbosity=verbosity)
    agreement_metrics = _write_comparison_csv(
        comparison_csv,
        output_indices=output_indices,
        quimb_amps=quimb_amps,
        feynman_sparse=feynman_transpiled_sparse if cfg["run_feynman_transpiled"] else feynman_sparse,
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
            "transpiled_qasm": str(transpiled_qasm),
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
            "process_start_peak_rss_mb": process_start_peak_rss_mb,
            "quimb_phase_peak_rss_mb": quimb_phase_peak_rss_mb,
            "process_peak_rss_mb": _rss_mb(),
            "feynman": feynman_metrics,
            "feynman_transpiled": feynman_transpiled_metrics,
            **agreement_metrics,
        },
    }
    summary_path = run_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    _log(f"Wrote summary: {summary_path}", verbosity=verbosity)

    print(f"Run directory: {run_dir}")
    print(f"Quimb total (s): {summary['metrics']['quimb_total_s']:.6f}")
    print(f"Quimb amplitudes only (s): {amplitude_s:.6f}")
    if cfg["run_feynman"]:
        print(f"Feynman walltime (s): {feynman_metrics['walltime_s']:.6f}")
        if feynman_metrics["internal_total_s"] is not None:
            print(f"Feynman internal total (s): {feynman_metrics['internal_total_s']:.6f}")
        if agreement_metrics["max_abs_amp_error"] is not None:
            print(f"Max amplitude error: {agreement_metrics['max_abs_amp_error']:.6e}")
    if cfg["run_feynman_transpiled"]:
        if feynman_transpiled_metrics["walltime_s"] is not None:
            print(f"Feynman transpiled walltime (s): {feynman_transpiled_metrics['walltime_s']:.6f}")
        if feynman_transpiled_metrics["internal_total_s"] is not None:
            print(f"Feynman transpiled internal total (s): {feynman_transpiled_metrics['internal_total_s']:.6f}")
    print(f"Summary: {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

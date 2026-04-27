#!/usr/bin/env python3
"""QFT frequency demo with optional Qiskit reference overlay.

Runs sv_prefetcher and plots:
1) Input signal real part over the sparse support.
2) Output populations for requested output bitstrings.

Input artifacts can be provided directly as file paths or generated from
JSON-specified generator parameters.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(SCRIPT_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_REPO_ROOT))

from generators.circuits.qft_generator import (  # noqa: E402
    DEFAULT_OUTPUT_DIR as QFT_DEFAULT_OUTPUT_DIR,
    generate_qft,
)
from generators.hexstrings.hexstring_set_generator import (  # noqa: E402
    DEFAULT_OUTPUT_DIR as HEXSTR_DEFAULT_OUTPUT_DIR,
    write_one_interval,
    write_two_intervals,
)
from generators.statevectors.statevector_generator import (  # noqa: E402
    DEFAULT_OUTPUT_DIR as STATEVEC_DEFAULT_OUTPUT_DIR,
    write_ket0,
    write_two_freq,
    write_two_freq_n_qubits,
    write_two_tone_dense,
)
from scripts.sweeplib.plotting import apply_plot_fontsizes, resolve_label_fontsize  # noqa: E402


def _utc_stamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%d_%H%M%S")


def _sanitize(name: str) -> str:
    out = []
    for ch in name.strip():
        if ch.isalnum() or ch in ("-", "_", "."):
            out.append(ch)
        else:
            out.append("_")
    return "".join(out) or "demo"


def _parse_complex_token(token: str) -> complex:
    s = token.strip()
    plus = s.find("+", 1)
    i_pos = s.find("i", 1)
    if plus == -1 or i_pos == -1:
        raise ValueError(f"Invalid complex token: {token!r}")
    return complex(float(s[:plus]), float(s[plus + 1 : i_pos]))


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        payload = json.load(fh)
    if not isinstance(payload, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    return payload


def _merge_config(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], dict[str, Any], str | None]:
    cfg: dict[str, Any] = {}
    config_path_str: str | None = None
    if args.config:
        config_path = Path(args.config).resolve()
        cfg = _load_json(config_path)
        config_path_str = str(config_path)

    def pick(key: str, cli_value: Any, default: Any = None) -> Any:
        return cli_value if cli_value is not None else cfg.get(key, default)

    merged = {
        "experiment_name": pick("experiment_name", args.experiment_name, "qft_feynman_demo"),
        "binary": pick("binary", args.binary, "build/sv_prefetcher_subset_mpi.x"),
        "mpirun": pick("mpirun", args.mpirun, "mpirun"),
        "ranks": int(pick("ranks", args.ranks, 1)),
        "circuit": pick("circuit", args.circuit),
        "input_statevector": pick("input_statevector", args.input_statevector),
        "output_bitstrings": pick("output_bitstrings", args.output_bitstrings),
        "fraction": float(pick("fraction", args.fraction, 1.0)),
        "threshold": float(pick("threshold", args.threshold, 0.0)),
        "batch_size": int(pick("batch_size", args.batch_size, 32)),
        "verbosity": int(pick("verbosity", args.verbosity, 1)),
        "dense": bool(pick("dense", args.dense, False)),
        "p": pick("p", args.p, None),
        "r": pick("r", args.r, None),
        "output_root": pick("output_root", args.output_root, "data/outputs/validation"),
        "repo_root": pick("repo_root", args.repo_root, "."),
        "normalize_input": bool(pick("normalize_input", None, False)),
        "from_csv": bool(pick("from_csv", args.from_csv, False)),
        "population_csv": pick("population_csv", args.population_csv, None),
        "summary_json": pick("summary_json", args.summary_json, None),
        "plot_pdf": pick("plot_pdf", args.plot_pdf, None),
        "plot_title": pick("plot_title", args.plot_title, None),
        "plot_max_xticks": int(pick("plot_max_xticks", args.plot_max_xticks, 24)),
        "plot_label_fontsize": pick("plot_label_fontsize", args.plot_label_fontsize, None),
        "qiskit_reference": bool(pick("qiskit_reference", None, True)),
        "qiskit_max_qubits": int(pick("qiskit_max_qubits", None, 16)),
        "signal": cfg.get("signal", {}),
    }
    if merged["plot_label_fontsize"] is not None:
        merged["plot_label_fontsize"] = float(merged["plot_label_fontsize"])

    if not merged["from_csv"]:
        for key in ("circuit", "input_statevector", "output_bitstrings"):
            if merged[key] is None:
                raise ValueError(f"Missing required parameter: {key}")
    if merged["ranks"] < 1:
        raise ValueError("ranks must be >= 1")
    if merged["batch_size"] < 0:
        raise ValueError("batch_size must be >= 0")
    if merged["plot_max_xticks"] < 2:
        raise ValueError("plot_max_xticks must be >= 2")
    return merged, cfg, config_path_str


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


def _infer_declared_qubits_from_qasm(path: Path) -> int | None:
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("//"):
            continue
        if line.startswith("qreg ") or line.startswith("qubit "):
            lb = line.find("[")
            rb = line.find("]")
            if lb == -1 or rb == -1 or rb <= lb:
                return None
            return int(line[lb + 1 : rb])
    return None


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
    from qiskit.circuit.library import HGate, PhaseGate, SwapGate, XGate, ZGate

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


def _build_qiskit_circuit(parsed: ParsedQasm):
    from qiskit import QuantumCircuit

    qc = QuantumCircuit(parsed.simulator_qubits)
    for ins in parsed.instructions:
        expected_targets = _gate_num_targets(ins.base_gate)
        if len(ins.args) != ins.num_controls + expected_targets:
            raise ValueError(
                f"Gate arity mismatch for '{ins.base_gate}': args={ins.args}, controls={ins.num_controls}"
            )
        controls = ins.args[: ins.num_controls]
        targets = ins.args[ins.num_controls :]
        base = _make_base_gate(ins.base_gate, ins.params)
        if ins.num_controls == 0:
            qc.append(base, targets)
        else:
            qc.append(base.control(ins.num_controls), controls + targets)
    return qc


def _build_dense_input_vector(path: Path, n_qubits: int) -> np.ndarray:
    dim = 1 << n_qubits
    vec = np.zeros(dim, dtype=np.complex128)
    sparse = _read_hsv_sparse(path)
    for idx, amp in sparse.items():
        if idx < 0 or idx >= dim:
            raise ValueError(f"Input index 0x{idx:X} is outside dimension 2^{n_qubits} ({dim}).")
        vec[idx] = amp
    return vec


def _compute_qiskit_subset_pop(
    *,
    circuit: Path,
    input_statevector_path: Path,
    output_bins: list[int],
) -> tuple[np.ndarray, dict[str, int]]:
    from qiskit.quantum_info import Statevector

    parsed_qasm = _parse_openqasm_subset(circuit)
    qiskit_circuit = _build_qiskit_circuit(parsed_qasm)
    dim = 1 << parsed_qasm.simulator_qubits
    for idx in output_bins:
        if idx < 0 or idx >= dim:
            raise ValueError(
                f"Output subset index 0x{idx:X} outside 2^{parsed_qasm.simulator_qubits}."
            )

    input_vec = _build_dense_input_vector(input_statevector_path, parsed_qasm.simulator_qubits)
    sv_out = Statevector(input_vec).evolve(qiskit_circuit)
    subset_amp = np.array([sv_out.data[idx] for idx in output_bins], dtype=np.complex128)
    subset_pop = np.abs(subset_amp) ** 2
    return subset_pop.astype(np.float64), {
        "declared_qubits": parsed_qasm.declared_qubits,
        "simulator_qubits": parsed_qasm.simulator_qubits,
    }


def _read_hsv_sparse(path: Path) -> dict[int, complex]:
    out: dict[int, complex] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        idx_s, amp_s = line.split(":", 1)
        out[int(idx_s, 16)] = _parse_complex_token(amp_s)
    return out


def _read_population_csv(path: Path) -> tuple[list[int], np.ndarray, np.ndarray | None]:
    bins: list[int] = []
    pop: list[float] = []
    qiskit_pop: list[float | None] = []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"population"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError(f"CSV missing required columns in {path}: requires {sorted(required)}")
        for row in reader:
            if "bin_dec" in row and row["bin_dec"] not in (None, ""):
                b = int(row["bin_dec"])
            elif "bin_hex" in row and row["bin_hex"] not in (None, ""):
                b = int(row["bin_hex"], 16)
            else:
                raise ValueError(f"CSV row missing bin_dec/bin_hex in {path}")
            bins.append(b)
            pop.append(float(row["population"]))
            if "qiskit_population" in row and row["qiskit_population"] not in (None, ""):
                qiskit_pop.append(float(row["qiskit_population"]))
            else:
                qiskit_pop.append(None)
    qiskit_arr: np.ndarray | None = None
    if any(v is not None for v in qiskit_pop):
        qiskit_arr = np.array(
            [float("nan") if v is None else float(v) for v in qiskit_pop], dtype=np.float64
        )
    return bins, np.array(pop, dtype=np.float64), qiskit_arr


def _write_hsv_sparse(path: Path, sparse: dict[int, complex], size_bytes: int) -> None:
    width = size_bytes * 2
    with path.open("w", encoding="utf-8") as fh:
        for idx in sorted(sparse):
            amp = sparse[idx]
            fh.write(f"0x{idx:0{width}X}:{amp.real:.18f}+{amp.imag:.18f}i\n")


def _require_int(spec: dict[str, Any], key: str, label: str) -> int:
    if key not in spec:
        raise ValueError(f"Missing '{key}' in {label} generator spec.")
    return int(spec[key])


def _as_bool(value: Any, *, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ("1", "true", "yes", "y", "on"):
            return True
        if v in ("0", "false", "no", "n", "off"):
            return False
    return bool(value)


def _resolve_output_dir(spec: dict[str, Any], repo_root: Path, default_dir: Path) -> Path:
    out_dir_raw = spec.get("output_dir", None)
    if out_dir_raw is None:
        return default_dir.resolve()
    out_dir = Path(str(out_dir_raw))
    if not out_dir.is_absolute():
        out_dir = (repo_root / out_dir).resolve()
    return out_dir


def _build_interval(interval_spec: Any, label: str) -> list[int]:
    if isinstance(interval_spec, list):
        values = [int(v) for v in interval_spec]
    elif isinstance(interval_spec, dict):
        if "values" in interval_spec:
            values = [int(v) for v in interval_spec["values"]]
        elif "start" in interval_spec and "count" in interval_spec:
            start = int(interval_spec["start"])
            count = int(interval_spec["count"])
            if count <= 0:
                raise ValueError(f"{label}.count must be > 0")
            values = list(range(start, start + count))
        elif "start" in interval_spec and "end" in interval_spec:
            start = int(interval_spec["start"])
            end = int(interval_spec["end"])
            if end <= start:
                raise ValueError(f"{label}.end must be > {label}.start")
            values = list(range(start, end))
        elif "center" in interval_spec and "radius" in interval_spec:
            center = int(interval_spec["center"])
            radius = int(interval_spec["radius"])
            if radius <= 0:
                raise ValueError(f"{label}.radius must be > 0")
            values = list(range(center - radius, center + radius))
        else:
            raise ValueError(
                f"{label} must define one of: values, (start+count), (start+end), or (center+radius)."
            )
    else:
        raise ValueError(f"{label} must be an object or an array of integers.")

    if not values:
        raise ValueError(f"{label} must not be empty.")
    if min(values) < 0:
        raise ValueError(f"{label} contains negative values.")
    return values


def _resolve_circuit_path(circuit_cfg: Any, repo_root: Path) -> tuple[Path, dict[str, Any] | None]:
    if isinstance(circuit_cfg, str):
        path = Path(circuit_cfg)
        if not path.is_absolute():
            path = (repo_root / path).resolve()
        return path, None
    if not isinstance(circuit_cfg, dict):
        raise ValueError("circuit must be a path string or a generator object.")

    generator = str(circuit_cfg.get("generator", "qft")).strip().lower()
    if generator != "qft":
        raise ValueError(f"Unsupported circuit generator: {generator!r}")
    n = _require_int(circuit_cfg, "n", "circuit")
    k = _require_int(circuit_cfg, "k", "circuit")
    out_dir = _resolve_output_dir(circuit_cfg, repo_root, QFT_DEFAULT_OUTPUT_DIR)
    path = generate_qft(n=n, k=k, out_dir=out_dir).resolve()
    return path, {"generator": generator, "n": n, "k": k, "output_dir": str(out_dir)}


def _resolve_statevector_path(
    statevector_cfg: Any, repo_root: Path
) -> tuple[Path, dict[str, Any] | None]:
    if isinstance(statevector_cfg, str):
        path = Path(statevector_cfg)
        if not path.is_absolute():
            path = (repo_root / path).resolve()
        return path, None
    if not isinstance(statevector_cfg, dict):
        raise ValueError("input_statevector must be a path string or a generator object.")

    generator = str(statevector_cfg.get("generator", "two_freq")).strip().lower()
    out_dir = _resolve_output_dir(statevector_cfg, repo_root, STATEVEC_DEFAULT_OUTPUT_DIR)

    if generator in ("two_freq", "amplitude_signal"):
        size_raw = statevector_cfg.get("size")
        n_qubits_raw = statevector_cfg.get("n_qubits", statevector_cfg.get("n"))
        f1_raw = statevector_cfg.get("f1", statevector_cfg.get("f_low"))
        f2_raw = statevector_cfg.get("f2", statevector_cfg.get("f_high"))
        if f1_raw is None or f2_raw is None:
            raise ValueError("input_statevector two_freq requires f1/f2 (or f_low/f_high).")
        f1 = int(f1_raw)
        f2 = float(f2_raw)
        f2_amp = float(
            statevector_cfg.get(
                "f2_amp",
                statevector_cfg.get("rel_amp", statevector_cfg.get("relative_amp", 1.0)),
            )
        )
        threshold = float(statevector_cfg.get("threshold", 0.9999))
        complex_signal = _as_bool(
            statevector_cfg.get("complex_signal", statevector_cfg.get("complex", False))
        )
        full_support = _as_bool(
            statevector_cfg.get("full_support", statevector_cfg.get("full", False))
        )
        if size_raw is not None:
            size = int(size_raw)
            path = write_two_freq(
                size=size,
                f1=f1,
                f2=f2,
                f2_amp=f2_amp,
                threshold=threshold,
                out_dir=out_dir,
                complex_signal=complex_signal,
                full_support=full_support,
            ).resolve()
            n_qubits = size * 8
        else:
            if n_qubits_raw is None:
                raise ValueError(
                    "input_statevector two_freq requires either size (bytes) or n_qubits (or n)."
                )
            n_qubits = int(n_qubits_raw)
            path = write_two_freq_n_qubits(
                n_qubits=n_qubits,
                f1=f1,
                f2=f2,
                f2_amp=f2_amp,
                threshold=threshold,
                out_dir=out_dir,
                complex_signal=complex_signal,
                full_support=full_support,
            ).resolve()
        return path, {
            "generator": generator,
            "size": size_raw,
            "n_qubits": n_qubits,
            "f1": f1,
            "f2": f2,
            "f2_amp": f2_amp,
            "threshold": threshold,
            "complex_signal": complex_signal,
            "full_support": full_support,
            "output_dir": str(out_dir),
        }

    if generator in ("two_tone", "two_tone_dense"):
        n_qubits_raw = statevector_cfg.get("n_qubits", statevector_cfg.get("n"))
        if n_qubits_raw is None:
            raise ValueError("input_statevector two_tone requires n_qubits (or n).")
        n_qubits = int(n_qubits_raw)
        f1 = _require_int(statevector_cfg, "f1", "input_statevector")
        f2 = _require_int(statevector_cfg, "f2", "input_statevector")
        rel_amp = float(
            statevector_cfg.get(
                "rel_amp",
                statevector_cfg.get("relative_amp", statevector_cfg.get("f2_amp", 1.0)),
            )
        )
        path = write_two_tone_dense(
            n_qubits=n_qubits, f1=f1, f2=f2, rel_amp=rel_amp, out_dir=out_dir
        ).resolve()
        return path, {
            "generator": generator,
            "n_qubits": n_qubits,
            "f1": f1,
            "f2": f2,
            "rel_amp": rel_amp,
            "output_dir": str(out_dir),
        }

    if generator == "ket0":
        size = _require_int(statevector_cfg, "size", "input_statevector")
        path = write_ket0(size=size, out_dir=out_dir).resolve()
        return path, {"generator": generator, "size": size, "output_dir": str(out_dir)}

    raise ValueError(f"Unsupported input_statevector generator: {generator!r}")


def _resolve_output_bitstrings_path(
    output_cfg: Any, repo_root: Path
) -> tuple[Path, dict[str, Any] | None]:
    if isinstance(output_cfg, str):
        path = Path(output_cfg)
        if not path.is_absolute():
            path = (repo_root / path).resolve()
        return path, None
    if not isinstance(output_cfg, dict):
        raise ValueError("output_bitstrings must be a path string or a generator object.")

    generator = str(output_cfg.get("generator", "one_interval")).strip().lower()
    out_dir = _resolve_output_dir(output_cfg, repo_root, HEXSTR_DEFAULT_OUTPUT_DIR)

    if generator == "one_interval":
        size = _require_int(output_cfg, "size", "output_bitstrings")
        count = int(output_cfg.get("count", output_cfg.get("nr_hexstrings", 0)))
        start = int(output_cfg.get("start", 0))
        if count <= 0:
            raise ValueError("output_bitstrings one_interval requires count > 0.")
        if start != 0:
            raise ValueError(
                "one_interval generator currently supports only start=0. Use two_intervals for other ranges."
            )
        path = write_one_interval(size=size, nr_hexstrings=count, out_dir=out_dir).resolve()
        return path, {
            "generator": generator,
            "size": size,
            "start": start,
            "count": count,
            "output_dir": str(out_dir),
        }

    if generator == "two_intervals":
        size = _require_int(output_cfg, "size", "output_bitstrings")
        interval1 = _build_interval(output_cfg.get("interval1"), "output_bitstrings.interval1")
        interval2 = _build_interval(output_cfg.get("interval2"), "output_bitstrings.interval2")
        path = write_two_intervals(
            size=size,
            interval1=interval1,
            interval2=interval2,
            out_dir=out_dir,
        ).resolve()
        return path, {
            "generator": generator,
            "size": size,
            "interval1_count": len(interval1),
            "interval2_count": len(interval2),
            "output_dir": str(out_dir),
        }

    raise ValueError(f"Unsupported output_bitstrings generator: {generator!r}")


def _signal_meta_from_input(
    *,
    input_generated: dict[str, Any] | None,
    input_cfg: Any,
    signal_fallback: Any,
) -> dict[str, Any]:
    def from_spec(spec: Any) -> dict[str, Any] | None:
        if not isinstance(spec, dict):
            return None
        gen = str(spec.get("generator", "")).strip().lower()
        if gen in ("two_freq", "amplitude_signal"):
            f_low = spec.get("f1", spec.get("f_low"))
            f_high = spec.get("f2", spec.get("f_high"))
            rel = spec.get("f2_amp", spec.get("rel_amp", spec.get("relative_amp")))
            if f_low is not None and f_high is not None:
                return {"f_low": f_low, "f_high": f_high, "relative_amp": rel}
        if gen in ("two_tone", "two_tone_dense"):
            f_low = spec.get("f1", spec.get("f_low"))
            f_high = spec.get("f2", spec.get("f_high"))
            rel = spec.get("rel_amp", spec.get("f2_amp", spec.get("relative_amp")))
            if f_low is not None and f_high is not None:
                return {"f_low": f_low, "f_high": f_high, "relative_amp": rel}
        # Legacy metadata object already using f_low/f_high keys.
        if "f_low" in spec and "f_high" in spec:
            return {
                "f_low": spec.get("f_low"),
                "f_high": spec.get("f_high"),
                "relative_amp": spec.get("relative_amp", spec.get("rel_amp")),
            }
        return None

    # Priority: exact resolved generator spec -> input cfg spec -> legacy "signal".
    for candidate in (input_generated, input_cfg, signal_fallback):
        meta = from_spec(candidate)
        if meta is not None:
            return meta
    return {}


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
    run_args = [
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
        run_args.extend(["-p", str(p), "-r", str(r)])
    if dense:
        run_args.append("-D")

    # Running single-rank directly avoids fragile PMIx startup in constrained envs.
    if ranks == 1:
        cmd = run_args
    else:
        cmd = [mpirun, "-n", str(ranks), *run_args]

    proc = subprocess.run(
        cmd,
        cwd=str(repo_root),
        text=True,
        capture_output=True,
        check=False,
    )
    return cmd, proc.returncode, proc.stdout, proc.stderr


def _render_demo_plot(
    *,
    out_pdf: Path,
    input_sparse: dict[int, complex],
    output_bins: list[int],
    output_pop: np.ndarray,
    qiskit_pop: np.ndarray | None,
    max_xticks: int = 24,
    label_fontsize: float | None = None,
) -> None:
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    import os

    os.environ.setdefault("MPLCONFIGDIR", str(out_pdf.parent / ".mplconfig"))
    os.environ.setdefault("XDG_CACHE_HOME", str(out_pdf.parent / ".cache"))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    apply_plot_fontsizes(plt=plt, label_fontsize=label_fontsize)
    subplot_title_fontsize = max(1.0, resolve_label_fontsize(label_fontsize) - 2.0)

    # Left panel: sparse input real part.
    in_idx = np.array(sorted(input_sparse.keys()), dtype=np.int64)
    in_real = np.array([input_sparse[i].real for i in in_idx], dtype=np.float64)

    # Right panel: requested output populations.
    x_out = np.arange(len(output_bins))
    dec_labels = [str(b) for b in output_bins]

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))

    axes[0].plot(in_idx, in_real, linewidth=1.0)
    axes[0].set_title("Input Signal (Real Part)", fontsize=subplot_title_fontsize)
    axes[0].set_xlabel("Basis Index (Time domain)")
    axes[0].set_ylabel("Amplitude")
    axes[0].grid(True, axis="y", alpha=0.25)

    if qiskit_pop is not None:
        bar_w = 0.44
        axes[1].bar(x_out - bar_w / 2.0, output_pop, width=bar_w, alpha=0.82, label="Feynman")
        axes[1].bar(x_out + bar_w / 2.0, qiskit_pop, width=bar_w, alpha=0.72, label="Qiskit")
    else:
        axes[1].bar(x_out, output_pop, alpha=0.82, label="Feynman")
    axes[1].set_title("Output Population (Requested Bitstrings)", fontsize=subplot_title_fontsize)
    axes[1].set_xlabel("Output Bitstring (Frequency domain)")
    axes[1].set_ylabel(r"$|amp|^2$")
    if len(output_bins) <= max_xticks:
        tick_idx = list(range(len(output_bins)))
    else:
        step = max(1, math.ceil(len(output_bins) / max_xticks))
        tick_idx = list(range(0, len(output_bins), step))
        if tick_idx[-1] != len(output_bins) - 1:
            tick_idx.append(len(output_bins) - 1)
    axes[1].set_xticks(tick_idx, [dec_labels[i] for i in tick_idx], rotation=50, ha="right")
    axes[1].grid(True, axis="y", alpha=0.25)
    if qiskit_pop is not None:
        axes[1].legend()

    fig.tight_layout()
    fig.savefig(out_pdf)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a QFT frequency demo and produce a PDF plot."
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
    parser.add_argument("--from-csv", action="store_true", default=None)
    parser.add_argument("--population-csv", default=None)
    parser.add_argument("--summary-json", default=None)
    parser.add_argument("--plot-pdf", default=None)
    parser.add_argument("--plot-title", default=None)
    parser.add_argument("--plot-max-xticks", type=int, default=None)
    parser.add_argument("--plot-label-fontsize", type=float, default=None)
    parser.add_argument("--qiskit-reference", action="store_true", default=None)
    parser.add_argument("--qiskit-max-qubits", type=int, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cfg, raw_cfg, config_path_str = _merge_config(args)

    repo_root = Path(cfg["repo_root"]).resolve()

    if cfg["from_csv"]:
        summary: dict[str, Any] = {}
        if cfg["summary_json"] is not None:
            summary_path = Path(cfg["summary_json"])
            if not summary_path.is_absolute():
                summary_path = (repo_root / summary_path).resolve()
            summary = _load_json(summary_path)

        population_csv: str | None = cfg["population_csv"]
        input_statevector_cfg_raw: Any = cfg["input_statevector"]
        input_statevector_cfg: str | None = (
            input_statevector_cfg_raw if isinstance(input_statevector_cfg_raw, str) else None
        )

        if population_csv is None and isinstance(summary.get("paths"), dict):
            population_csv = summary["paths"].get("output_population_csv")
        if input_statevector_cfg is None and isinstance(summary.get("paths"), dict):
            input_statevector_cfg = summary["paths"].get("input_statevector_used") or summary["paths"].get(
                "input_statevector"
            )

        if population_csv is None:
            raise ValueError(
                "Missing population CSV for plotting. Provide --population-csv or --summary-json with paths.output_population_csv."
            )
        if input_statevector_cfg is None:
            raise ValueError(
                "Missing input statevector for plotting. Provide --input-statevector or --summary-json with paths.input_statevector_used."
            )

        population_csv_path = Path(population_csv)
        if not population_csv_path.is_absolute():
            population_csv_path = (repo_root / population_csv_path).resolve()
        input_statevector_plot = Path(input_statevector_cfg)
        if not input_statevector_plot.is_absolute():
            input_statevector_plot = (repo_root / input_statevector_plot).resolve()

        if cfg["plot_pdf"] is not None:
            plot_pdf = Path(cfg["plot_pdf"])
            if not plot_pdf.is_absolute():
                plot_pdf = (repo_root / plot_pdf).resolve()
        else:
            plot_pdf = population_csv_path.with_name("demo_plot_from_csv.pdf")

        for p in (population_csv_path, input_statevector_plot):
            if not p.exists():
                raise FileNotFoundError(f"Required path not found: {p}")

        output_bins, output_pop, qiskit_pop = _read_population_csv(population_csv_path)
        input_sparse = _read_hsv_sparse(input_statevector_plot)
        if not input_sparse:
            raise ValueError(f"Input statevector has no amplitudes: {input_statevector_plot}")

        _render_demo_plot(
            out_pdf=plot_pdf,
            input_sparse=input_sparse,
            output_bins=output_bins,
            output_pop=output_pop,
            qiskit_pop=qiskit_pop,
            max_xticks=int(cfg["plot_max_xticks"]),
            label_fontsize=cfg["plot_label_fontsize"],
        )

        print(f"Plot written: {plot_pdf}")
        print(f"Population CSV: {population_csv_path}")
        return 0

    binary = Path(str(cfg["binary"]))
    if not binary.is_absolute():
        binary = (repo_root / binary).resolve()

    circuit, circuit_generated = _resolve_circuit_path(cfg["circuit"], repo_root)
    input_statevector, input_generated = _resolve_statevector_path(cfg["input_statevector"], repo_root)
    output_bitstrings, output_generated = _resolve_output_bitstrings_path(
        cfg["output_bitstrings"], repo_root
    )
    output_root = (repo_root / cfg["output_root"]).resolve()

    for p in (binary, circuit, input_statevector, output_bitstrings):
        if not p.exists():
            raise FileNotFoundError(f"Required path not found: {p}")

    sweep_dir = output_root / f"{_utc_stamp()}_{_sanitize(cfg['experiment_name'])}"
    sweep_dir.mkdir(parents=True, exist_ok=False)

    output_bins, size_bytes = _read_output_bitstrings(output_bitstrings)
    declared_qubits = _infer_declared_qubits_from_qasm(circuit)
    if declared_qubits is not None:
        min_size_bytes = max(1, (declared_qubits + 7) // 8)
        if size_bytes < min_size_bytes:
            raise ValueError(
                "output_bitstrings size is too small for the circuit width: "
                f"got {size_bytes} byte(s), but qasm declares {declared_qubits} qubits "
                f"(minimum {min_size_bytes} byte(s))."
            )

    input_sparse_orig = _read_hsv_sparse(input_statevector)
    if not input_sparse_orig:
        raise ValueError(f"Input statevector has no amplitudes: {input_statevector}")

    input_norm2_before = float(
        np.sum(np.abs(np.array(list(input_sparse_orig.values()), dtype=np.complex128)) ** 2)
    )
    input_sparse = dict(input_sparse_orig)
    input_path_used = input_statevector
    if cfg["normalize_input"]:
        if input_norm2_before <= 0.0:
            raise ValueError("Cannot normalize input with non-positive norm.")
        scale = 1.0 / np.sqrt(input_norm2_before)
        input_sparse = {idx: amp * scale for idx, amp in input_sparse_orig.items()}
        input_path_used = sweep_dir / "input_normalized.hsv"
        _write_hsv_sparse(input_path_used, input_sparse, size_bytes=size_bytes)

    input_norm2_after = float(
        np.sum(np.abs(np.array(list(input_sparse.values()), dtype=np.complex128)) ** 2)
    )

    output_hsv = sweep_dir / "feynman_output.hsv"
    feynman_t0 = time.perf_counter()
    cmd, rc, stdout_text, stderr_text = _run_sv_prefetcher(
        repo_root=repo_root,
        mpirun=cfg["mpirun"],
        ranks=cfg["ranks"],
        binary=binary,
        circuit=circuit,
        input_statevector=input_path_used,
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
    feynman_runtime_s = float(time.perf_counter() - feynman_t0)
    (sweep_dir / "stdout.log").write_text(stdout_text, encoding="utf-8")
    (sweep_dir / "stderr.log").write_text(stderr_text, encoding="utf-8")
    (sweep_dir / "command.txt").write_text(shlex.join(cmd) + "\n", encoding="utf-8")
    if rc != 0:
        raise RuntimeError(
            f"sv_prefetcher failed with return code {rc}. See {sweep_dir / 'stderr.log'}"
        )
    if not output_hsv.exists():
        err_hint = ""
        if stderr_text.strip():
            tail = "\n".join(stderr_text.strip().splitlines()[-6:])
            err_hint = f"\nStderr tail:\n{tail}"
        raise RuntimeError(
            "sv_prefetcher did not produce the expected output file "
            f"({output_hsv}), even though return code was 0. "
            f"See logs in {sweep_dir}.{err_hint}"
        )

    feynman_sparse = _read_hsv_sparse(output_hsv)

    feynman_amp = np.array(
        [feynman_sparse.get(b, 0.0 + 0.0j) for b in output_bins], dtype=np.complex128
    )
    output_pop = np.abs(feynman_amp) ** 2
    qiskit_pop: np.ndarray | None = None
    qiskit_runtime_s: float | None = None
    qiskit_ref_info: dict[str, Any] = {
        "enabled": bool(cfg["qiskit_reference"]),
        "used": False,
        "reason": "",
        "declared_qubits": None,
        "simulator_qubits": None,
    }
    if cfg["qiskit_reference"]:
        declared_for_limit = _infer_declared_qubits_from_qasm(circuit)
        if declared_for_limit is None:
            qiskit_ref_info["reason"] = "Could not determine declared qubits from qasm; skipped."
        elif declared_for_limit > int(cfg["qiskit_max_qubits"]):
            qiskit_ref_info["reason"] = (
                f"Skipped: declared qubits ({declared_for_limit}) > "
                f"qiskit_max_qubits ({int(cfg['qiskit_max_qubits'])})."
            )
        else:
            try:
                qiskit_t0 = time.perf_counter()
                qiskit_pop, qinfo = _compute_qiskit_subset_pop(
                    circuit=circuit,
                    input_statevector_path=input_path_used,
                    output_bins=output_bins,
                )
                qiskit_runtime_s = float(time.perf_counter() - qiskit_t0)
                qiskit_ref_info["used"] = True
                qiskit_ref_info["reason"] = ""
                qiskit_ref_info["declared_qubits"] = int(qinfo["declared_qubits"])
                qiskit_ref_info["simulator_qubits"] = int(qinfo["simulator_qubits"])
            except ImportError as exc:
                qiskit_ref_info["reason"] = f"Skipped: Qiskit import failed ({exc})."
            except Exception as exc:
                qiskit_ref_info["reason"] = f"Qiskit reference failed: {exc}"

    abs_pop_err: np.ndarray | None = None
    max_abs_pop_err: float | None = None
    mean_abs_pop_err: float | None = None
    rmse_pop_err: float | None = None
    if qiskit_pop is not None:
        abs_pop_err = np.abs(output_pop - qiskit_pop)
        max_abs_pop_err = float(np.max(abs_pop_err)) if abs_pop_err.size else 0.0
        mean_abs_pop_err = float(np.mean(abs_pop_err)) if abs_pop_err.size else 0.0
        rmse_pop_err = float(np.sqrt(np.mean(abs_pop_err**2))) if abs_pop_err.size else 0.0

    pop_csv = sweep_dir / "output_population.csv"
    with pop_csv.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(
            [
                "ordinal",
                "bin_dec",
                "bin_hex",
                "amplitude_real",
                "amplitude_imag",
                "population",
                "qiskit_population",
                "abs_pop_error",
            ]
        )
        for i, b in enumerate(output_bins):
            a = feynman_amp[i]
            qp = "" if qiskit_pop is None else f"{qiskit_pop[i]:.18e}"
            ap = "" if abs_pop_err is None else f"{abs_pop_err[i]:.18e}"
            wr.writerow(
                [
                    i,
                    b,
                    f"0x{b:0{size_bytes * 2}X}",
                    f"{a.real:.18e}",
                    f"{a.imag:.18e}",
                    f"{output_pop[i]:.18e}",
                    qp,
                    ap,
                ]
            )

    top_k = min(10, len(output_bins))
    top_idx = np.argsort(output_pop)[::-1][:top_k]
    top_bins = [
        {
            "rank": int(rank + 1),
            "bin_dec": int(output_bins[i]),
            "bin_hex": f"0x{output_bins[i]:0{size_bytes * 2}X}",
            "population": float(output_pop[i]),
        }
        for rank, i in enumerate(top_idx)
    ]

    plot_pdf = sweep_dir / "demo_plot.pdf"
    signal = _signal_meta_from_input(
        input_generated=input_generated,
        input_cfg=cfg["input_statevector"],
        signal_fallback=cfg.get("signal", {}),
    )
    _render_demo_plot(
        out_pdf=plot_pdf,
        input_sparse=input_sparse,
        output_bins=output_bins,
        output_pop=output_pop,
        qiskit_pop=qiskit_pop,
        max_xticks=int(cfg["plot_max_xticks"]),
        label_fontsize=cfg["plot_label_fontsize"],
    )

    low_bucket_population = None
    high_bucket_population = None
    low_bucket_bin = None
    high_bucket_bin = None
    low_to_high_ratio = None
    if signal:
        if signal.get("f_low") is not None:
            f_low = int(signal["f_low"])
            for i, b in enumerate(output_bins):
                if b == f_low:
                    low_bucket_bin = int(b)
                    low_bucket_population = float(output_pop[i])
                    break
        if signal.get("f_high") is not None:
            f_high = int(signal["f_high"])
            for i, b in enumerate(output_bins):
                if b == f_high:
                    high_bucket_bin = int(b)
                    high_bucket_population = float(output_pop[i])
                    break
    if (
        low_bucket_population is not None
        and high_bucket_population is not None
        and high_bucket_population > 0.0
    ):
        low_to_high_ratio = float(low_bucket_population / high_bucket_population)

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
            "input_statevector": str(input_statevector),
            "input_statevector_used": str(input_path_used),
            "output_bitstrings": str(output_bitstrings),
            "run_dir": str(sweep_dir),
            "feynman_output": str(output_hsv),
            "normalized_input_hsv": str(input_path_used) if cfg["normalize_input"] else "",
            "output_population_csv": str(pop_csv),
            "plot_pdf": str(plot_pdf),
            "stdout_log": str(sweep_dir / "stdout.log"),
            "stderr_log": str(sweep_dir / "stderr.log"),
        },
        "generated_inputs": {
            "circuit": circuit_generated,
            "input_statevector": input_generated,
            "output_bitstrings": output_generated,
        },
        "signal_used_for_plot_and_buckets": signal,
        "subset_info": {
            "num_requested_outputs": len(output_bins),
            "size_bytes": size_bytes,
        },
        "qiskit_reference": qiskit_ref_info,
        "metrics": {
            "subset_population_sum": float(np.sum(output_pop)),
            "qiskit_subset_population_sum": float(np.nansum(qiskit_pop))
            if qiskit_pop is not None
            else None,
            "feynman_runtime_s": feynman_runtime_s,
            "qiskit_runtime_s": qiskit_runtime_s,
            "max_population": float(np.max(output_pop)) if output_pop.size else 0.0,
            "max_qiskit_population": float(np.nanmax(qiskit_pop))
            if qiskit_pop is not None and qiskit_pop.size
            else None,
            "max_abs_population_error": max_abs_pop_err,
            "mean_abs_population_error": mean_abs_pop_err,
            "rmse_population_error": rmse_pop_err,
            "input_norm2_before": input_norm2_before,
            "input_norm2_after": input_norm2_after,
            "low_bucket_bin": low_bucket_bin,
            "high_bucket_bin": high_bucket_bin,
            "low_bucket_population": low_bucket_population,
            "high_bucket_population": high_bucket_population,
            "qiskit_low_bucket_population": float(qiskit_pop[output_bins.index(low_bucket_bin)])
            if qiskit_pop is not None and low_bucket_bin is not None and low_bucket_bin in output_bins
            else None,
            "qiskit_high_bucket_population": float(qiskit_pop[output_bins.index(high_bucket_bin)])
            if qiskit_pop is not None and high_bucket_bin is not None and high_bucket_bin in output_bins
            else None,
            "low_to_high_population_ratio": low_to_high_ratio,
        },
        "top_bins_by_population": top_bins,
    }

    summary_path = sweep_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"Demo run directory: {sweep_dir}")
    print(f"Summary: {summary_path}")
    print(f"Subset population sum: {summary['metrics']['subset_population_sum']:.12f}")
    print(f"Feynman runtime (s): {summary['metrics']['feynman_runtime_s']:.6f}")
    if qiskit_ref_info["used"]:
        print(
            "Qiskit subset population sum: "
            f"{summary['metrics']['qiskit_subset_population_sum']:.12f}"
        )
        print(f"Qiskit runtime (s): {summary['metrics']['qiskit_runtime_s']:.6f}")
        print(
            "Population error |Feynman-Qiskit|: "
            f"max={summary['metrics']['max_abs_population_error']:.6e}, "
            f"mean={summary['metrics']['mean_abs_population_error']:.6e}, "
            f"rmse={summary['metrics']['rmse_population_error']:.6e}"
        )
    elif qiskit_ref_info["enabled"] and qiskit_ref_info["reason"]:
        print(f"Qiskit reference: {qiskit_ref_info['reason']}")
    if top_bins:
        top = top_bins[0]
        print(f"Top bin: {top['bin_hex']} with population {top['population']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

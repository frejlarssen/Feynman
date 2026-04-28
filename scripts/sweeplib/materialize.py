from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from generators.circuits.aa_iter_generator import (
    DEFAULT_OUTPUT_DIR as AA_DEFAULT_OUTPUT_DIR,
    generate_aa,
)
from generators.circuits.qaoa_maxcut_generator import (
    DEFAULT_OUTPUT_DIR as QAOA_MAXCUT_DEFAULT_OUTPUT_DIR,
    generate_qaoa_maxcut,
)
from generators.circuits.qft_generator import (
    DEFAULT_OUTPUT_DIR as QFT_DEFAULT_OUTPUT_DIR,
    generate_qft,
)
from generators.circuits.quantum_walk_generator import (
    DEFAULT_OUTPUT_DIR as QWALK_DEFAULT_OUTPUT_DIR,
    generate_qwalk,
)
from generators.hexstrings.hexstring_set_generator import (
    DEFAULT_OUTPUT_DIR as HEXSTR_DEFAULT_OUTPUT_DIR,
    write_one_interval,
    write_two_intervals,
)
from generators.statevectors.statevector_generator import (
    DEFAULT_OUTPUT_DIR as STATEVEC_DEFAULT_OUTPUT_DIR,
    write_ket0,
    write_two_freq,
    write_two_freq_n_qubits,
    write_two_tone_dense,
)


def resolve_path_like(value: str | Path, repo_root: Path) -> Path:
    path = Path(value)
    return path.resolve() if path.is_absolute() else (repo_root / path).resolve()


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
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return bool(value)


def _resolve_output_dir(spec: dict[str, Any], repo_root: Path, default_dir: Path) -> Path:
    out_dir_raw = spec.get("output_dir")
    if out_dir_raw is None:
        return default_dir.resolve()
    out_dir = Path(str(out_dir_raw))
    return out_dir.resolve() if out_dir.is_absolute() else (repo_root / out_dir).resolve()


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


def resolve_circuit_input(circuit_cfg: str | dict[str, Any], repo_root: Path) -> tuple[Path, dict[str, Any] | None]:
    if isinstance(circuit_cfg, str):
        return resolve_path_like(circuit_cfg, repo_root), None
    if not isinstance(circuit_cfg, dict):
        raise ValueError("circuit must be a path string or a generator object.")

    generator = str(circuit_cfg.get("generator", "qft")).strip().lower()
    if generator == "qft":
        n = _require_int(circuit_cfg, "n", "circuit")
        k = _require_int(circuit_cfg, "k", "circuit")
        out_dir = _resolve_output_dir(circuit_cfg, repo_root, QFT_DEFAULT_OUTPUT_DIR)
        path = generate_qft(n=n, k=k, out_dir=out_dir).resolve()
        return path, {"generator": generator, "n": n, "k": k, "output_dir": str(out_dir)}

    if generator in {"aa", "amplitude_amplification"}:
        n = _require_int(circuit_cfg, "n", "circuit")
        it = _require_int(circuit_cfg, "it", "circuit")
        mark = _require_int(circuit_cfg, "mark", "circuit")
        out_dir = _resolve_output_dir(circuit_cfg, repo_root, AA_DEFAULT_OUTPUT_DIR)
        path = generate_aa(n=n, it=it, mark=mark, out_dir=out_dir).resolve()
        return path, {
            "generator": generator,
            "n": n,
            "it": it,
            "mark": mark,
            "output_dir": str(out_dir),
        }

    if generator in {"qwalk", "quantum_walk"}:
        n = _require_int(circuit_cfg, "n", "circuit")
        it = _require_int(circuit_cfg, "it", "circuit")
        biased = _as_bool(circuit_cfg.get("biased", False))
        coin_angle = float(circuit_cfg.get("coin_angle", 1.0471975511965976))
        out_dir = _resolve_output_dir(circuit_cfg, repo_root, QWALK_DEFAULT_OUTPUT_DIR)
        path = generate_qwalk(n=n, it=it, out_dir=out_dir, biased=biased, coin_angle=coin_angle).resolve()
        return path, {
            "generator": generator,
            "n": n,
            "it": it,
            "biased": biased,
            "coin_angle": coin_angle,
            "output_dir": str(out_dir),
        }

    if generator in {"qaoa_maxcut", "qaoa"}:
        n = _require_int(circuit_cfg, "n", "circuit")
        p = _require_int(circuit_cfg, "p", "circuit")
        graph = str(circuit_cfg.get("graph", "ring"))
        out_dir = _resolve_output_dir(circuit_cfg, repo_root, QAOA_MAXCUT_DEFAULT_OUTPUT_DIR)
        edges = circuit_cfg.get("edges")
        edges_str = str(edges) if edges is not None else None
        gammas_raw = circuit_cfg.get("gammas")
        betas_raw = circuit_cfg.get("betas")
        gammas = [float(v) for v in gammas_raw] if isinstance(gammas_raw, list) else None
        betas = [float(v) for v in betas_raw] if isinstance(betas_raw, list) else None
        name_raw = circuit_cfg.get("name")
        name = str(name_raw) if name_raw is not None else None
        path = generate_qaoa_maxcut(
            n=n,
            p=p,
            out_dir=out_dir,
            graph=graph,
            edges_str=edges_str,
            gammas=gammas,
            betas=betas,
            name=name,
        ).resolve()
        return path, {
            "generator": generator,
            "n": n,
            "p": p,
            "graph": graph,
            "edges": edges_str,
            "gammas": gammas,
            "betas": betas,
            "name": name,
            "output_dir": str(out_dir),
        }

    raise ValueError(f"Unsupported circuit generator: {generator!r}")


def resolve_statevector_input(
    statevector_cfg: str | dict[str, Any], repo_root: Path
) -> tuple[Path, dict[str, Any] | None]:
    if isinstance(statevector_cfg, str):
        return resolve_path_like(statevector_cfg, repo_root), None
    if not isinstance(statevector_cfg, dict):
        raise ValueError("input_statevector must be a path string or a generator object.")

    generator = str(statevector_cfg.get("generator", "two_freq")).strip().lower()
    out_dir = _resolve_output_dir(statevector_cfg, repo_root, STATEVEC_DEFAULT_OUTPUT_DIR)

    if generator in {"two_freq", "amplitude_signal"}:
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

    if generator in {"two_tone", "two_tone_dense"}:
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


def resolve_output_bitstrings_input(
    output_cfg: str | dict[str, Any], repo_root: Path
) -> tuple[Path, dict[str, Any] | None]:
    if isinstance(output_cfg, str):
        return resolve_path_like(output_cfg, repo_root), None
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
        path = write_two_intervals(size=size, interval1=interval1, interval2=interval2, out_dir=out_dir).resolve()
        return path, {
            "generator": generator,
            "size": size,
            "interval1_count": len(interval1),
            "interval2_count": len(interval2),
            "output_dir": str(out_dir),
        }

    raise ValueError(f"Unsupported output_bitstrings generator: {generator!r}")

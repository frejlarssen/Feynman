from __future__ import annotations

import csv
import glob
import math
import random
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
from generators.circuits.google_rqc_generator import (
    DEFAULT_OUTPUT_DIR as GOOGLE_RQC_DEFAULT_OUTPUT_DIR,
    generate_google_rqc,
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
    write_explicit_values,
    write_random_uniform,
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


def _read_hs(path: Path) -> tuple[list[int], int]:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(lines) < 2:
        raise ValueError(f"Invalid .hs file (missing header): {path}")
    try:
        expected_count = int(lines[0], 10)
        size_bytes = int(lines[1], 10)
    except ValueError as exc:
        raise ValueError(f"Invalid .hs header in {path}") from exc
    values = [int(raw, 16) for raw in lines[2:]]
    if len(values) != expected_count:
        raise ValueError(
            f"Invalid .hs file {path}: header says {expected_count} values but found {len(values)}."
        )
    return values, size_bytes


def _write_hs(path: Path, *, values: list[int], size_bytes: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    nr_nibbles = size_bytes * 2
    with path.open("w", encoding="utf-8") as handle:
        handle.write(f"{len(values)}\n")
        handle.write(f"{size_bytes}\n")
        for value in values:
            handle.write(f"0x{value:0{nr_nibbles}X}\n")
    return path


def infer_size_bytes_for_qubits(n_qubits: int) -> int:
    if n_qubits <= 0:
        raise ValueError("n_qubits must be > 0")
    return max(1, math.ceil(int(n_qubits) / 8))


def _infer_qasm_qubits(path: Path) -> int | None:
    try:
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
    except OSError:
        return None
    return None


def infer_circuit_qubits(circuit_cfg: str | dict[str, Any], repo_root: Path) -> int | None:
    if isinstance(circuit_cfg, str):
        return _infer_qasm_qubits(resolve_path_like(circuit_cfg, repo_root))
    if not isinstance(circuit_cfg, dict):
        return None

    generator = str(circuit_cfg.get("generator", "")).strip().lower()
    if generator in {"google_rqc", "google_style_rqc", "rqc"}:
        rows_raw = circuit_cfg.get("rows")
        cols_raw = circuit_cfg.get("cols")
        if rows_raw is None or cols_raw is None:
            return None
        return int(rows_raw) * int(cols_raw)
    n_raw = circuit_cfg.get("n")
    return int(n_raw) if n_raw is not None else None


def normalize_statevector_spec(
    statevector_cfg: str | dict[str, Any],
    repo_root: Path,
    *,
    circuit_qubits: int | None = None,
) -> str | dict[str, Any]:
    if isinstance(statevector_cfg, str):
        return statevector_cfg
    if not isinstance(statevector_cfg, dict):
        raise ValueError("input_statevector must be a path string or a generator object.")

    cfg = dict(statevector_cfg)
    generator = str(cfg.get("generator", "two_freq")).strip().lower()
    if generator == "ket0":
        if all(cfg.get(key) is None for key in ("size", "n_qubits", "n")):
            if circuit_qubits is None:
                raise ValueError(
                    "input_statevector ket0 requires size/n_qubits or an inferable circuit width."
                )
            cfg["size"] = infer_size_bytes_for_qubits(circuit_qubits)
        return cfg

    if generator in {"two_freq", "amplitude_signal", "two_tone", "two_tone_dense"}:
        if all(cfg.get(key) is None for key in ("size", "n_qubits", "n")):
            if circuit_qubits is None:
                raise ValueError(
                    f"input_statevector {generator} requires size/n_qubits or an inferable circuit width."
                )
            cfg["n_qubits"] = int(circuit_qubits)
        return cfg

    return cfg


def normalize_output_bitstrings_spec(
    output_cfg: str | dict[str, Any],
    repo_root: Path,
    *,
    circuit_qubits: int | None = None,
) -> str | dict[str, Any]:
    if isinstance(output_cfg, str):
        return output_cfg
    if not isinstance(output_cfg, dict):
        raise ValueError("output_bitstrings must be a path string or a generator object.")

    cfg = dict(output_cfg)
    generator = str(cfg.get("generator", "one_interval")).strip().lower()
    if cfg.get("size") is None:
        if circuit_qubits is None:
            raise ValueError(
                f"output_bitstrings {generator} requires size or an inferable circuit width."
            )
        cfg["size"] = infer_size_bytes_for_qubits(circuit_qubits)

    if generator in {"random_uniform", "uniform_random", "random"}:
        if cfg.get("n_qubits") is None and cfg.get("active_qubits") is None and circuit_qubits is not None:
            cfg["n_qubits"] = int(circuit_qubits)
    return cfg


def normalize_generator_specs(
    circuit_cfg: str | dict[str, Any],
    statevector_cfg: str | dict[str, Any],
    output_cfg: str | dict[str, Any],
    repo_root: Path,
) -> tuple[str | dict[str, Any], str | dict[str, Any], str | dict[str, Any], int | None]:
    circuit_qubits = infer_circuit_qubits(circuit_cfg, repo_root)
    return (
        circuit_cfg,
        normalize_statevector_spec(statevector_cfg, repo_root, circuit_qubits=circuit_qubits),
        normalize_output_bitstrings_spec(output_cfg, repo_root, circuit_qubits=circuit_qubits),
        circuit_qubits,
    )


def _sanitize_identifier(value: str) -> str:
    out = []
    for ch in value.strip():
        if ch.isalnum() or ch in {"-", "_", "."}:
            out.append(ch)
        else:
            out.append("_")
    return "".join(out).strip("_") or "case"


def _number_token(value: Any) -> str:
    text = f"{float(value):.12g}" if isinstance(value, float) or isinstance(value, int) else str(value)
    return (
        text.replace("-", "m")
        .replace(".", "p")
        .replace("+", "")
        .replace("/", "_")
    )


def _normalize_output_ordering_spec(ordering_cfg: Any) -> dict[str, Any]:
    if ordering_cfg is None:
        return {"method": "contiguous", "label": "contiguous"}
    if isinstance(ordering_cfg, str):
        method = ordering_cfg.strip().lower()
        return {"method": method or "contiguous", "label": method or "contiguous"}
    if not isinstance(ordering_cfg, dict):
        raise ValueError("output_bitstrings.ordering must be a string or object.")

    method = str(ordering_cfg.get("method", "contiguous")).strip().lower() or "contiguous"
    normalized = dict(ordering_cfg)
    normalized["method"] = method
    if not str(normalized.get("label", "")).strip():
        normalized["label"] = method
    return normalized


def describe_output_ordering(output_cfg: Any) -> dict[str, str]:
    if not isinstance(output_cfg, dict):
        return {"method": "contiguous", "label": "contiguous"}

    ordering = _normalize_output_ordering_spec(output_cfg.get("ordering"))
    method = ordering["method"]
    if method in {"", "contiguous", "none"}:
        return {"method": "contiguous", "label": str(ordering.get("label", "contiguous"))}
    if method in {"shuffle", "random"}:
        seed = int(ordering.get("seed", 0))
        label = str(ordering.get("label", f"random_seed{seed}"))
        return {"method": "random", "label": label}
    if method in {"heavy_first", "runtime_desc"}:
        metric = str(ordering.get("value_column", "elapsed_seconds"))
        label = str(ordering.get("label", f"heavy_first_{metric}"))
        return {"method": "heavy_first", "label": label}
    if method in {"light_first", "runtime_asc"}:
        metric = str(ordering.get("value_column", "elapsed_seconds"))
        label = str(ordering.get("label", f"light_first_{metric}"))
        return {"method": "light_first", "label": label}
    if method == "sort_by_csv":
        descending = _as_bool(ordering.get("descending", True), default=True)
        metric = str(ordering.get("value_column", "elapsed_seconds"))
        direction = "desc" if descending else "asc"
        label = str(ordering.get("label", f"sort_{metric}_{direction}"))
        return {"method": f"sort_by_csv_{direction}", "label": label}
    raise ValueError(f"Unsupported output_bitstrings ordering method: {method!r}")


def _score_map_from_csv_files(
    csv_paths: list[Path],
    *,
    index_column: str,
    value_column: str,
) -> dict[int, float]:
    if not csv_paths:
        raise ValueError("No ordering CSV files were provided.")

    scores: dict[int, float] = {}
    for csv_path in csv_paths:
        with csv_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames is None:
                raise ValueError(f"Ordering CSV is missing a header row: {csv_path}")
            for row in reader:
                index_raw = (row.get(index_column) or "").strip()
                value_raw = (row.get(value_column) or "").strip()
                if not index_raw or not value_raw:
                    continue
                index = int(index_raw, 16) if index_raw.lower().startswith("0x") else int(index_raw, 10)
                if index in scores:
                    raise ValueError(
                        f"Duplicate ordering entry for bitstring 0x{index:X} across CSV files."
                    )
                scores[index] = float(value_raw)
    if not scores:
        joined = ", ".join(str(path) for path in csv_paths[:3])
        raise ValueError(f"No usable ordering rows found in CSV files starting with: {joined}")
    return scores


def _ordered_output_path(base_path: Path, ordering: dict[str, Any], suffix: str) -> Path:
    label = _sanitize_identifier(str(ordering.get("label", ordering["method"])))
    return base_path.with_name(f"{base_path.stem}__{label}_{suffix}.hs")


def _apply_output_ordering(
    path: Path,
    output_cfg: dict[str, Any],
    *,
    repo_root: Path,
) -> tuple[Path, dict[str, Any] | None]:
    ordering = _normalize_output_ordering_spec(output_cfg.get("ordering"))
    method = ordering["method"]
    described = describe_output_ordering(output_cfg)
    if method in {"", "contiguous", "none"}:
        return path, {
            "ordering_method": described["method"],
            "ordering_label": described["label"],
        }

    values, size_bytes = _read_hs(path)
    original_positions = {value: idx for idx, value in enumerate(values)}
    ordered_values = list(values)

    if method in {"shuffle", "random"}:
        random.Random(int(ordering.get("seed", 0))).shuffle(ordered_values)
        out_path = _ordered_output_path(path, ordering, "shuffle")
    elif method in {"heavy_first", "runtime_desc", "light_first", "runtime_asc", "sort_by_csv"}:
        csv_raw = ordering.get("csv") or ordering.get("csv_file") or ordering.get("ranking_csv")
        csv_glob_raw = ordering.get("csv_glob")
        if not csv_raw and not csv_glob_raw:
            raise ValueError(
                f"output_bitstrings.ordering method {method!r} requires csv=<path> or csv_glob=<glob>."
            )
        index_column = str(ordering.get("index_column", "bitstring_hex"))
        value_column = str(ordering.get("value_column", "elapsed_seconds"))
        descending = True
        if method in {"light_first", "runtime_asc"}:
            descending = False
        elif method == "sort_by_csv":
            descending = _as_bool(ordering.get("descending", True), default=True)
        csv_paths: list[Path] = []
        if csv_raw:
            csv_paths.append(resolve_path_like(str(csv_raw), repo_root))
        if csv_glob_raw:
            pattern = str(csv_glob_raw)
            csv_paths.extend(sorted(Path(match) for match in glob.glob(str((repo_root / pattern) if not Path(pattern).is_absolute() else pattern))))
        csv_paths = [path.resolve() for path in csv_paths]
        if not csv_paths:
            raise ValueError(
                f"output_bitstrings.ordering {method!r} found no CSV files for csv/csv_glob."
            )
        scores = _score_map_from_csv_files(
            csv_paths,
            index_column=index_column,
            value_column=value_column,
        )
        missing = [value for value in values if value not in scores]
        if missing:
            preview = ", ".join(f"0x{value:X}" for value in missing[:5])
            raise ValueError(
                f"Ordering CSV {csv_path} is missing {len(missing)} requested bitstrings "
                f"(for example {preview})."
            )
        ordered_values.sort(
            key=lambda value: (
                scores[value],
                -original_positions[value] if descending else original_positions[value],
            ),
            reverse=descending,
        )
        out_path = _ordered_output_path(path, ordering, "ordered")
    else:
        raise ValueError(f"Unsupported output_bitstrings ordering method: {method!r}")

    _write_hs(out_path, values=ordered_values, size_bytes=size_bytes)
    return out_path.resolve(), {
        "ordering_method": described["method"],
        "ordering_label": described["label"],
        "ordering_output_file": str(out_path.resolve()),
    }


def derive_circuit_identifier(circuit_cfg: str | dict[str, Any], repo_root: Path) -> str:
    if isinstance(circuit_cfg, str):
        return _sanitize_identifier(resolve_path_like(circuit_cfg, repo_root).stem)
    if not isinstance(circuit_cfg, dict):
        return "circuit"

    generator = str(circuit_cfg.get("generator", "circuit")).strip().lower()
    if generator == "qft":
        return f"qft_n{int(circuit_cfg['n'])}_k{int(circuit_cfg['k'])}"
    if generator in {"qwalk", "quantum_walk"}:
        suffix = "_biased" if _as_bool(circuit_cfg.get("biased", False)) else ""
        return f"qwalk_n{int(circuit_cfg['n'])}_it{int(circuit_cfg['it'])}{suffix}"
    if generator in {"aa", "amplitude_amplification"}:
        return (
            f"aa_n{int(circuit_cfg['n'])}_it{int(circuit_cfg['it'])}_mark{int(circuit_cfg['mark'])}"
        )
    if generator in {"google_rqc", "google_style_rqc", "rqc"}:
        if circuit_cfg.get("name"):
            return _sanitize_identifier(str(circuit_cfg["name"]))
        token = (
            f"google_rqc_r{int(circuit_cfg['rows'])}_c{int(circuit_cfg['cols'])}"
            f"_m{int(circuit_cfg['cycles'])}"
        )
        seed = int(circuit_cfg.get("seed", 0))
        if seed != 0:
            token += f"_seed{seed}"
        variant = str(circuit_cfg.get("variant", "sycamore")).strip().lower()
        if variant and variant != "sycamore":
            token += f"_{_sanitize_identifier(variant)}"
        return token
    if generator in {"qaoa_maxcut", "qaoa"}:
        if circuit_cfg.get("name"):
            return _sanitize_identifier(str(circuit_cfg["name"]))
        graph = _sanitize_identifier(str(circuit_cfg.get("graph", "graph")))
        return f"qaoa_{graph}_n{int(circuit_cfg['n'])}_p{int(circuit_cfg['p'])}"
    return _sanitize_identifier(generator)


def _interval_descriptor(interval_spec: Any) -> str:
    if isinstance(interval_spec, dict):
        if "start" in interval_spec and "count" in interval_spec:
            return f"from{int(interval_spec['start'])}_count{int(interval_spec['count'])}"
        if "start" in interval_spec and "end" in interval_spec:
            return f"from{int(interval_spec['start'])}_to{int(interval_spec['end'])}"
        if "center" in interval_spec and "radius" in interval_spec:
            return f"center{int(interval_spec['center'])}_rad{int(interval_spec['radius'])}"
        if "values" in interval_spec:
            values = list(interval_spec["values"])
            return f"values{len(values)}"
    if isinstance(interval_spec, list):
        return f"values{len(interval_spec)}"
    return "interval"


def derive_statevector_identifier(
    statevector_cfg: str | dict[str, Any],
    repo_root: Path,
    *,
    circuit_qubits: int | None = None,
) -> str:
    if isinstance(statevector_cfg, str):
        return _sanitize_identifier(resolve_path_like(statevector_cfg, repo_root).stem)
    cfg = normalize_statevector_spec(statevector_cfg, repo_root, circuit_qubits=circuit_qubits)
    assert isinstance(cfg, dict)
    generator = str(cfg.get("generator", "")).strip().lower()
    if generator == "ket0":
        return ""
    if generator in {"two_freq", "amplitude_signal"}:
        return f"twofreq_f{int(cfg['f1'])}_f{_number_token(cfg['f2'])}"
    if generator in {"two_tone", "two_tone_dense"}:
        return f"twotone_f{int(cfg['f1'])}_{int(cfg['f2'])}"
    return _sanitize_identifier(generator)


def derive_output_identifier(
    output_cfg: str | dict[str, Any],
    repo_root: Path,
    *,
    circuit_qubits: int | None = None,
) -> str:
    if isinstance(output_cfg, str):
        return _sanitize_identifier(resolve_path_like(output_cfg, repo_root).stem)
    cfg = normalize_output_bitstrings_spec(output_cfg, repo_root, circuit_qubits=circuit_qubits)
    assert isinstance(cfg, dict)
    generator = str(cfg.get("generator", "outputs")).strip().lower()
    if generator == "one_interval":
        token = f"count{int(cfg['count'])}"
        start = int(cfg.get("start", 0))
        if start != 0:
            token += f"_from{start}"
        return token
    if generator in {"random_uniform", "uniform_random", "random"}:
        token = f"count{int(cfg['count'])}_seed{int(cfg.get('seed', 0))}"
        n_qubits = cfg.get("n_qubits", cfg.get("active_qubits"))
        if n_qubits is not None and circuit_qubits is not None and int(n_qubits) != int(circuit_qubits):
            token += f"_nq{int(n_qubits)}"
        return token
    if generator == "two_intervals":
        return (
            f"twointervals_{_interval_descriptor(cfg.get('interval1'))}_"
            f"{_interval_descriptor(cfg.get('interval2'))}"
        )
    if generator in {"explicit", "values"}:
        values = cfg.get("values")
        if isinstance(values, list):
            return f"explicit{len(values)}"
        return f"explicit{int(cfg.get('count', 0))}"
    return _sanitize_identifier(generator)


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


def _build_values(values_spec: Any, label: str) -> list[int]:
    if not isinstance(values_spec, list):
        raise ValueError(f"{label} must be an array of integers or integer-like strings.")
    values = [int(v, 0) if isinstance(v, str) else int(v) for v in values_spec]
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

    if generator in {"google_rqc", "google_style_rqc", "rqc"}:
        rows = _require_int(circuit_cfg, "rows", "circuit")
        cols = _require_int(circuit_cfg, "cols", "circuit")
        cycles = _require_int(circuit_cfg, "cycles", "circuit")
        seed = int(circuit_cfg.get("seed", 0))
        variant = str(circuit_cfg.get("variant", "sycamore"))
        name_raw = circuit_cfg.get("name")
        name = str(name_raw) if name_raw is not None else None
        out_dir = _resolve_output_dir(circuit_cfg, repo_root, GOOGLE_RQC_DEFAULT_OUTPUT_DIR)
        path = generate_google_rqc(
            rows=rows,
            cols=cols,
            cycles=cycles,
            seed=seed,
            out_dir=out_dir,
            variant=variant,
            name=name,
        ).resolve()
        return path, {
            "generator": generator,
            "rows": rows,
            "cols": cols,
            "cycles": cycles,
            "seed": seed,
            "variant": variant,
            "name": name,
            "n": rows * cols,
            "output_dir": str(out_dir),
        }

    raise ValueError(f"Unsupported circuit generator: {generator!r}")


def resolve_statevector_input(
    statevector_cfg: str | dict[str, Any],
    repo_root: Path,
    *,
    circuit_qubits: int | None = None,
) -> tuple[Path, dict[str, Any] | None]:
    statevector_cfg = normalize_statevector_spec(
        statevector_cfg,
        repo_root,
        circuit_qubits=circuit_qubits,
    )
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
    output_cfg: str | dict[str, Any],
    repo_root: Path,
    *,
    circuit_qubits: int | None = None,
) -> tuple[Path, dict[str, Any] | None]:
    output_cfg = normalize_output_bitstrings_spec(
        output_cfg,
        repo_root,
        circuit_qubits=circuit_qubits,
    )
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
        if start < 0:
            raise ValueError("output_bitstrings one_interval requires start >= 0.")
        path = write_one_interval(size=size, nr_hexstrings=count, out_dir=out_dir, start=start).resolve()
        ordered_path, ordering_meta = _apply_output_ordering(path, output_cfg, repo_root=repo_root)
        meta = {
            "generator": generator,
            "size": size,
            "start": start,
            "count": count,
            "output_dir": str(out_dir),
        }
        if ordering_meta:
            meta.update(ordering_meta)
        return ordered_path, meta

    if generator == "two_intervals":
        size = _require_int(output_cfg, "size", "output_bitstrings")
        interval1 = _build_interval(output_cfg.get("interval1"), "output_bitstrings.interval1")
        interval2 = _build_interval(output_cfg.get("interval2"), "output_bitstrings.interval2")
        path = write_two_intervals(size=size, interval1=interval1, interval2=interval2, out_dir=out_dir).resolve()
        ordered_path, ordering_meta = _apply_output_ordering(path, output_cfg, repo_root=repo_root)
        meta = {
            "generator": generator,
            "size": size,
            "interval1_count": len(interval1),
            "interval2_count": len(interval2),
            "output_dir": str(out_dir),
        }
        if ordering_meta:
            meta.update(ordering_meta)
        return ordered_path, meta

    if generator in {"random_uniform", "uniform_random", "random"}:
        size = _require_int(output_cfg, "size", "output_bitstrings")
        count = int(output_cfg.get("count", output_cfg.get("nr_hexstrings", 0)))
        seed = int(output_cfg.get("seed", 0))
        n_qubits_raw = output_cfg.get("n_qubits", output_cfg.get("active_qubits"))
        n_qubits = None if n_qubits_raw is None else int(n_qubits_raw)
        if count <= 0:
            raise ValueError("output_bitstrings random_uniform requires count > 0.")
        path = write_random_uniform(
            size=size,
            nr_hexstrings=count,
            seed=seed,
            out_dir=out_dir,
            n_qubits=n_qubits,
        ).resolve()
        ordered_path, ordering_meta = _apply_output_ordering(path, output_cfg, repo_root=repo_root)
        meta = {
            "generator": generator,
            "size": size,
            "count": count,
            "seed": seed,
            "n_qubits": n_qubits,
            "output_dir": str(out_dir),
        }
        if ordering_meta:
            meta.update(ordering_meta)
        return ordered_path, meta

    if generator in {"explicit", "values"}:
        size = _require_int(output_cfg, "size", "output_bitstrings")
        values = _build_values(output_cfg.get("values"), "output_bitstrings.values")
        path = write_explicit_values(size=size, values=values, out_dir=out_dir).resolve()
        ordered_path, ordering_meta = _apply_output_ordering(path, output_cfg, repo_root=repo_root)
        meta = {
            "generator": generator,
            "size": size,
            "count": len(values),
            "output_dir": str(out_dir),
        }
        if ordering_meta:
            meta.update(ordering_meta)
        return ordered_path, meta

    raise ValueError(f"Unsupported output_bitstrings generator: {generator!r}")

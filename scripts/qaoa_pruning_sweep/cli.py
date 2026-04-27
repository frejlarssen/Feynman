from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from .schema import (
    BOOLEAN_FIELDS,
    DEFAULT_OPTIONS,
    NUMERIC_CASTS,
    OVERRIDE_FIELDS,
    REQUIRED_FIELDS,
    SweepConfig,
)


def _to_bool(name: str, value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    raise ValueError(f"Invalid boolean for '{name}': {value!r}")


def _to_number(name: str, value: Any, conv: Callable[[Any], Any]) -> Any:
    if value is None:
        return None
    try:
        return conv(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid numeric value for '{name}': {value!r}") from exc


def _contains_threshold(values: list[float], target: float) -> bool:
    for v in values:
        tol = max(1e-15, 1e-12 * max(1.0, abs(v), abs(target)))
        if abs(v - target) <= tol:
            return True
    return False


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Config file must contain a JSON object at top level.")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run QAOA pruning threshold sweeps (sweeplib runner) and report time/fidelity "
            "against a threshold reference (default t=0)."
        )
    )
    parser.add_argument("--config", default=argparse.SUPPRESS)
    parser.add_argument("--experiment-name", default=argparse.SUPPRESS)
    parser.add_argument("--repo-root", default=argparse.SUPPRESS)
    parser.add_argument("--output-root", default=argparse.SUPPRESS)
    parser.add_argument("--base-config", default=argparse.SUPPRESS)
    parser.add_argument("--thresholds", nargs="+", default=argparse.SUPPRESS)
    parser.add_argument("--reference-threshold", type=float, default=argparse.SUPPRESS)
    parser.add_argument("--repeat", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--continue-on-error", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--timeout-seconds", type=float, default=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--notes", default=argparse.SUPPRESS)
    parser.add_argument(
        "--max-cases",
        type=int,
        default=argparse.SUPPRESS,
        help="Optional cap on threshold points (for smoke tests).",
    )

    parser.add_argument("--binary", default=argparse.SUPPRESS)
    parser.add_argument("--mpirun", default=argparse.SUPPRESS)
    parser.add_argument("--ranks", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--circuit", default=argparse.SUPPRESS)
    parser.add_argument("--input-statevector", default=argparse.SUPPRESS)
    parser.add_argument("--output-bitstrings", default=argparse.SUPPRESS)
    parser.add_argument("--fraction", type=float, default=argparse.SUPPRESS)
    parser.add_argument("--batch-size", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--verbosity", type=int, default=argparse.SUPPRESS)
    return parser


def _merge_config(cli_options: dict[str, Any]) -> dict[str, Any]:
    merged = dict(DEFAULT_OPTIONS)
    config_path_raw = cli_options.pop("config", None)

    if config_path_raw:
        config_path = Path(config_path_raw).expanduser().resolve()
        config_data = _load_json_object(config_path)

        allowed = set(DEFAULT_OPTIONS)
        unknown = sorted(set(config_data) - allowed)
        if unknown:
            raise ValueError(
                "Unknown keys in config file: "
                + ", ".join(unknown)
                + f". Allowed keys: {', '.join(sorted(allowed))}"
            )
        merged.update(config_data)
        merged["config"] = str(config_path)

    merged.update(cli_options)
    return merged


def _normalize_options(options: dict[str, Any]) -> None:
    for field, conv in NUMERIC_CASTS.items():
        options[field] = _to_number(field, options.get(field), conv)
    for field in BOOLEAN_FIELDS:
        options[field] = _to_bool(field, options.get(field))

    thresholds_raw = options.get("thresholds")
    if thresholds_raw is None:
        return
    if isinstance(thresholds_raw, str) or not isinstance(thresholds_raw, list):
        raise ValueError(f"'thresholds' must be a list, got: {thresholds_raw!r}")
    options["thresholds"] = [float(v) for v in thresholds_raw]


def _validate_required(options: dict[str, Any]) -> None:
    missing: list[str] = []
    for field in REQUIRED_FIELDS:
        value = options.get(field)
        if value is None or value == "":
            missing.append(field)
    if missing:
        raise ValueError(
            "Missing required sweep arguments: "
            + ", ".join(missing)
            + ". Use CLI flags or provide them in --config JSON."
        )


def _normalize_threshold_order(options: dict[str, Any]) -> None:
    thresholds = options["thresholds"]
    if len(thresholds) == 0:
        raise ValueError("'thresholds' must contain at least one value.")

    reference = float(options["reference_threshold"])
    if not _contains_threshold(thresholds, reference):
        thresholds = [reference, *thresholds]

    ordered: list[float] = []
    for t in thresholds:
        if _contains_threshold(ordered, float(t)):
            continue
        ordered.append(float(t))

    ref_values = [t for t in ordered if _contains_threshold([t], reference)]
    non_ref = [t for t in ordered if not _contains_threshold([t], reference)]
    options["thresholds"] = [*ref_values, *non_ref]


def _validate_semantics(options: dict[str, Any]) -> None:
    if int(options["repeat"]) < 1:
        raise ValueError("--repeat must be >= 1")
    max_cases = options.get("max_cases")
    if max_cases is not None and int(max_cases) < 1:
        raise ValueError("--max-cases must be >= 1 when provided")

    for key in ("ranks", "batch_size", "verbosity"):
        if options.get(key) is not None and int(options[key]) < 0:
            raise ValueError(f"--{key.replace('_', '-')} must be >= 0")

    for key in OVERRIDE_FIELDS:
        if key in ("ranks", "batch_size", "verbosity") and options.get(key) == 0 and key != "batch_size":
            raise ValueError(f"--{key.replace('_', '-')} must be >= 1")


def _finalize_thresholds(options: dict[str, Any]) -> None:
    _normalize_threshold_order(options)
    max_cases = options.get("max_cases")
    if max_cases is not None:
        options["thresholds"] = options["thresholds"][: int(max_cases)]
    if len(options["thresholds"]) == 0:
        raise ValueError("No thresholds left after applying --max-cases.")


def build_config() -> SweepConfig:
    parser = build_parser()
    try:
        options = _merge_config(vars(parser.parse_args()))
        _normalize_options(options)
        _validate_required(options)
        _validate_semantics(options)
        _finalize_thresholds(options)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    return SweepConfig(**options)

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Callable

from .schema import (
    BOOLEAN_FIELDS,
    DEFAULT_OPTIONS,
    FLOAT_SWEEP_PARAMS,
    NUMERIC_CASTS,
    REQUIRED_FIELDS,
    VARY_CHOICES,
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


def _load_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"Config file does not exist: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Config file must contain a JSON object at top level.")
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sweep one parameter for sv_prefetcher and store results with metadata."
    )
    parser.add_argument("--config", default=argparse.SUPPRESS)
    parser.add_argument("--experiment-name", default=argparse.SUPPRESS)
    parser.add_argument("--vary", choices=VARY_CHOICES, default=argparse.SUPPRESS)
    parser.add_argument("--values", nargs="+", default=argparse.SUPPRESS)

    parser.add_argument("--repeat", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--binary", default=argparse.SUPPRESS)
    parser.add_argument("--mpirun", default=argparse.SUPPRESS)
    parser.add_argument("--circuit", default=argparse.SUPPRESS)
    parser.add_argument("--input-statevector", default=argparse.SUPPRESS)
    parser.add_argument("--output-bitstrings", default=argparse.SUPPRESS)
    parser.add_argument("--output-root", default=argparse.SUPPRESS)

    parser.add_argument("--ranks", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--batch-size", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--fraction", type=float, default=argparse.SUPPRESS)
    parser.add_argument("--threshold", type=float, default=argparse.SUPPRESS)
    parser.add_argument("--p", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--r", type=int, default=argparse.SUPPRESS)
    parser.add_argument("--verbosity", type=int, default=argparse.SUPPRESS)

    parser.add_argument("--dense", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--timeout-seconds", type=float, default=argparse.SUPPRESS)
    parser.add_argument("--continue-on-error", action="store_true", default=argparse.SUPPRESS)
    parser.add_argument("--notes", default=argparse.SUPPRESS)
    parser.add_argument("--dry-run", action="store_true", default=argparse.SUPPRESS)
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

    values = options.get("values")
    if isinstance(values, str) or (values is not None and not isinstance(values, list)):
        raise ValueError(f"'values' must be a list, got: {values!r}")


def _validate_required(options: dict[str, Any]) -> None:
    missing: list[str] = []
    for field in REQUIRED_FIELDS:
        value = options.get(field)
        if value is None or value == "":
            missing.append(field)
        elif field == "values" and len(value) == 0:
            missing.append(field)
    if missing:
        raise ValueError(
            "Missing required sweep arguments: "
            + ", ".join(missing)
            + ". Use CLI flags or provide them in --config JSON."
        )


def _validate_semantics(options: dict[str, Any]) -> None:
    if options["vary"] not in VARY_CHOICES:
        raise ValueError(
            f"Invalid vary parameter: {options['vary']!r}. Must be one of {VARY_CHOICES}."
        )
    if int(options["repeat"]) < 1:
        raise ValueError("--repeat must be >= 1")
    if int(options["ranks"]) < 1:
        raise ValueError("--ranks must be >= 1")
    if int(options["batch_size"]) < 0:
        raise ValueError("--batch-size must be >= 0")
    if (options["p"] is None) ^ (options["r"] is None):
        raise ValueError("Provide both --p and --r, or neither.")
    if options["vary"] == "p" and options["r"] is None:
        raise ValueError("Sweeping --vary p requires fixed --r.")
    if options["vary"] == "r" and options["p"] is None:
        raise ValueError("Sweeping --vary r requires fixed --p.")


def _parse_values(options: dict[str, Any]) -> None:
    conv = float if options["vary"] in FLOAT_SWEEP_PARAMS else int
    options["values"] = [_to_number("values", value, conv) for value in options["values"]]


def build_config() -> SweepConfig:
    parser = build_parser()
    try:
        options = _merge_config(vars(parser.parse_args()))
        _normalize_options(options)
        _validate_required(options)
        _validate_semantics(options)
        _parse_values(options)
    except (FileNotFoundError, json.JSONDecodeError, ValueError) as exc:
        parser.error(str(exc))

    return SweepConfig(**options)

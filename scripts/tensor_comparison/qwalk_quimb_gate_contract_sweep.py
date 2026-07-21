#!/usr/bin/env python
"""Run qwalk-quimb sweeps for several quimb gate contraction modes."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(SCRIPT_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_REPO_ROOT))


DEFAULT_CONTRACT_VALUES: tuple[Any, ...] = (
    False,
    True,
    "split",
    "reduce-split",
    "split-gate",
    "swap-split-gate",
    "auto-split-gate",
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
    return "".join(out) or "value"


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Config must be a JSON object: {path}")
    return payload


def _parse_contract_value(raw: str) -> Any:
    lowered = raw.lower()
    if lowered == "false":
        return False
    if lowered == "true":
        return True
    return raw


def _contract_label(value: Any) -> str:
    if value is False:
        return "false"
    if value is True:
        return "true"
    return _sanitize(str(value))


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Base qwalk-quimb-sweep config JSON.")
    parser.add_argument("--repo-root", type=Path, default=Path("."), help="Repository root.")
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
        help="Outer output directory. Defaults to the base config output_root.",
    )
    parser.add_argument(
        "--contract-values",
        nargs="*",
        default=None,
        help="Values to test. Defaults to all documented quimb contract modes.",
    )
    parser.add_argument("--continue-on-error", action="store_true", help="Run remaining modes after a failed child sweep.")
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    repo_root = args.repo_root.resolve()
    base_config_path = args.config.resolve()
    base_config = _load_json(base_config_path)
    values = (
        [_parse_contract_value(value) for value in args.contract_values]
        if args.contract_values is not None
        else list(DEFAULT_CONTRACT_VALUES)
    )

    base_experiment_name = str(base_config.get("experiment_name", "qwalk_quimb_qubit_sweep"))
    base_output_root = args.output_root or Path(base_config.get("output_root", "data/outputs/experiments"))
    if not base_output_root.is_absolute():
        base_output_root = repo_root / base_output_root
    outer_dir = base_output_root / f"{_utc_stamp()}_{_sanitize(base_experiment_name)}_gate_contract"
    configs_dir = outer_dir / "configs"
    configs_dir.mkdir(parents=True, exist_ok=False)

    manifest = {
        "created_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "base_config": str(base_config_path),
        "contract_values": values,
        "runs": [],
    }
    returncode = 0
    print(f"[qwalk-quimb-gate-contract-sweep] output: {outer_dir}", flush=True)
    for value in values:
        label = _contract_label(value)
        config = json.loads(json.dumps(base_config))
        config["experiment_name"] = f"{base_experiment_name}_contract_{label}"
        config["output_root"] = str(outer_dir)
        validation = dict(config.get("validation", {}))
        validation["quimb_gate_contract"] = value
        config["validation"] = validation
        child_config_path = configs_dir / f"{label}.json"
        child_config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        cmd = [
            sys.executable,
            str(repo_root / "scripts" / "run_pipeline.py"),
            "qwalk-quimb-sweep",
            "--config",
            str(child_config_path),
        ]
        if args.dry_run:
            cmd.append("--dry-run")
        print(
            f"[qwalk-quimb-gate-contract-sweep] contract={value!r}: {' '.join(cmd)}",
            flush=True,
        )
        manifest["runs"].append(
            {
                "quimb_gate_contract": value,
                "label": label,
                "config": str(child_config_path),
                "command": cmd,
            }
        )
        completed = subprocess.run(cmd, cwd=repo_root)
        manifest["runs"][-1]["returncode"] = completed.returncode
        (outer_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        if completed.returncode != 0:
            returncode = completed.returncode
            if not args.continue_on_error:
                break

    print(f"Gate-contract sweep directory: {outer_dir}")
    print(f"Manifest: {outer_dir / 'manifest.json'}")
    return returncode


if __name__ == "__main__":
    raise SystemExit(main())

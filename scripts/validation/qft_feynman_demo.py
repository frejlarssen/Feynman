#!/usr/bin/env python3
"""Feynman-only QFT frequency demo (no Qiskit reference).

Runs sv_prefetcher on a provided signal/statevector and plots:
1) Input signal real part over the sparse support.
2) Output populations for requested output bitstrings.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import math
import shlex
import subprocess
from pathlib import Path
from typing import Any

import numpy as np


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
        "signal": cfg.get("signal", {}),
    }

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


def _read_hsv_sparse(path: Path) -> dict[int, complex]:
    out: dict[int, complex] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line:
            continue
        idx_s, amp_s = line.split(":", 1)
        out[int(idx_s, 16)] = _parse_complex_token(amp_s)
    return out


def _read_population_csv(path: Path) -> tuple[list[int], np.ndarray]:
    bins: list[int] = []
    pop: list[float] = []
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
    return bins, np.array(pop, dtype=np.float64)


def _write_hsv_sparse(path: Path, sparse: dict[int, complex], size_bytes: int) -> None:
    width = size_bytes * 2
    with path.open("w", encoding="utf-8") as fh:
        for idx in sorted(sparse):
            amp = sparse[idx]
            fh.write(f"0x{idx:0{width}X}:{amp.real:.18f}+{amp.imag:.18f}i\n")


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
    title: str,
    max_xticks: int = 24,
) -> None:
    out_pdf.parent.mkdir(parents=True, exist_ok=True)
    import os

    os.environ.setdefault("MPLCONFIGDIR", str(out_pdf.parent / ".mplconfig"))
    os.environ.setdefault("XDG_CACHE_HOME", str(out_pdf.parent / ".cache"))

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # Left panel: sparse input real part.
    in_idx = np.array(sorted(input_sparse.keys()), dtype=np.int64)
    in_real = np.array([input_sparse[i].real for i in in_idx], dtype=np.float64)

    # Right panel: requested output populations.
    x_out = np.arange(len(output_bins))
    hex_labels = [f"0x{b:X}" for b in output_bins]

    fig, axes = plt.subplots(1, 2, figsize=(13, 4.8))

    axes[0].plot(in_idx, in_real, linewidth=1.0)
    axes[0].set_title("Input Signal (Real Part, Sparse Support)")
    axes[0].set_xlabel("Basis Index")
    axes[0].set_ylabel("Amplitude")
    axes[0].grid(True, axis="y", alpha=0.25)

    axes[1].bar(x_out, output_pop, alpha=0.9)
    axes[1].set_title("Output Population (Requested Bitstrings)")
    axes[1].set_xlabel("Output Bitstring")
    axes[1].set_ylabel(r"$|amp|^2$")
    if len(output_bins) <= max_xticks:
        tick_idx = list(range(len(output_bins)))
    else:
        step = max(1, math.ceil(len(output_bins) / max_xticks))
        tick_idx = list(range(0, len(output_bins), step))
        if tick_idx[-1] != len(output_bins) - 1:
            tick_idx.append(len(output_bins) - 1)
    axes[1].set_xticks(tick_idx, [hex_labels[i] for i in tick_idx], rotation=50, ha="right")
    axes[1].grid(True, axis="y", alpha=0.25)

    fig.suptitle(title)
    fig.tight_layout()
    fig.savefig(out_pdf)
    plt.close(fig)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a Feynman-only QFT frequency demo and produce a PDF plot."
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
        input_statevector_cfg: str | None = cfg["input_statevector"]
        plot_title: str | None = cfg["plot_title"]

        if population_csv is None and isinstance(summary.get("paths"), dict):
            population_csv = summary["paths"].get("output_population_csv")
        if input_statevector_cfg is None and isinstance(summary.get("paths"), dict):
            input_statevector_cfg = summary["paths"].get("input_statevector_used") or summary["paths"].get(
                "input_statevector"
            )
        if plot_title is None:
            exp = summary.get("experiment_name")
            plot_title = f"{exp} (from CSV)" if exp else "Feynman QFT Frequency Demo (from CSV)"

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

        output_bins, output_pop = _read_population_csv(population_csv_path)
        input_sparse = _read_hsv_sparse(input_statevector_plot)
        if not input_sparse:
            raise ValueError(f"Input statevector has no amplitudes: {input_statevector_plot}")

        _render_demo_plot(
            out_pdf=plot_pdf,
            input_sparse=input_sparse,
            output_bins=output_bins,
            output_pop=output_pop,
            title=plot_title,
            max_xticks=int(cfg["plot_max_xticks"]),
        )

        print(f"Plot written: {plot_pdf}")
        print(f"Population CSV: {population_csv_path}")
        return 0

    binary = (repo_root / cfg["binary"]).resolve()
    circuit = (repo_root / cfg["circuit"]).resolve()
    input_statevector = (repo_root / cfg["input_statevector"]).resolve()
    output_bitstrings = (repo_root / cfg["output_bitstrings"]).resolve()
    output_root = (repo_root / cfg["output_root"]).resolve()

    for p in (binary, circuit, input_statevector, output_bitstrings):
        if not p.exists():
            raise FileNotFoundError(f"Required path not found: {p}")

    sweep_dir = output_root / f"{_utc_stamp()}_{_sanitize(cfg['experiment_name'])}"
    sweep_dir.mkdir(parents=True, exist_ok=False)

    output_bins, size_bytes = _read_output_bitstrings(output_bitstrings)

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
    (sweep_dir / "stdout.log").write_text(stdout_text, encoding="utf-8")
    (sweep_dir / "stderr.log").write_text(stderr_text, encoding="utf-8")
    (sweep_dir / "command.txt").write_text(shlex.join(cmd) + "\n", encoding="utf-8")
    if rc != 0:
        raise RuntimeError(
            f"sv_prefetcher failed with return code {rc}. See {sweep_dir / 'stderr.log'}"
        )

    feynman_sparse = _read_hsv_sparse(output_hsv)

    feynman_amp = np.array(
        [feynman_sparse.get(b, 0.0 + 0.0j) for b in output_bins], dtype=np.complex128
    )
    output_pop = np.abs(feynman_amp) ** 2

    pop_csv = sweep_dir / "output_population.csv"
    with pop_csv.open("w", newline="", encoding="utf-8") as fh:
        wr = csv.writer(fh)
        wr.writerow(["ordinal", "bin_dec", "bin_hex", "amplitude_real", "amplitude_imag", "population"])
        for i, b in enumerate(output_bins):
            a = feynman_amp[i]
            wr.writerow(
                [
                    i,
                    b,
                    f"0x{b:0{size_bytes * 2}X}",
                    f"{a.real:.18e}",
                    f"{a.imag:.18e}",
                    f"{output_pop[i]:.18e}",
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
    signal = cfg.get("signal", {})
    signal_str = ""
    if isinstance(signal, dict) and signal:
        low = signal.get("f_low")
        high = signal.get("f_high")
        rel = signal.get("relative_amp")
        signal_str = f" (f_low={low}, f_high={high}, rel_amp={rel})"
    _render_demo_plot(
        out_pdf=plot_pdf,
        input_sparse=input_sparse,
        output_bins=output_bins,
        output_pop=output_pop,
        title="Feynman QFT Frequency Demo" + signal_str,
        max_xticks=int(cfg["plot_max_xticks"]),
    )

    low_bucket_population = None
    high_bucket_population = None
    low_bucket_bin = None
    high_bucket_bin = None
    low_to_high_ratio = None
    if isinstance(signal, dict):
        if "f_low" in signal:
            f_low = int(signal["f_low"])
            for i, b in enumerate(output_bins):
                if b == f_low:
                    low_bucket_bin = int(b)
                    low_bucket_population = float(output_pop[i])
                    break
        if "f_high" in signal:
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
        "subset_info": {
            "num_requested_outputs": len(output_bins),
            "size_bytes": size_bytes,
        },
        "metrics": {
            "subset_population_sum": float(np.sum(output_pop)),
            "max_population": float(np.max(output_pop)) if output_pop.size else 0.0,
            "input_norm2_before": input_norm2_before,
            "input_norm2_after": input_norm2_after,
            "low_bucket_bin": low_bucket_bin,
            "high_bucket_bin": high_bucket_bin,
            "low_bucket_population": low_bucket_population,
            "high_bucket_population": high_bucket_population,
            "low_to_high_population_ratio": low_to_high_ratio,
        },
        "top_bins_by_population": top_bins,
    }

    summary_path = sweep_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")

    print(f"Demo run directory: {sweep_dir}")
    print(f"Summary: {summary_path}")
    print(f"Subset population sum: {summary['metrics']['subset_population_sum']:.12f}")
    if top_bins:
        top = top_bins[0]
        print(f"Top bin: {top['bin_hex']} with population {top['population']:.6f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

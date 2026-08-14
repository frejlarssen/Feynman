#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scripts.sweeplib.plot_style import (  # noqa: E402
    LINE_COLOR_PRIMARY,
    LINE_COLOR_SECONDARY,
    apply_plot_fontsizes,
    configure_headless_matplotlib,
    double_column_figure_size,
)


@dataclass(frozen=True)
class TimingSeries:
    label: str
    paths: tuple[Path, ...]
    times: list[float]
    statuses: list[str]


def _parse_tm(path: Path) -> tuple[list[float], list[str]]:
    lines = [raw.strip() for raw in path.read_text(encoding="utf-8").splitlines() if raw.strip()]
    if not lines:
        raise ValueError(f"No timing rows found in {path}")

    header = lines[0].lower()
    if header == "bitstring_hex,elapsed_seconds,status":
        times: list[float] = []
        statuses: list[str] = []
        reader = csv.DictReader(lines)
        for row in reader:
            time_raw = (row.get("elapsed_seconds") or "").strip()
            if not time_raw:
                raise ValueError(f"Missing elapsed_seconds in {path}: {row!r}")
            status = (row.get("status") or "unknown").strip().lower() or "unknown"
            times.append(float(time_raw))
            statuses.append(status)
        if not times:
            raise ValueError(f"No timing rows found in {path}")
        return times, statuses

    times: list[float] = []
    statuses: list[str] = []
    for line in lines:
        parts = line.split(":")
        if len(parts) == 2:
            _, time_raw = parts
            status = "unknown"
        elif len(parts) == 3:
            _, time_raw, status = parts
            status = status.strip().lower() or "unknown"
        else:
            raise ValueError(f"Invalid timing row in {path}: {line!r}")
        times.append(float(time_raw))
        statuses.append(status)
    if not times:
        raise ValueError(f"No timing rows found in {path}")
    return times, statuses


def _group_series(entries: Iterable[tuple[str, Path]]) -> list[TimingSeries]:
    grouped: dict[str, dict[str, object]] = {}
    for label, path in entries:
        times, statuses = _parse_tm(path)
        bucket = grouped.setdefault(label, {"paths": [], "times": [], "statuses": []})
        bucket["paths"].append(path)
        bucket["times"].extend(times)
        bucket["statuses"].extend(statuses)
    return [
        TimingSeries(
            label=label,
            paths=tuple(bucket["paths"]),
            times=list(bucket["times"]),
            statuses=list(bucket["statuses"]),
        )
        for label, bucket in sorted(grouped.items())
    ]


def _parse_perf_summary_series(summary_csv: Path) -> list[TimingSeries]:
    entries: list[tuple[str, Path]] = []
    with summary_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            timing_file_raw = (row.get("timing_file") or "").strip()
            if not timing_file_raw:
                continue
            label = (row.get("case_name") or Path(timing_file_raw).parent.name).strip() or "default"
            timing_path = (REPO_ROOT / timing_file_raw).resolve()
            if not timing_path.exists():
                raise FileNotFoundError(f"Timing file referenced by summary.csv not found: {timing_path}")
            entries.append((label, timing_path))
    series = _group_series(entries)
    if not series:
        raise ValueError(f"No timing_file entries found in {summary_csv}")
    return series


def _cloud_timing_paths(summary_csv: Path, row: dict[str, str]) -> tuple[Path, ...]:
    run_id = (row.get("run_id") or "").strip()
    if not run_id:
        return ()

    run_dirs = (
        summary_csv.parent / "runs" / run_id,
        summary_csv.parent / run_id,
    )
    for run_dir in run_dirs:
        if not run_dir.exists():
            continue
        per_batch = tuple(sorted(path.resolve() for path in run_dir.glob("*.timeBitstrings.csv")))
        if per_batch:
            return per_batch
        per_batch = tuple(sorted(path.resolve() for path in run_dir.glob("*.timeBitstrings.tm")))
        if per_batch:
            return per_batch
        legacy = run_dir / "timeBitstrings.csv"
        if legacy.exists():
            return (legacy.resolve(),)
        legacy = run_dir / "timeBitstrings.tm"
        if legacy.exists():
            return (legacy.resolve(),)
    return ()


def _parse_cloud_summary_series(summary_csv: Path) -> list[TimingSeries]:
    entries: list[tuple[str, Path]] = []
    with summary_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (row.get("state") or "").strip().lower() != "success":
                continue
            timing_paths = _cloud_timing_paths(summary_csv, row)
            if not timing_paths:
                continue
            label_kind = (row.get("label_kind") or "").strip()
            value = (row.get("target_label_value") or row.get("target_num_batches") or "").strip()
            if label_kind == "pool_slots" and value:
                label = f"{value} pool slots"
            elif value:
                label = f"{value} batches"
            else:
                label = "cloud"
            for timing_path in timing_paths:
                entries.append((label, timing_path))
    series = _group_series(entries)
    if not series:
        raise ValueError(
            f"No cloud timing files found for successful benchmark rows in {summary_csv}"
        )
    return series


def _parse_summary_series(summary_csv: Path) -> list[TimingSeries]:
    with summary_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames or []
    if "timing_file" in fieldnames:
        return _parse_perf_summary_series(summary_csv)
    if "run_id" in fieldnames and "target_num_batches" in fieldnames:
        return _parse_cloud_summary_series(summary_csv)
    raise ValueError(f"Unsupported summary CSV format for timing histogram: {summary_csv}")


def _parse_series_arg(value: str) -> TimingSeries:
    if "=" not in value:
        raise ValueError("--series must have the form LABEL=PATH")
    label, path_raw = value.split("=", 1)
    label = label.strip()
    if not label:
        raise ValueError("--series label must be non-empty")
    path = Path(path_raw.strip()).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Timing file not found: {path}")
    times, statuses = _parse_tm(path)
    return TimingSeries(label=label, paths=(path,), times=times, statuses=statuses)


def _filter_series(series: list[TimingSeries], status_filter: str) -> list[TimingSeries]:
    if status_filter == "all":
        return series

    filtered: list[TimingSeries] = []
    for item in series:
        pairs = [
            (time_s, status)
            for time_s, status in zip(item.times, item.statuses, strict=True)
            if status == status_filter
        ]
        if not pairs:
            continue
        filtered.append(
            TimingSeries(
                label=item.label,
                paths=item.paths,
                times=[time_s for time_s, _ in pairs],
                statuses=[status for _, status in pairs],
            )
        )
    if not filtered:
        raise ValueError(f"No rows matched status filter {status_filter!r}.")
    return filtered


def _default_output(summary_csv: Path | None, status_filter: str) -> Path:
    suffix = "" if status_filter == "all" else f"_{status_filter}"
    if summary_csv is not None:
        return summary_csv.parent / f"timebitstrings_hist{suffix}.pdf"
    return REPO_ROOT / "untracked" / f"timebitstrings_hist{suffix}.pdf"


def _timing_file_output_name(timing_file: Path, status_filter: str) -> str:
    suffix = "" if status_filter == "all" else f"_{status_filter}"
    name = timing_file.name
    for ext in (".timeBitstrings.csv", ".timeBitstrings.tm", ".csv", ".tm"):
        if name.endswith(ext):
            stem = name[: -len(ext)]
            break
    else:
        stem = timing_file.stem
    if stem in ("", "timeBitstrings"):
        return f"timebitstrings_hist{suffix}.pdf"
    return f"{stem}_timebitstrings_hist{suffix}.pdf"


def _default_title(summary_csv: Path | None, series: list[TimingSeries]) -> str:
    if summary_csv is None:
        return "Bitstrings compute time distribution"
    labels = {item.label for item in series}
    if labels and all(label.endswith(" batches") for label in labels):
        return "Per-bitstring compute time distribution by batch count"
    return "Bitstrings compute time distribution"


def _default_title_for_timing_file(timing_file: Path) -> str:
    parent = timing_file.parent.name
    return f"Bitstrings compute time distribution ({parent})"


def plot_histogram(
    *,
    series: list[TimingSeries],
    output_path: Path,
    title: str,
    xlabel: str = "Compute time [s]",
    ylabel: str = "Bitstrings Count",
    bins: int = 40,
    linear_y: bool = False,
    label_fontsize: float | None = None,
) -> Path:
    if not series:
        raise ValueError("Need at least one timing series to plot.")

    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_plot_fontsizes(plt=plt, label_fontsize=label_fontsize)

    colors = [LINE_COLOR_PRIMARY, LINE_COLOR_SECONDARY, "#2F4858", "#E07A5F", "#6A994E", "#7A5195"]
    fig, ax = plt.subplots(figsize=double_column_figure_size(height_inches=2.9))

    global_min = min(min(item.times) for item in series)
    global_max = max(max(item.times) for item in series)
    if global_max <= global_min:
        global_max = global_min * 1.01

    for idx, item in enumerate(series):
        color = colors[idx % len(colors)]
        ax.hist(
            item.times,
            bins=bins,
            range=(global_min, global_max),
            alpha=0.35,
            color=color,
            label=f"{item.label} (n={len(item.times)})",
        )

    if not linear_y:
        ax.set_yscale("log")
        ax.set_ylim(bottom=1)
    ax.set_xlabel(xlabel)
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, axis="y", alpha=0.25)
    ax.legend(frameon=False)
    fig.tight_layout()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def auto_plot_timebitstrings_histograms(
    *,
    summary_csv: Path,
    output_dir: Path | None = None,
    title: str | None = None,
    bins: int = 40,
    label_fontsize: float | None = None,
) -> list[Path]:
    summary_path = summary_csv.resolve()
    series = _parse_summary_series(summary_path)
    statuses_present = {status for item in series for status in item.statuses}
    status_filters = ["all"]
    for status in ("supported", "rejected"):
        if status in statuses_present:
            status_filters.append(status)

    saved: list[Path] = []
    dest_dir = output_dir.resolve() if output_dir is not None else summary_path.parent
    for status_filter in status_filters:
        filtered = _filter_series(series, status_filter)
        output_path = dest_dir / _default_output(summary_path, status_filter).name
        saved.append(
            plot_histogram(
                series=filtered,
                output_path=output_path,
                title=title or _default_title(summary_path, filtered),
                bins=bins,
                label_fontsize=label_fontsize,
            )
        )
    return saved


def auto_plot_timing_file_histograms(
    *,
    timing_file: Path,
    output_dir: Path | None = None,
    title: str | None = None,
    bins: int = 40,
    label_fontsize: float | None = None,
) -> list[Path]:
    timing_path = timing_file.resolve()
    if not timing_path.exists():
        raise FileNotFoundError(f"Timing file not found: {timing_path}")
    times, statuses = _parse_tm(timing_path)
    base_series = [TimingSeries(label=timing_path.parent.name or timing_path.stem, paths=(timing_path,), times=times, statuses=statuses)]
    statuses_present = {status for status in statuses}
    status_filters = ["all"]
    for status in ("supported", "rejected"):
        if status in statuses_present:
            status_filters.append(status)

    saved: list[Path] = []
    dest_dir = output_dir.resolve() if output_dir is not None else timing_path.parent
    for status_filter in status_filters:
        filtered = _filter_series(base_series, status_filter)
        output_path = dest_dir / _timing_file_output_name(timing_path, status_filter)
        saved.append(
            plot_histogram(
                series=filtered,
                output_path=output_path,
                title=title or _default_title_for_timing_file(timing_path),
                bins=bins,
                label_fontsize=label_fontsize,
            )
        )
    return saved


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plot histogram(s) of per-bitstring compute time from timeBitstrings.csv artifacts."
    )
    parser.add_argument(
        "--summary-csv",
        type=Path,
        default=None,
        help="Load timing series from one perf-sweep or cloud-benchmark summary.csv.",
    )
    parser.add_argument(
        "--series",
        action="append",
        default=[],
        help="Explicit series in the form LABEL=/path/to/timeBitstrings.csv. Can be repeated.",
    )
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--title", default="")
    parser.add_argument("--xlabel", default="Compute time [s]")
    parser.add_argument("--ylabel", default="Bitstrings Count")
    parser.add_argument("--bins", type=int, default=40)
    parser.add_argument(
        "--status-filter",
        choices=("all", "supported", "rejected", "unknown"),
        default="all",
        help="Keep all rows or only one timing status from the .tm file.",
    )
    parser.add_argument(
        "--auto-all-statuses",
        action="store_true",
        help="When using --summary-csv, emit the default histogram and any supported/rejected variants automatically.",
    )
    parser.add_argument("--linear-y", action="store_true", help="Use a linear y-axis instead of log scale.")
    parser.add_argument("--label-fontsize", type=float, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.summary_csv is None and not args.series:
        raise ValueError("Pass either --summary-csv or at least one --series LABEL=PATH.")
    if args.auto_all_statuses and args.summary_csv is None:
        raise ValueError("--auto-all-statuses requires --summary-csv.")
    if args.auto_all_statuses and args.output is not None:
        raise ValueError("--auto-all-statuses does not accept --output; it writes the standard set of files.")
    if args.auto_all_statuses and args.series:
        raise ValueError("--auto-all-statuses cannot be combined with --series.")

    summary_csv = args.summary_csv.resolve() if args.summary_csv is not None else None
    if args.auto_all_statuses:
        saved = auto_plot_timebitstrings_histograms(
            summary_csv=summary_csv,
            title=args.title or None,
            bins=args.bins,
            label_fontsize=args.label_fontsize,
        )
        for path in saved:
            print(f"Saved plot: {path}")
        return 0

    all_series: list[TimingSeries] = []
    if summary_csv is not None:
        all_series.extend(_parse_summary_series(summary_csv))
    for raw in args.series:
        all_series.append(_parse_series_arg(raw))

    series = _filter_series(all_series, args.status_filter)
    output_path = (
        args.output.resolve()
        if args.output is not None
        else _default_output(summary_csv, args.status_filter)
    )
    saved = plot_histogram(
        series=series,
        output_path=output_path,
        title=args.title or _default_title(summary_csv, series),
        xlabel=args.xlabel,
        ylabel=args.ylabel,
        bins=args.bins,
        linear_y=args.linear_y,
        label_fontsize=args.label_fontsize,
    )
    print(f"Saved plot: {saved}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

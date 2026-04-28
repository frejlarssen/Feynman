from __future__ import annotations

import csv
import json
import shlex
import statistics
import sys
from pathlib import Path

from sweeplib.provenance import get_git_info
from sweeplib.sweep import run_sweep
from sweeplib.plot_style import apply_plot_fontsizes, configure_headless_matplotlib
from sweeplib.plotting import default_plot_output_path, load_xy_from_summary, render_sweep_plot

from .cli import build_config
from .project import build_metadata, build_run_points, make_run_one, resolve_paths
from .schema import SUMMARY_FIELDS


def _infer_vary_label(summary_path: Path) -> str:
    metadata_path = summary_path.parent / "sweep_metadata.json"
    if not metadata_path.exists():
        return "varied_value"
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "varied_value"
    vary = payload.get("config", {}).get("vary", "")
    return vary if isinstance(vary, str) and vary else "varied_value"


def _plot_cases_total_full(summary_csv: Path) -> Path:
    grouped: dict[str, list[float]] = {}
    with summary_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if int(row.get("returncode", "1")) != 0:
                continue
            case_name = row.get("case_name", "") or "default"
            y_raw = row.get("total_full_s", "")
            if y_raw is None or y_raw == "":
                continue
            grouped.setdefault(case_name, []).append(float(y_raw))
    if len(grouped) <= 1:
        raise ValueError("No multiple cases available for case aggregate plot.")

    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_plot_fontsizes(plt=plt, label_fontsize=None)
    case_names = sorted(grouped)
    means = [statistics.mean(grouped[name]) for name in case_names]
    stds = [statistics.stdev(grouped[name]) if len(grouped[name]) > 1 else 0.0 for name in case_names]
    fig, ax = plt.subplots(figsize=(8, 5))
    xs = list(range(len(case_names)))
    ax.bar(xs, means, yerr=stds, capsize=5, alpha=0.9)
    ax.set_xticks(xs, case_names)
    ax.set_ylabel("total_full_s")
    ax.set_xlabel("case_name")
    ax.set_title("total_full_s by case")
    ax.grid(True, axis="y", alpha=0.3)
    fig.tight_layout()
    output_path = summary_csv.parent / "plot_total_full_s_by_case.pdf"
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def _plot_cases_vs_x(
    summary_csv: Path,
    *,
    x_column: str,
    y_column: str,
    xscale: str = "linear",
    yscale: str = "linear",
) -> Path:
    grouped: dict[str, dict[float, list[float]]] = {}
    with summary_csv.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if int(row.get("returncode", "1")) != 0:
                continue
            x_raw = row.get(x_column, "")
            y_raw = row.get(y_column, "")
            if x_raw in (None, "") or y_raw in (None, ""):
                continue
            case_name = row.get("case_name", "") or "default"
            x = float(x_raw)
            y = float(y_raw)
            grouped.setdefault(case_name, {}).setdefault(x, []).append(y)
    if len(grouped) <= 1:
        raise ValueError("No multiple cases available for case line plot.")

    configure_headless_matplotlib()
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    apply_plot_fontsizes(plt=plt, label_fontsize=None)
    fig, ax = plt.subplots(figsize=(8, 5))
    for case_name in sorted(grouped):
        x_sorted = sorted(grouped[case_name])
        means = [statistics.mean(grouped[case_name][x]) for x in x_sorted]
        stds = [
            statistics.stdev(grouped[case_name][x]) if len(grouped[case_name][x]) > 1 else 0.0
            for x in x_sorted
        ]
        ax.errorbar(
            x_sorted,
            means,
            yerr=stds,
            fmt="o-",
            capsize=4,
            linewidth=1.4,
            markersize=5,
            label=case_name,
        )
    if xscale not in {"linear", "log", "symlog"}:
        raise ValueError(f"Unsupported xscale: {xscale}")
    if yscale not in {"linear", "log", "symlog"}:
        raise ValueError(f"Unsupported yscale: {yscale}")
    if xscale == "log":
        all_x = [x for case_data in grouped.values() for x in case_data]
        if any(x <= 0.0 for x in all_x):
            raise ValueError(f"xscale=log requires all {x_column} values > 0.")
    if yscale == "log":
        all_y = [y for case_data in grouped.values() for ys in case_data.values() for y in ys]
        if any(y <= 0.0 for y in all_y):
            raise ValueError(f"yscale=log requires all {y_column} values > 0.")

    ax.set_xscale(xscale)
    ax.set_yscale(yscale)
    ax.set_xlabel(x_column)
    ax.set_ylabel(y_column)
    scale_suffix = "" if (xscale == "linear" and yscale == "linear") else f" ({xscale}/{yscale})"
    ax.set_title(f"{y_column} vs {x_column} by case{scale_suffix}")
    ax.grid(True, alpha=0.3)
    ax.legend()
    fig.tight_layout()
    output_path = summary_csv.parent / f"plot_{y_column}_vs_{x_column}_by_case.pdf"
    fig.savefig(output_path, dpi=160)
    plt.close(fig)
    return output_path


def main(entry_script: Path | None = None, argv: list[str] | None = None) -> int:
    config = build_config(argv)
    repo_root_raw = Path(config.repo_root).expanduser()
    repo_root = repo_root_raw.resolve() if repo_root_raw.is_absolute() else (Path.cwd() / repo_root_raw).resolve()
    paths = resolve_paths(config, repo_root)
    git_info = get_git_info(paths.repo_root)
    run_one = make_run_one(config=config, paths=paths, git_info=git_info)
    run_points = build_run_points(config)
    runner_script_path = entry_script or Path(__file__).resolve()
    invocation = shlex.join(sys.argv)

    def _auto_plot(_sweep_dir: Path, summary_csv: Path, _metadata_path: Path, failures: int) -> None:
        try:
            x_label = _infer_vary_label(summary_csv)
            xs, ys = load_xy_from_summary(
                summary_path=summary_csv,
                x_column="varied_value",
                y_column="total_full_s",
                include_failures=(failures > 0),
            )
            output_path = default_plot_output_path(
                summary_csv,
                x_column=x_label,
                y_column="total_full_s",
            )
            render_sweep_plot(
                xs=xs,
                ys=ys,
                mode="meanstd",
                x_label=x_label,
                y_label="total_full_s",
                title=config.experiment_name,
                output_path=output_path,
                label_fontsize=None,
            )
            if failures > 0:
                print(f"Auto-generated plot (partial sweep): {output_path}")
            else:
                print(f"Auto-generated plot: {output_path}")
        except (RuntimeError, ValueError, FileNotFoundError) as exc:
            print(f"Auto-plot skipped: {exc}", file=sys.stderr)

        try:
            case_plot = _plot_cases_total_full(summary_csv)
            print(f"Auto-generated case plot: {case_plot}")
        except (RuntimeError, ValueError, FileNotFoundError):
            pass
        try:
            structure_case_plot = _plot_cases_vs_x(
                summary_csv,
                x_column="total_artificial_sources",
                y_column="total_full_s",
                xscale="linear",
                yscale="log",
            )
            print(f"Auto-generated structure case plot: {structure_case_plot}")
        except (RuntimeError, ValueError, FileNotFoundError):
            pass

    return run_sweep(
        output_root=paths.output_root,
        experiment_name=config.experiment_name,
        summary_fields=SUMMARY_FIELDS,
        values=run_points,
        repeat=config.repeat,
        continue_on_error=config.continue_on_error,
        run_one=run_one,
        build_metadata=lambda sweep_dir, created_at: build_metadata(
            config=config,
            paths=paths,
            git_info=git_info,
            sweep_dir=sweep_dir,
            created_at=created_at,
            runner_script_path=runner_script_path,
            invocation=invocation,
        ),
        on_complete=_auto_plot,
    )

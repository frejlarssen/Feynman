from __future__ import annotations

import os
from pathlib import Path

PLOT_LABEL_FONTSIZE_ENV = "FEYNMAN_PLOT_LABEL_FONTSIZE"
PLOT_TICK_FONTSIZE_DELTA_ENV = "FEYNMAN_PLOT_TICK_FONTSIZE_DELTA"
PLOT_TITLE_FONTSIZE_DELTA_ENV = "FEYNMAN_PLOT_TITLE_FONTSIZE_DELTA"
PLOT_FIGURE_TITLE_FONTSIZE_DELTA_ENV = "FEYNMAN_PLOT_FIGURE_TITLE_FONTSIZE_DELTA"
PLOT_SUBPLOT_TITLE_FONTSIZE_DELTA_ENV = "FEYNMAN_PLOT_SUBPLOT_TITLE_FONTSIZE_DELTA"

# Measured from the IEEEtran 10 pt conference manuscript log.  Matplotlib
# expects inches, while TeX reports dimensions in TeX points (72.27 pt/in).
IEEE_CONFERENCE_COLUMN_WIDTH_PT = 252.0
IEEE_CONFERENCE_TEXT_WIDTH_PT = 516.0
TEX_POINTS_PER_INCH = 72.27

DEFAULT_LABEL_FONTSIZE = 8.5
DEFAULT_TICK_FONTSIZE_DELTA = -0.9
DEFAULT_TITLE_FONTSIZE_DELTA = 0.0
DEFAULT_FIGURE_TITLE_FONTSIZE_DELTA = 0.7
DEFAULT_SUBPLOT_TITLE_FONTSIZE_DELTA = -0.9

SINGLE_COLUMN_FIGURE_HEIGHT_IN = 2.35
STACKED_SINGLE_COLUMN_FIGURE_HEIGHT_IN = 3.25
DOUBLE_COLUMN_FIGURE_HEIGHT_IN = 2.65

LINE_COLOR_PRIMARY = "#1f77b4"
LINE_COLOR_SECONDARY = "#d62728"

DEFAULT_LINEWIDTH_PRIMARY = 1.2
DEFAULT_LINEWIDTH_SECONDARY = 1.1
DEFAULT_MARKERSIZE = 3.5
DEFAULT_MARKER_PRIMARY = "o"
DEFAULT_MARKER_SECONDARY = "s"


def ieee_column_width_inches() -> float:
    return IEEE_CONFERENCE_COLUMN_WIDTH_PT / TEX_POINTS_PER_INCH


def ieee_text_width_inches() -> float:
    return IEEE_CONFERENCE_TEXT_WIDTH_PT / TEX_POINTS_PER_INCH


def single_column_figure_size(
    height_inches: float = SINGLE_COLUMN_FIGURE_HEIGHT_IN,
) -> tuple[float, float]:
    return ieee_column_width_inches(), float(height_inches)


def stacked_single_column_figure_size() -> tuple[float, float]:
    return ieee_column_width_inches(), STACKED_SINGLE_COLUMN_FIGURE_HEIGHT_IN


def double_column_figure_size(
    height_inches: float = DOUBLE_COLUMN_FIGURE_HEIGHT_IN,
) -> tuple[float, float]:
    return ieee_text_width_inches(), float(height_inches)


def configure_headless_matplotlib() -> None:
    os.environ.setdefault("MPLCONFIGDIR", "/tmp/mplconfig_feynman")
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp/xdg_cache_feynman")
    Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)
    Path(os.environ["XDG_CACHE_HOME"]).mkdir(parents=True, exist_ok=True)


def resolve_label_fontsize(label_fontsize: float | None = None) -> float:
    if label_fontsize is not None:
        size = float(label_fontsize)
    else:
        raw = os.environ.get(PLOT_LABEL_FONTSIZE_ENV, "").strip()
        if raw:
            try:
                size = float(raw)
            except ValueError as exc:
                raise ValueError(
                    f"{PLOT_LABEL_FONTSIZE_ENV} must be a float, got {raw!r}."
                ) from exc
        else:
            size = DEFAULT_LABEL_FONTSIZE
    if size <= 0.0:
        raise ValueError("Label fontsize must be > 0.")
    return size


def _resolve_delta(env_name: str, default: float) -> float:
    raw = os.environ.get(env_name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ValueError(f"{env_name} must be a float, got {raw!r}.") from exc


def resolve_subplot_title_fontsize(label_fontsize: float | None = None) -> float:
    base = resolve_label_fontsize(label_fontsize)
    delta = _resolve_delta(PLOT_SUBPLOT_TITLE_FONTSIZE_DELTA_ENV, DEFAULT_SUBPLOT_TITLE_FONTSIZE_DELTA)
    return max(1.0, base + delta)


def format_metric_label(name: str) -> str:
    key = str(name).strip()
    if key == "total_full_s":
        return r"$T_{tot}$"
    if key == "total_artificial_sources":
        return r"$A$"
    if key == "fidelity_to_reference":
        return "Fidelity"
    return key


def apply_plot_fontsizes(*, plt, label_fontsize: float | None = None) -> float:
    size = resolve_label_fontsize(label_fontsize)
    tick_delta = _resolve_delta(PLOT_TICK_FONTSIZE_DELTA_ENV, DEFAULT_TICK_FONTSIZE_DELTA)
    title_delta = _resolve_delta(PLOT_TITLE_FONTSIZE_DELTA_ENV, DEFAULT_TITLE_FONTSIZE_DELTA)
    figure_title_delta = _resolve_delta(
        PLOT_FIGURE_TITLE_FONTSIZE_DELTA_ENV, DEFAULT_FIGURE_TITLE_FONTSIZE_DELTA
    )
    tick_size = max(1.0, size + tick_delta)
    title_size = max(1.0, size + title_delta)
    figure_title_size = max(1.0, size + figure_title_delta)
    plt.rcParams.update(
        {
            "axes.labelsize": size,
            "xtick.labelsize": tick_size,
            "ytick.labelsize": tick_size,
            "axes.titlesize": title_size,
            "legend.fontsize": tick_size,
            "figure.titlesize": figure_title_size,
            "lines.linewidth": DEFAULT_LINEWIDTH_PRIMARY,
            "lines.markersize": DEFAULT_MARKERSIZE,
        }
    )
    return size

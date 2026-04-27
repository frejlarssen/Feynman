from __future__ import annotations

import os
from pathlib import Path

PLOT_LABEL_FONTSIZE_ENV = "FEYNMAN_PLOT_LABEL_FONTSIZE"
DEFAULT_LABEL_FONTSIZE = 18.0

LINE_COLOR_PRIMARY = "#1f77b4"
LINE_COLOR_SECONDARY = "#d62728"

DEFAULT_LINEWIDTH_PRIMARY = 1.8
DEFAULT_LINEWIDTH_SECONDARY = 1.6
DEFAULT_MARKER_PRIMARY = "o"
DEFAULT_MARKER_SECONDARY = "s"


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


def apply_plot_fontsizes(*, plt, label_fontsize: float | None = None) -> float:
    size = resolve_label_fontsize(label_fontsize)
    tick_size = max(1.0, size - 1.0)
    plt.rcParams.update(
        {
            "axes.labelsize": size,
            "xtick.labelsize": tick_size,
            "ytick.labelsize": tick_size,
            "axes.titlesize": size + 1.0,
            "legend.fontsize": tick_size,
            "figure.titlesize": size + 2.0,
        }
    )
    return size

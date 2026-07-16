# Experiment scripts

The output of the experiment is found in `outputs/experiments/`.

Run all experiment configs (perf + validation):

```bash
python scripts/run_pipeline.py run-all-experiments --scope all
```

Minimal plot-only:

```bash
python scripts/run_pipeline.py plot perf-sweep --latest \
  --y-column total_full_s --mode meanstd
```

Regenerate all existing plots after style changes:

```bash
python scripts/regenerate_all_plots.py
```

`--latest` can be used in plot/replot flows to auto-pick a recent run directory.
Use explicit `--summary-csv`, `--comparison-csv`, or `--summary-json` when you
want strict reproducibility.

## Outputs and Commit Policy

- Keep curated JSON configs in `scripts/experiments/paper/` and `scripts/experiments/exploratory/`.
- Do not commit generated inputs/outputs (`data/generated/`, `data/outputs/` are gitignored).
- Archive interesting run artifacts externally (re-runnable from committed configs).
- Keep only small, hand-curated fixtures in `data/fixtures/`.

## Plotting

Global plotting typography/style defaults are centralized in
`scripts/sweeplib/plot_style.py` (with optional env overrides such as
`FEYNMAN_PLOT_LABEL_FONTSIZE`).

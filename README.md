# Feynman

A sparse-output Feynman path simulator.

## Formats

Hexadecimal output states `.hs`:

```text
num_hexstrings
size_in_bytes
...
hexstrings
...
```

Circuit format: subset of QASM with extensions (for example `ccccx`).
Circuit size is rounded up automatically to the closest multiple of 8.

## Setup

```bash
micromamba create -n feynman -f environment.yml
micromamba activate feynman
```

Generate input artifacts:

```bash
python3 generators/generate_bulk.py
```

Build:

```bash
cmake --preset dev
cmake --build --preset dev -j
```

Build one target:

```bash
cmake --build --preset dev --target sv_prefetcher_mpi_subsetbitstrings -j
```

## Quickstart

Raw binary example:

```bash
mkdir -p data/outputs/tmp
mpirun -n 1 ./build/sv_prefetcher_subset_mpi.x \
  -c data/generated/circuits/qft/qft_n8_k2.qasm \
  -i data/generated/statevectors/ket0_size1.hsv \
  -b data/generated/hexstring_sets/nrhex10_size1_from0x0_to0xA.hs \
  -o data/outputs/tmp/qft_n8_k2_run.hsv \
  -t 0.0 -v 1
```

Unified pipeline entrypoint:

```bash
python3 scripts/run_pipeline.py <subcommand> ...
```

Minimal perf sweep:

```bash
python3 scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/exploratory/perf/qft_n8_batch_sweep.json
```

Minimal plot-only:

```bash
python3 scripts/run_pipeline.py plot perf-sweep --latest \
  --y-column total_full_s --mode meanstd
```

Regenerate all existing plots after style changes:

```bash
python3 scripts/regenerate_all_plots.py
```

`--latest` can be used in plot/replot flows to auto-pick a recent run directory.
Use explicit `--summary-csv`, `--comparison-csv`, or `--summary-json` when you
want strict reproducibility.

## Documentation Map

- Full experiment/validation catalog: `docs/experiments.md`
- Paper-targeted reproducibility map: `docs/paper_experiments.md`

## Outputs and Commit Policy

- Keep curated JSON configs in `scripts/experiments/paper/` and `scripts/experiments/exploratory/`.
- Do not commit generated inputs/outputs (`data/generated/`, `data/outputs/` are gitignored).
- Archive interesting run artifacts externally (re-runnable from committed configs).
- Keep only small, hand-curated fixtures in `data/fixtures/`.

## Development

If needed, regenerate `compile_commands.json` through an intercepted build:

```bash
bear -- cmake --build build -j
```

Global plotting typography/style defaults are centralized in
`scripts/sweeplib/plot_style.py` (with optional env overrides such as
`FEYNMAN_PLOT_LABEL_FONTSIZE`).

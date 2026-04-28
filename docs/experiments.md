# Experiments and Validation Catalog

This file is the full command catalog for the unified pipeline in
`scripts/run_pipeline.py`.

All runs write into `data/outputs/experiments/` or `data/outputs/validation/`.
Experiment and validation runs generate their associated plots automatically.

For perf experiments, build the release binary first:

```bash
cmake --preset release
cmake --build --preset release --target sv_prefetcher_mpi_subsetbitstrings -j
```

Perf configs in this catalog use `build-release/sv_prefetcher_subset_mpi.x`.

Perf run telemetry now records:

- `summary.csv`: `ranks`, `active_workers`, `omp_threads_per_worker`
- `sweep_metadata.json`: host logical core counts (`os.cpu_count` and `nproc`)

Batch-run all configs (perf + validation):

```bash
python3 scripts/run_pipeline.py run-all-experiments --scope all
```

Useful options:

```bash
python3 scripts/run_pipeline.py run-all-experiments --scope paper --dry-run
python3 scripts/run_pipeline.py run-all-experiments --scope exploratory --fail-fast
```

## Perf Sweeps

### QFT Batch Sweep

```bash
python3 scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/exploratory/perf/qft_n8_batch_sweep.json
```

Plot from explicit summary:

```bash
python3 scripts/run_pipeline.py plot perf-sweep \
  --summary-csv data/outputs/experiments/<timestamp>_qft_n8_batch_sweep/summary.csv \
  --y-column total_full_s \
  --mode meanstd
```

### Checkpoint Ablations

AA (small):

```bash
python3 scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/paper/perf/aa_n3_it3_mark1_checkpoint_ablation.json
```

AA (larger):

```bash
python3 scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/exploratory/perf/aa_n4_it3_mark5_checkpoint_ablation.json
```

QFT:

```bash
python3 scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/exploratory/perf/qft_n8_k2_checkpoint_ablation.json
```

QWalk:

```bash
python3 scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/exploratory/perf/qwalk_n16_it16_checkpoint_ablation.json
```

QWalk iteration sweep with checkpoint strategy lines:

```bash
python3 scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/exploratory/perf/qwalk_n16_iteration_checkpoint_sources.json
```

Plot `total_full_s` vs `total_artificial_sources` with one line per case:

```bash
python3 scripts/run_pipeline.py plot perf-case-lines \
  --summary-csv data/outputs/experiments/<timestamp>_qwalk_n16_iteration_checkpoint_sources/summary.csv \
  --x-column total_artificial_sources \
  --y-column total_full_s \
  --yscale log
```

Case aggregate plot:

```bash
python3 scripts/run_pipeline.py plot perf-cases \
  --summary-csv data/outputs/experiments/<timestamp>_aa_n3_it3_mark1_checkpoint_ablation/summary.csv \
  --y-column gate_ops_estimate
```

## QAOA Pruning Sweep

```bash
python3 scripts/run_pipeline.py qaoa-pruning \
  --config scripts/experiments/paper/perf/qaoa_pruning_sweep_cycle_n8_p2.json
```

Optional disable auto-plot:

```bash
python3 scripts/run_pipeline.py qaoa-pruning \
  --config scripts/experiments/paper/perf/qaoa_pruning_sweep_cycle_n8_p2.json \
  --no-plot
```

Plot-only:

```bash
python3 scripts/run_pipeline.py plot qaoa-pruning \
  --summary-csv data/outputs/experiments/<timestamp>_qaoa_pruning_sweep_cycle_n8_p2/summary.csv
```

Plot meaning: blue is `total_full_s` (left axis), red is
`fidelity_to_reference` (right axis).

## Validation Workflows

### QAOA vs Qiskit

```bash
python3 scripts/run_pipeline.py validation qaoa-qiskit \
  --config scripts/experiments/paper/validation/qaoa_cycle_n8_p2_qiskit_validation.json
```

Alternative config:

```bash
python3 scripts/run_pipeline.py validation qaoa-qiskit \
  --config scripts/experiments/exploratory/validation/qft_n8_k4_qiskit_validation.json
```

Plot-only:

```bash
python3 scripts/run_pipeline.py plot qaoa-qiskit \
  --comparison-csv data/outputs/validation/<timestamp>_qaoa_cycle_n8_p2_qiskit_validation/comparison.csv
```

### QFT Demo

```bash
python3 scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/exploratory/validation/qft_demo.json
```

Other available configs:

```bash
python3 scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/paper/validation/qft_two_freq_nqubits_demo_norm.json
```

```bash
python3 scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/exploratory/validation/qft_n16_feynman_low_high_bulk.json
```

```bash
python3 scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/exploratory/validation/qft_n24_feynman_low_high_bulk.json
```

Replot from existing CSV (no rerun):

```bash
python3 scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/exploratory/validation/qft_demo.json \
  -- --from-csv \
  --summary-json data/outputs/validation/<run_dir>/summary.json
```

## Convenience: Latest Run Resolution

For interactive work, plot/replot commands support `--latest` to auto-select a
recent run directory. For reproducible scripts and paper workflows, prefer
explicit artifact paths.

Bulk regeneration after style changes:

```bash
python3 scripts/regenerate_all_plots.py
```

Optional helpers:

```bash
python3 scripts/regenerate_all_plots.py --dry-run
python3 scripts/regenerate_all_plots.py --fail-fast
```

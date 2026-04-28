# Experiments and Validation Catalog

This file is the full command catalog for the unified pipeline in
`scripts/run_pipeline.py`.

All runs write into `data/outputs/experiments/` or `data/outputs/validation/`.
Experiment and validation runs generate their associated plots automatically.

## Perf Sweeps

### QFT Batch Sweep

```bash
python3 scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/perf/qft_n8_batch_sweep.json
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
  --config scripts/experiments/perf/aa_n3_it3_mark1_checkpoint_ablation.json
```

AA (larger):

```bash
python3 scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/perf/aa_n4_it3_mark5_checkpoint_ablation.json
```

QFT:

```bash
python3 scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/perf/qft_n8_k2_checkpoint_ablation.json
```

QWalk:

```bash
python3 scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/perf/qwalk_n16_it16_checkpoint_ablation.json
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
  --config scripts/experiments/perf/qaoa_pruning_sweep_cycle_n8_p2.json
```

Optional disable auto-plot:

```bash
python3 scripts/run_pipeline.py qaoa-pruning \
  --config scripts/experiments/perf/qaoa_pruning_sweep_cycle_n8_p2.json \
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
  --config scripts/experiments/validation/qaoa_cycle_n8_p2_qiskit_validation.json
```

Alternative config:

```bash
python3 scripts/run_pipeline.py validation qaoa-qiskit \
  --config scripts/experiments/validation/qft_n8_k4_qiskit_validation.json
```

Plot-only:

```bash
python3 scripts/run_pipeline.py plot qaoa-qiskit \
  --comparison-csv data/outputs/validation/<timestamp>_qaoa_cycle_n8_p2_qiskit_validation/comparison.csv
```

### QFT Demo

```bash
python3 scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/validation/qft_demo.json
```

Other available configs:

```bash
python3 scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/validation/qft_two_freq_nqubits_demo_norm.json
```

```bash
python3 scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/validation/qft_n16_feynman_low_high_bulk.json
```

```bash
python3 scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/validation/qft_n24_feynman_low_high_bulk.json
```

Replot from existing CSV (no rerun):

```bash
python3 scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/validation/qft_demo.json \
  -- --from-csv \
  --summary-json data/outputs/validation/<run_dir>/summary.json
```

## Convenience: Latest Run Resolution

For interactive work, plot/replot commands support `--latest` to auto-select a
recent run directory. For reproducible scripts and paper workflows, prefer
explicit artifact paths.

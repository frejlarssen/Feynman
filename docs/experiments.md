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

- `summary.csv`: `ranks`, `feynman_env`, `active_workers`, `omp_threads_per_worker`
- `sweep_metadata.json`: host logical core counts (`os.cpu_count` and `nproc`)
- `sweep_metadata.json`: git commit, dirty flag, config/build inputs, and a
  scoped git patch snapshot for perf sweeps

Batch-run all configs (perf + validation):

```bash
python scripts/run_pipeline.py run-all-experiments --scope all
```

Useful options:

```bash
python scripts/run_pipeline.py run-all-experiments --scope paper --dry-run
python scripts/run_pipeline.py run-all-experiments --scope exploratory --fail-fast
```

## Perf Sweeps

### QFT Batch Sweep

```bash
python scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/exploratory/perf/qft_batch_sweep.json
```

Plot from explicit summary:

```bash
python scripts/run_pipeline.py plot perf-sweep \
  --summary-csv data/outputs/experiments/<timestamp>_qft_n8_batch_sweep/summary.csv \
  --y-column total_full_s \
  --mode meanstd
```

### Checkpoint Ablations

AA (small):

```bash
python scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/paper/perf/aa_checkpoint_ablation.json
```

AA (larger):

```bash
python scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/exploratory/perf/aa_checkpoint_ablation.json
```

QFT:

```bash
python scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/exploratory/perf/qft_checkpoint_ablation.json
```

QWalk:

```bash
python scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/exploratory/perf/qwalk_checkpoint_ablation.json
```

QWalk iteration sweep with checkpoint strategy lines:

```bash
python scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/paper/perf/qwalk_iteration_checkpoint_sources.json
```

Plot `total_full_s` vs `total_artificial_sources` with one line per case:

```bash
python scripts/run_pipeline.py plot perf-case-lines \
  --summary-csv data/outputs/experiments/<timestamp>_qwalk_iteration_checkpoint_sources/summary.csv \
  --x-column total_artificial_sources \
  --y-column total_full_s \
  --yscale log
```

Case aggregate plot:

```bash
python scripts/run_pipeline.py plot perf-cases \
  --summary-csv data/outputs/experiments/<timestamp>_aa_n4_it3_mark5_checkpoint_ablation/summary.csv \
  --y-column gate_ops_estimate
```

## QAOA Pruning Sweep

```bash
python scripts/run_pipeline.py qaoa-pruning \
  --config scripts/experiments/paper/perf/qaoa_pruning_sweep_cycle_n8_p2.json
```

Optional disable auto-plot:

```bash
python scripts/run_pipeline.py qaoa-pruning \
  --config scripts/experiments/paper/perf/qaoa_pruning_sweep_cycle_n8_p2.json \
  --no-plot
```

Plot-only:

```bash
python scripts/run_pipeline.py plot qaoa-pruning \
  --summary-csv data/outputs/experiments/<timestamp>_qaoa_pruning_sweep_cycle_n8_p2/summary.csv
```

Plot meaning: blue is `total_full_s` (left axis), red is
`fidelity_to_reference` (right axis).

### QWalk qubit sweep vs quimb

```bash
python scripts/run_pipeline.py qwalk-quimb-sweep \
  --config scripts/experiments/paper/perf/qwalk_quimb_qubit_sweep.json
```

This performance benchmark runs the same fixed-iteration quantum-walk family while varying
qubit count. Each point runs exact quimb selected amplitudes, Feynman on the
original multi-controlled-gate circuit, and Feynman on the same Qiskit-lowered
circuit used by quimb. The sweep records runtime, peak RSS, and lowered
operation counts, then writes time, memory, and operation-count plots.

## Validation Workflows

### QWalk vs quimb

```bash
python scripts/run_pipeline.py validation qwalk-quimb \
  --config scripts/experiments/exploratory/validation/qwalk_quimb_smoke.json
```

This workflow materializes a generated quantum-walk circuit, lowers its
multi-controlled gates through Qiskit to a quimb-compatible basis, computes
selected amplitudes by exact tensor-network contraction, and optionally runs
Feynman on the original and quimb-lowered circuits for agreement and timing.

### QAOA vs Qiskit

```bash
python scripts/run_pipeline.py validation qaoa-qiskit \
  --config scripts/experiments/exploratory/validation/qaoa_cycle_n8_p2_qiskit_validation.json
```

This is a development/reference check used by the QAOA pruning machinery, not
a standalone paper figure.

Alternative config:

```bash
python scripts/run_pipeline.py validation qaoa-qiskit \
  --config scripts/experiments/exploratory/validation/qft_qiskit_validation.json
```

Plot-only:

```bash
python scripts/run_pipeline.py plot qaoa-qiskit \
  --comparison-csv data/outputs/validation/<timestamp>_qaoa_cycle_n8_p2_qiskit_validation/comparison.csv
```

### QFT Demo

```bash
python scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/exploratory/validation/qft_demo.json
```

Other available configs:

```bash
python scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/paper/validation/qft_demo.json
```

```bash
python scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/exploratory/validation/qft_n16_feynman_low_high_bulk.json
```

```bash
python scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/exploratory/validation/qft_n24_feynman_low_high_bulk.json
```

Replot from existing CSV (no rerun):

```bash
python scripts/run_pipeline.py validation qft-demo \
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
python scripts/regenerate_all_plots.py --dry-run
python scripts/regenerate_all_plots.py --fail-fast
```

This discovers saved summaries under `data/outputs/experiments/` and
`data/outputs/validation/`. It regenerates plots from those artifacts only; it
does not rerun experiments. Multi-case performance summaries generate the
generic sweep, case aggregate, and case-line variants when applicable.

To continue past individual plotting failures instead of stopping at the first
one, omit `--fail-fast`:

```bash
python scripts/regenerate_all_plots.py
```

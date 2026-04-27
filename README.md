# Feynman
A Feynman simulator.

## File format

Hexadecimal output states `.hs` of the format:
```
num_hexstrings
size_in_bytes
...
hexstrings
...
```

## Circuit format
Subset of QASM, with some extensions such as multi-controlled gates (eg. `ccccx`).
The circuit size is rounded up automatically to closest multiple of 8.

Generators produce bulks of datafiles:

```bash
python3 generators/generate_bulk.py
```

## Setup

```
micromamba create -n feynman -f environment.yml
micromamba activate feynman
```

### Build with CMake

```bash
cmake --preset dev
cmake --build --preset dev -j
```

Build one target:
```bash
cmake --build build --target sv_prefetcher_mpi_subsetbitstrings -j
```

## Example usage
Generate desired circuits and datafiles with the `generators/`.

```bash
mkdir -p data/outputs/tmp
mpirun -n 1 ./build/sv_prefetcher_subset_mpi.x \
  -c data/generated/circuits/qft/qft_n8_k2.qasm \
  -i data/generated/statevectors/ket0_size1.hsv \
  -b data/generated/hexstring_sets/nrhex10_size1_from0x0_to0xA.hs \
  -o data/outputs/tmp/qft_n8_k2_run.hsv \
  -t 0.0 -v 1

# If interesting results
scripts/save_output.sh data/outputs/tmp/qft_n8_k2_run.hsv qft-n8-k2-example "threshold=0.0 n=8"

```

## Unified Sweep + Plot Pipeline

All experiment and validation entrypoints are unified under:

```bash
python3 scripts/run_pipeline.py <subcommand> ...
```

### Perf Sweep

Run a parameter sweep:

```bash
python3 scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/perf/qft_n8_batch_sweep.json
```

Override extra mode-specific flags by passing them after `--`:

```bash
python3 scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/perf/qft_n8_batch_sweep.json \
  -- --ranks 8 --repeat 5
```

Plot-only from an existing `summary.csv`:

```bash
python3 scripts/run_pipeline.py plot perf-sweep \
  --summary-csv data/outputs/experiments/<timestamp>_qft_n8_batch_sweep/summary.csv \
  --y-column total_full_s \
  --mode meanstd
```

Case aggregate plot:

```bash
python3 scripts/run_pipeline.py plot perf-cases \
  --summary-csv data/outputs/experiments/<timestamp>_qwalk_n16_it16_checkpoint_ablation/summary.csv \
  --y-column gate_ops_estimate
```

### QAOA Pruning Sweep

Run QAOA threshold pruning sweep (auto-plot enabled by default):

```bash
python3 scripts/run_pipeline.py qaoa-pruning \
  --config scripts/experiments/perf/qaoa_pruning_sweep_cycle_n8_p2.json
```

Disable auto-plot for a run:

```bash
python3 scripts/run_pipeline.py qaoa-pruning \
  --config scripts/experiments/perf/qaoa_pruning_sweep_cycle_n8_p2.json \
  --no-plot
```

Plot-only from an existing summary:

```bash
python3 scripts/run_pipeline.py plot qaoa-pruning \
  --summary-csv data/outputs/experiments/<timestamp>_qaoa_pruning_sweep_cycle_n8_p2/summary.csv
```

In this plot, blue is `total_full_s` (left y-axis) and red is
`fidelity_to_reference` (right y-axis).

### Validation

QAOA vs Qiskit validation:

```bash
python3 scripts/run_pipeline.py validation qaoa-qiskit \
  --config scripts/experiments/validation/qaoa_cycle_n8_p2_qiskit_validation.json
```

QFT demo validation:

```bash
python3 scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/validation/qft_demo.json
```

`qft-demo` supports generator objects for `circuit`, `input_statevector`, and
`output_bitstrings`, and this path/object materialization is shared with sweep
and validation flows through `scripts/sweeplib/materialize.py`.

Replot from existing CSV without rerun:

```bash
python3 scripts/run_pipeline.py validation qft-demo \
  --config scripts/experiments/validation/qft_demo.json \
  -- --from-csv \
  --summary-json data/outputs/validation/<run_dir>/summary.json
```

### Outputs and Commit Policy

- Keep curated JSON configs in `scripts/experiments/perf/` and `scripts/experiments/validation/`.
- Do not commit generated inputs/outputs (`data/generated/`, `data/outputs/` are gitignored).
- Archive interesting run artifacts externally (re-runnable from committed configs).
- Keep only small, hand-curated fixtures in `data/fixtures/`.

## For development

Add `bear --` before `make` to create file used for clangd.

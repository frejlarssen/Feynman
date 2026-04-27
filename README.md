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
cmake -S . -B build
cmake --build build -j
```

Build one target:
```bash
cmake --build build --target sv_prefetcher_mpi_subsetbitstrings -j
```

## Example usage
Generate desired circuits in `circuits/`.

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

## Parameter Sweeps

For repeatable experiments with metadata + plotting:

```bash
cmake --build build --target sv_prefetcher_mpi_subsetbitstrings -j

python3 scripts/run_sv_prefetcher_sweep.py \
  --config scripts/experiments/qft_n8_batch_sweep.json

# Optional: override one or two values from CLI
python3 scripts/run_sv_prefetcher_sweep.py \
  --config scripts/experiments/qft_n8_batch_sweep.json \
  --ranks 8 --repeat 5

python3 scripts/plot_sv_prefetcher_sweep.py \
  --summary-csv data/outputs/experiments/<timestamp>_qft_n8_batch_sweep/summary.csv \
  --y-column total_full_s \
  --mode meanstd
```

Example config file:
```json
{
  "experiment_name": "qft_n8_batch_sweep",
  "vary": "batch_size",
  "values": [8, 16, 32, 64, 128],
  "repeat": 3,
  "ranks": 4,
  "circuit": "data/generated/circuits/qft/qft_n8_k2.qasm",
  "input_statevector": "data/generated/statevectors/ket0_size1.hsv",
  "output_bitstrings": "data/generated/hexstring_sets/nrhex10_size1_from0x0_to0xA.hs",
  "p": 8,
  "r": 4,
  "output_root": "data/outputs/experiments"
}
```

Each sweep creates:
- `summary.csv` with one row per run (parameter values, case name, return code, extracted timings).
- `summary.csv` also includes parsed chunk/source metrics, autotuning metrics (`autotune_time_s`, `autotune_candidates`, `autotune_step_size`, `autotune_best_gate_ops_estimate`), and derived fields such as `gate_ops_estimate`.
- `sweep_metadata.json` (commit, branch, dirty flag, host, invocation, env snapshot).
- `git_diff_apps_src.patch` with staged/unstaged/untracked snapshot for `apps/` and `src/`.
- Provenance in metadata also includes binary SHA256, input file SHA256, CMake build/compiler info, and `mpirun` version output.
- A per-run folder containing `output.hsv`, `timeBitstrings.tm`, `stdout.log`, `stderr.log`.

Case-based ablation in one sweep (optional):
```json
{
  "experiment_name": "qwalk_cp_ablation",
  "vary": "batch_size",
  "values": [32],
  "repeat": 5,
  "ranks": 4,
  "batch_size": 32,
  "fraction": 1.0,
  "threshold": 1e-8,
  "circuit": "data/generated/circuits/qwalk/qwalk_n16_it16.qasm",
  "input_statevector": "data/fixtures/ket0.hsv",
  "output_bitstrings": "data/generated/hexstring_sets/nrhex10_size2_from0x0_to0xA.hs",
  "cases": [
    {"name": "no_cp", "p": 0, "r": 0},
    {"name": "fixed_cp", "p": 176, "r": 176},
    {"name": "autotuned_cp", "p": null, "r": null}
  ]
}
```

Case plot helper:
```bash
python3 scripts/plot_sv_prefetcher_cases.py \
  --summary-csv data/outputs/experiments/<timestamp>_qwalk_cp_ablation/summary.csv \
  --y-column gate_ops_estimate
```

Merge helper for multiple sweep directories:
```bash
python3 scripts/merge_sv_prefetcher_summaries.py \
  --summary-csv data/outputs/experiments/<run1>/summary.csv \
  --summary-csv data/outputs/experiments/<run2>/summary.csv \
  --output data/outputs/experiments/merged.csv
```

Sweep script layout:
- `scripts/sweeplib/` contains shared sweep/plot/provenance helpers (`sweep`, `plotting`, `provenance`, `utils`).
- `scripts/sv_prefetcher_sweep/` contains project-specific modules (`schema`, `cli`, `project`, `main`).

## For development

Add `bear -- ` before `make` to create file used for clangd.

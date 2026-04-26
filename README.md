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
- `summary.csv` with one row per run (parameter values, return code, extracted timings).
- `sweep_metadata.json` (commit, branch, dirty flag, host, invocation, env snapshot).
- `git_diff_apps_src.patch` with staged/unstaged/untracked snapshot for `apps/` and `src/`.
- Provenance in metadata also includes binary SHA256, input file SHA256, CMake build/compiler info, and `mpirun` version output.
- A per-run folder containing `output.hsv`, `timeBitstrings.tm`, `stdout.log`, `stderr.log`.

Sweep script layout:
- `scripts/sweeplib/` contains shared sweep/plot/provenance helpers (`sweep`, `plotting`, `provenance`, `utils`).
- `scripts/sv_prefetcher_sweep/` contains project-specific modules (`schema`, `cli`, `project`, `main`).

## For development

Add `bear -- ` before `make` to create file used for clangd.

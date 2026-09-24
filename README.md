# Feynman

A sparse-output Feynman path simulator.

## Setup

Activate the environment:

```bash
python3 -m venv ~/venvs/feynman-mysystem
source ~/venvs/feynman-mysystem/bin/activate
python -m pip install -r requirements.txt
```

Generate input artifacts:

```bash
python generators/generate_bulk.py
```

Build release for experiments:

```bash
cmake --preset release
cmake --build --preset release --target feynman_mpi -j
```

The presets use Unix Makefiles. `dev` / `release` enable MPI; `standalone-dev`
/ `standalone` build without MPI. A C++17 compiler, Make, and OpenMP are required;
the MPI presets additionally require MPI. Presets require CMake 3.21 or newer.
Use a fresh build directory when changing generators.

For standalone or cloud execution:

```bash
cmake --preset standalone
cmake --build --preset standalone -j 8
```

The apps are `feynman.x`, `feynman_mpi.x`, `feynman_split_batches.x`, and
`feynman_concat_batches.x`. Both simulators use OpenMP internally; set
`OMP_NUM_THREADS` to control threads per process.

## Quickstart

Run `./build-release/feynman_mpi.x -h` for the list of arguments.

Example with a 8 qubit QFT:

```bash
mkdir -p data/outputs/tmp
mpirun -n 1 ./build-release/feynman_mpi.x \
  -c data/generated/circuits/qft/qft_n8_k2.qasm \
  -i data/generated/statevectors/ket0_size1.hsv \
  -b data/generated/hexstring_sets/nrhex10_size1_from0x0_to0xA.hs \
  -o data/outputs/tmp/qft_n8_k2_run.hsv \
  -t 0.0 -v 1
```

The output amplitudes is found in `data/outputs/tmp/qft_n8_k2_run.hsv`.

For one amplitude, supply binary input/output strings (most significant bit
first) instead of files:

```bash
./build-standalone/feynman.x \
  -c data/generated/circuits/qft/qft_n8_k2.qasm \
  --input-bits 00000000 --output-bits 00000001 -t 0
```

`--build-only` reports circuit structure without simulating. `-p` and `-r`
set the gate counts in the rightmost and middle chunks; omit both to autotune.

MPI scheduling is selected with `--schedule`: `static-block` distributes
contiguous ranges, `static-cyclic` distributes outputs round-robin, `dynamic`
requests batches on demand, and `prefetch` (default) requests the next batch
while computing. Dynamic/prefetch reserve rank 0 as coordinator when more than
one rank is used. `--batch-size N` must be positive and affects only these two
modes; it no longer selects scheduling. All modes work with one rank.

## Experiments

Unified pipeline entrypoint for experiments:

```bash
python scripts/run_pipeline.py <subcommand> ...
```

Minimal perf sweep:

```bash
python scripts/run_pipeline.py perf-sweep \
  --config scripts/experiments/exploratory/perf/qft_batch_sweep.json
```

Selected-output accuracy validation:

```bash
python scripts/run_pipeline.py validation selected-output-accuracy \
  --config scripts/experiments/exploratory/validation/google_rqc_selected_accuracy_smoke.json \
  -- --binary build-release/feynman_mpi.x --ranks 1
```

Cross-seeded selected-population validation:

```bash
python scripts/run_pipeline.py validation selected-output-accuracy \
  --config scripts/experiments/exploratory/validation/google_rqc_selected_accuracy_cross_seeded_smoke.json \
  -- --binary build-release/feynman_mpi.x --ranks 1
```

## Documentation Map

- More utilities of experiment scripts: `docs/scripts.md`
- Full experiment/validation catalog: `docs/experiments.md`
- Paper-targeted reproducibility map: `docs/paper_experiments.md`
- File formats of input files: `docs/file_formats.md`
- Cloud setup: `docs/cloud.md`

## Development

Build for dev/debug:

```bash
micromamba create -n feynman -f environment.yml
micromamba activate feynman
```


```bash
cmake --preset dev
cmake --build --preset dev -j
```

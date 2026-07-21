# Feynman

A sparse-output Feynman path simulator.

## Setup

```bash
micromamba create -n feynman -f environment.yml
micromamba activate feynman
```

Generate input artifacts:

```bash
python generators/generate_bulk.py
```

Build release for experiments:

```bash
cmake --preset release
cmake --build --preset release --target sv_prefetcher_mpi_subsetbitstrings -j
```

## Quickstart

Run `./build-release/sv_prefetcher_subset_mpi.x -h` for the list of arguments.

Example with a 8 qubit QFT:

```bash
mkdir -p data/outputs/tmp
mpirun -n 1 ./build-release/sv_prefetcher_subset_mpi.x \
  -c data/generated/circuits/qft/qft_n8_k2.qasm \
  -i data/generated/statevectors/ket0_size1.hsv \
  -b data/generated/hexstring_sets/nrhex10_size1_from0x0_to0xA.hs \
  -o data/outputs/tmp/qft_n8_k2_run.hsv \
  -t 0.0 -v 1
```

The output amplitudes is found in `data/outputs/tmp/qft_n8_k2_run.hsv`.

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

## Documentation Map

- More utilities of experiment scripts: `docs/scripts.md`
- Full experiment/validation catalog: `docs/experiments.md`
- Paper-targeted reproducibility map: `docs/paper_experiments.md`
- File formats of input files: `docs/file_formats.md`
- Cloud setup: `docs/cloud.md`

## Development

Build for dev/debug:

```bash
cmake --preset dev
cmake --build --preset dev -j
```

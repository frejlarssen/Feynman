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
(TODO: Document conda env.)
```
# Optional:
# conda activate feynman
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
## For development

Add `bear -- ` before `make` to create file used for clangd.

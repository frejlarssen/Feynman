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

## Example usage

```
conda activate feynman

make sv_prefetcher_mpi_subsetbitstrings
cd circuits/
python3 quantum_walk_generator.py
python3 qft_generator.py
cd ../
mkdir outputs
mpirun -n 4 ./sv_prefetcher_subset_mpi.x -c circuits/qft_12.qasm -i statevectors/ket0.sv -o outputs/qftout -t 0.0 -v 1


python tests.py

```
## For development

Add `bear -- ` before `make` to create file used for clangd.

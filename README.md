# Feynman
A Feynman simulator.

## Setup
MPI and OpenMP is used for parallelization.

`compilers` ensures the compilers are compatible with the conda packages.

`qiskit` is optional and only required for testing.

Using a conda environment:
```bash
conda create --name feynman -c conda-forge openmpi llvm-openmp compilers qiskit
conda activate feynman
```

## Example usage
```bash
make sv_embedded_mpi
cd circuits/
python3 quantum_walk_generator.py
python3 qft_generator.py
cd ../
mkdir outputs
mpirun -n 4 ./sv_embedded_mpi.x -c ./circuits/small.qasm -i ./statevectors/ket0_size1.hsv -f 1.0 -o ./outputs/small_f1.0.hsv -v 2
```

## Run tests
```bash
make sv_embedded_mpi
python tests.py
```
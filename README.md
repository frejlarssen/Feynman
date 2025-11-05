# FeynQFT
A Feynman simulator.

Example usage:

```
make sv_scheduler_mpi
cd circuits/
python3 quantum_walk_generator.py
python3 qft_generator.py
cd ../
mkdir outputs
mpirun -n 4 ./sv_scheduler_mpi.x -c circuits/qft_12.qasm -i statevectors/ket0.sv -o outputs/qftout -t 0.0 -v 1

```

# FeynQFT
A Feynman simulator.

Example usage:

```
make sv_mpi
cd circuits/
python3 quantum_walk_generator.py
cd ../
mkdir outputs
mpirun -n 4 ./sv_mpi.x -c ./circuits/qwalk_n4_it20.qasm -i ./statevectors/ket0.sv -o ./outputs/output.sv -v 2

```

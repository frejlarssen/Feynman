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
mpirun -n 4 ./sv_prefetcher_subset_mpi.x -c ./circuits/qft_n8_k2.qasm -i ./statevectors/amplitude_signal_size1QB_f6_f64.0_relamp0.2_t0.5_v2.hsv -o ./outputs/qft_size1QB_20outs_t0.5_full.hsv -v 2

```

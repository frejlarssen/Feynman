# Runs .qasm files with both ./simulator and qiskit and compares all input/output.

import subprocess
import sys
import numpy as np
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector
from qiskit import qasm3

def run_simulator(qasm_file, input_bits, output_bits):
    cmd = ["./simulator", "-c", qasm_file, "-i", input_bits, "-o", output_bits]
    #print("Running command:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    for line in result.stdout.splitlines():
        #print(line)
        if "Total amplitude:" in line:
            amp_str = line.split("Total amplitude:")[1].strip()
            real, imag = amp_str.split("+ i")
            return complex(float(real), float(imag))
    raise RuntimeError("Simulator output did not contain amplitude.")

def run_qiskit(qasm_file, input_bits, output_bits):
    qc = qasm3.load(qasm_file)
    #print("input_bits:", input_bits)
    #print("int input_bits:", int(input_bits, 2))
    state = Statevector.from_int(int(input_bits, 2), 2**qc.num_qubits)
    state = state.evolve(qc)
    output_index = int(output_bits, 2)
    amp = state.data[output_index]
    return amp

def bitstrings(n):
    return [format(i, f'0{n}b') for i in range(2**n)]

if __name__ == "__main__":
    # Hardcoded QASM files and number of qubits for each
    qasm_files = [
        ("./circuits/aa_n2_it1_mark1.qasm", 2),
        ("./circuits/qft_3.qasm", 3),
        # ("./circuits/qwalk_n4_it1.qasm", 4),
        # TODO: Implement multi-controll gates in main branch
        # TODO: Report fail at python Error.
    ]

    all_passed = True

    for qasm_file, n_qubits in qasm_files:
        print(f"Testing {qasm_file} with {n_qubits} qubits")
        inputs = bitstrings(n_qubits)
        outputs = bitstrings(n_qubits)
        for input_bits in inputs:
            for output_bits in outputs:
                try:
                    amp_sim = run_simulator(qasm_file, input_bits, output_bits)
                    amp_qiskit = run_qiskit(qasm_file, input_bits, output_bits)
                    match = np.allclose([amp_sim.real, amp_sim.imag], [amp_qiskit.real, amp_qiskit.imag], atol=1e-6)
                    all_passed = all_passed and match
                    status = "PASS" if match else "FAIL"
                    print(f"{qasm_file} | in: {input_bits} out: {output_bits} | sim: {amp_sim} | qiskit: {amp_qiskit} | {status}")
                except Exception as e:
                    print(f"{qasm_file} | in: {input_bits} out: {output_bits} | ERROR: {e}")
    print("All tests passed!" if all_passed else "Some tests failed.")

# Runs .qasm files with both ./sv_embedded and qiskit and calculates fidelity.

import subprocess
import sys
import numpy as np
import time
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector
from qiskit import qasm3

#def run_simulator(qasm_file, input_bits, output_bits, p=None, r=None, fraction=1.0):
#    cmd = ["./bitstr", "-c", qasm_file, "-i", input_bits, "-o", output_bits]
#    if p != None:
#        cmd.append("-p")
#        cmd.append(str(p))
#    if r != None:
#        cmd.append("-r")
#        cmd.append(str(r))
#    
#    cmd.append("-f")
#    cmd.append(str(fraction))
#    print("Running command:", " ".join(cmd))
#    result = subprocess.run(cmd, capture_output=True, text=True)
#    for line in result.stdout.splitlines():
#        #print(line)
#        if "Total amplitude:" in line:
#            amp_str = line.split("Total amplitude:")[1].strip()
#            real, imag = amp_str.split("+ i")
#            return (complex(float(real), float(imag)), result.stdout)
#    print("Did not find amplitude in simulator output. Full output:")
#    for line in result.stdout.splitlines():
#        print("STDERR:", line)
#    raise RuntimeError("Simulator output did not contain amplitude.")

def run_simulator(qasm_file, input_sv, output_sv, num_processes=4, p=None, r=None, fraction=None, batch_size=None):
    cmd = ["mpirun", "-n", str(num_processes), "./sv_embedded_mpi.x", "-c", qasm_file, "-i", input_sv, "-o", output_sv]
    if p != None:
        cmd.append("-p")
        cmd.append(str(p))
    if r != None:
        cmd.append("-r")
        cmd.append(str(r))
    if fraction != None:
        cmd.append("-f")
        cmd.append(str(fraction))
    if batch_size != None:
        cmd.append("-s")
        cmd.append(str(batch_size))

    print("Running command:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    for line in result.stdout.splitlines():
        print(line)
    return






#def build_simulator(qasm_file):
#    cmd = ["./simulator", "-c", qasm_file, "-B"]
#    result = subprocess.run(cmd, capture_output=True, text=True)
#    nr_gates = -1
#    nr_artificial = -1
#    for line in result.stdout.splitlines():
#        if "Total gates:" in line:
#            gates_str = line.split("Total gates:")[1].strip()
#            nr_gates = int(gates_str)
#        if "Artificial sources:" in line:
#            art_str = line.split("Artificial sources:")[1].strip()
#            nr_artificial = int(art_str)
#    if (nr_gates == -1 or nr_artificial == -1):
#        print("Did not find total gates or artificial sources in simulator output. Full output:")
#        for line in result.stdout.splitlines():
#            print("STDERR:", line)
#        raise RuntimeError("Build output did not contain info.")
#    return (nr_gates, nr_artificial)

def run_qiskit(qasm_file, input_bits, output_bits):
    try:
        qc = build_qiskit_circuit_from_custom_qasm(qasm_file)
        #print(f"Qiskit Circuit:\n{qc.draw()}")
        state = Statevector.from_int(int(input_bits, 2), 2**qc.num_qubits)
        state = state.evolve(qc)
        output_index = int(output_bits, 2)
        amp = state.data[output_index]
        return amp
    except Exception as e:
        raise RuntimeError(f"Qiskit simulation failed: {e}")

def build_qiskit_circuit_from_custom_qasm(qasm_file):
    with open(qasm_file) as f:
        lines = f.readlines()

    # Find number of qubits from 'qubit' or 'qreg' declaration
    n_qubits = None
    for line in lines:
        if line.startswith("qubit"):
            n_qubits = int(line.split("[")[1].split("]")[0])
            break
        elif line.startswith("qreg"):
            n_qubits = int(line.split("[")[1].split("]")[0])
            break
    if n_qubits is None:
        raise RuntimeError("Could not determine number of qubits from QASM.")

    qc = QuantumCircuit(n_qubits)

    for line in lines:
        line = line.strip()
        if not line or line.startswith("//") or line.startswith("OPENQASM"):
            continue
        if line.startswith("qubit") or line.startswith("qreg") or line.startswith("include"):
            continue

        # Single-controlled phase: cp(theta) q[control],q[target]
        if line.startswith("cp"):
            gate, args = line.split(" ")
            theta = float(gate.split("(")[1].split(")")[0])
            qubits = [int(s.split("[")[1].split("]")[0]) for s in args.split(",")]
            control, target = qubits
            qc.cp(theta, control, target)
        # Multi-controlled gates: c...cX, c...cZ, c...cH, etc.
        elif line.startswith("c") and len(line.split(" ")[0]) > 1:
            gate, args = line.split(" ")
            num_controls = gate.count("c")
            base_gate = gate[num_controls:]
            qubit_indices = [int(s.split("[")[1].split("]")[0]) for s in args.split(",")]
            controls = qubit_indices[:num_controls]
            target = qubit_indices[num_controls]
            if base_gate == "x":
                qc.mcx(controls, target)
            elif base_gate == "z":
                qc.h(target)
                qc.mcx(controls, target)
                qc.h(target)
            elif base_gate == "h":
                if num_controls == 0:
                    qc.h(target)
                else:
                    raise RuntimeError("Multi-controlled H is not natively supported in Qiskit.")
            else:
                raise RuntimeError(f"Unsupported multi-controlled gate: {gate}")
        # Hadamard: h q[0]
        elif line.startswith("h"):
            _, arg = line.split(" ")
            q = int(arg.split("[")[1].split("]")[0])
            qc.h(q)
        # Phase: p(theta) q[0]
        elif line.startswith("p"):
            gate, rest = line.split(" ", 1)
            theta = float(rest.split(")")[0].split("(")[1])
            q = int(rest.split(" ")[1].split("[")[1].split("]")[0])
            qc.p(theta, q)
        # X: x q[0]
        elif line.startswith("x"):
            _, arg = line.split(" ")
            q = int(arg.split("[")[1].split("]")[0])
            qc.x(q)
        # Z: z q[0]
        elif line.startswith("z"):
            _, arg = line.split(" ")
            q = int(arg.split("[")[1].split("]")[0])
            qc.z(q)
        # SWAP: swap q[0],q[1]
        elif line.startswith("swap"):
            _, args = line.split(" ")
            q0 = int(args.split(",")[0].split("[")[1].split("]")[0])
            q1 = int(args.split(",")[1].split("[")[1].split("]")[0])
            qc.swap(q0, q1)
        else:
            raise RuntimeError(f"Unsupported gate in QASM: {line}")

    return qc

def bitstrings(n):
    return [format(i, f'0{n}b') for i in range(2**n)]

def calculate_fidelity(sim_vector, qiskit_vector):
    print("sim_vector:", sim_vector) #TODO: Check why sim_vector is not already normalized
    print("qiskit_vector:", qiskit_vector)
    sim_vector = sim_vector / np.linalg.norm(sim_vector)
    qiskit_vector = qiskit_vector / np.linalg.norm(qiskit_vector)
    dot_prod = np.dot(np.conj(sim_vector), qiskit_vector)
    fidelity = np.abs(dot_prod) ** 2
    return fidelity

"""
Reads a statevector from a .hsv file and returns it as a numpy array of complex numbers. The file is in the format:
0x0: 0.0625+0i
0x1: 0.1875+0i
0xA: -0.0625+0i
0xF: 0.0625+0i

Note that only the non-zero amplitudes are stored in the file. We need to reconstruct the full statevector.
"""
def get_statevector_from_file(sv_file, nr_qubytes):
    statevector = np.zeros(2**(nr_qubytes*8), dtype=complex)
    with open(sv_file, 'r') as f:
        for line in f:
            if line.startswith("0x"):
                key, value = line.split(": ")
                index = int(key, 16)
                # Note that complex() expects the format a+bj, so we replace 'i' with 'j'
                value = value.replace('i', 'j')
                statevector[index] = complex(value.strip())
    return statevector

def test_fidelity(qasm_file, n_qubytes, fraction):
    input_sv = f"./statevectors/ket0_size{n_qubytes}.hsv"
    output_sv_sim = f"./outputs/sim_output_size{n_qubytes}.hsv"
    run_simulator(qasm_file, input_sv, output_sv_sim, num_processes=4, fraction=fraction)

    sim_vector = get_statevector_from_file(output_sv_sim, n_qubytes)

    qc = build_qiskit_circuit_from_custom_qasm(qasm_file)
    state = Statevector.from_int(0, 2**(n_qubytes*8))
    state = state.evolve(qc)
    qiskit_vector = state.data

    fidelity = calculate_fidelity(sim_vector, qiskit_vector)
    print(f"Fidelity between simulator and Qiskit for {qasm_file}: {fidelity}")

if __name__ == "__main__":
    start = time.time()
    #run_simulator("./circuits/small.qasm", "./statevectors/ket0_size1.hsv", "./outputs/small_f1.0.hsv", num_processes=4, p=None, r=None, fraction=1.0, batch_size=None)

    test_fidelity("./circuits/small.qasm", n_qubytes=1, fraction=100000.0)
    end = time.time()
    print("Time elapsed in total: ", end - start, "s")

    #deep()
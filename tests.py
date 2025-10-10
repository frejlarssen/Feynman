# Runs .qasm files with both ./simulator and qiskit and compares all input/output.

import subprocess
import sys
import numpy as np
import time
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector
from qiskit import qasm3

def run_simulator(qasm_file, input_bits, output_bits, p=None, r=None):
    cmd = ["./simulator", "-c", qasm_file, "-i", input_bits, "-o", output_bits]
    if p != None:
        cmd.append("-p")
        cmd.append(str(p))
    if r != None:
        cmd.append("-r")
        cmd.append(str(r))
    #print("Running command:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)
    for line in result.stdout.splitlines():
        #print(line)
        if "Total amplitude:" in line:
            amp_str = line.split("Total amplitude:")[1].strip()
            real, imag = amp_str.split("+ i")
            return (complex(float(real), float(imag)), result.stdout)
    print("Did not find amplitude in simulator output. Full output:")
    for line in result.stdout.splitlines():
        print("STDERR:", line)
    raise RuntimeError("Simulator output did not contain amplitude.")

def build_simulator(qasm_file):
    cmd = ["./simulator", "-c", qasm_file, "-B"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    nr_gates = -1
    nr_artificial = -1
    for line in result.stdout.splitlines():
        if "Total gates:" in line:
            gates_str = line.split("Total gates:")[1].strip()
            nr_gates = int(gates_str)
        if "Artificial sources:" in line:
            art_str = line.split("Artificial sources:")[1].strip()
            nr_artificial = int(art_str)
    if (nr_gates == -1 or nr_artificial == -1):
        print("Did not find total gates or artificial sources in simulator output. Full output:")
        for line in result.stdout.splitlines():
            print("STDERR:", line)
        raise RuntimeError("Build output did not contain info.")
    return (nr_gates, nr_artificial)

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

def test_case(filename, input_bits, output_bits, all_params = False):
    if all_params: #TODO: If possible, test systematically but not all of the possible parameters.
        try:
            (nr_gates, nr_art) = build_simulator(filename)
            print("nr_gates returned: ", nr_gates, " and nr_art: ", nr_art)
            amp_qiskit = run_qiskit(filename, input_bits, output_bits)
            all_params_status = True
            for p in range(nr_gates+1):
                for r in range(nr_gates - p + 1):
                    try:
                        (amp_sim, stdout) = run_simulator(filename, input_bits, output_bits, p, r)
                        match = np.allclose([amp_sim.real, amp_sim.imag], [amp_qiskit.real, amp_qiskit.imag], atol=1e-6)
                        status = "PASS" if match else "FAIL"
                        print(f"{filename} | in: {input_bits} out: {output_bits} | p: {p} r: {r} | sim: {amp_sim} | qiskit: {amp_qiskit} | {status}")
                        if "FAIL" in status:
                            all_params_status = False
                            print("Failed for this parameters. Simulator output was:")
                            print(stdout)
                            return False
                    except Exception as e:
                        print(f"{filename} | in: {input_bits} out: {output_bits} | p: {p} r: {r} | ERROR: {e}")
                        return False
            return all_params_status
        except Exception as e:
            print(f"{filename} | Build ERROR: {e}")
            return False
    else:
        try:
            (amp_sim, stdout) = run_simulator(filename, input_bits, output_bits)
            amp_qiskit = run_qiskit(filename, input_bits, output_bits)
            match = np.allclose([amp_sim.real, amp_sim.imag], [amp_qiskit.real, amp_qiskit.imag], atol=1e-6)
            status = "PASS" if match else "FAIL"
            print(f"{filename} | in: {input_bits} out: {output_bits} | sim: {amp_sim} | qiskit: {amp_qiskit} | {status}")
            #if "FAIL" in status:
            #    print("Failed. Simulator output was:")
            #    print(stdout)
        except Exception as e:
            print(f"{filename} | in: {input_bits} out: {output_bits} | ERROR: {e}")
            return False
        return match

def test_exhaustive(filename, n_qubits, all_params = False):
    print(f"Testing {filename} with {n_qubits} qubits")
    inputs = bitstrings(n_qubits)
    outputs = bitstrings(n_qubits)
    all_passed = True
    for input_bits in inputs:
        for output_bits in outputs:
            try:
                match = test_case(filename, input_bits, output_bits, all_params)
                all_passed = all_passed and match
                if not match:
                    return False
            except Exception as e:
                print(f"{filename} | in: {input_bits} out: {output_bits} | ERROR: {e}")
                all_passed = False
    if all_passed:
        print(f"All tests passed for {filename}")
        return True
    else:
        print(f"Some tests failed for {filename}")
        return False

def exhaustive(all_params = False):
    # Hardcoded QASM files and number of qubits for each
    qasm_files = [
        ("./circuits/small.qasm", 2),
        ("./circuits/aa_n2_it1_mark1.qasm", 2),
        ("./circuits/qft_3.qasm", 3),
        ("./circuits/qwalk_n2_it1.qasm", 2),
        #("./circuits/qwalk_n2_it2.qasm", 2),
        #("./circuits/qwalk_n3_it2.qasm", 3),
        #("./circuits/qwalk_n4_it2.qasm", 4),
    ]

    all_files_passed = True
    for qasm_file, n_qubits in qasm_files:
        file_status = test_exhaustive(qasm_file, n_qubits, all_params)
        all_files_passed = file_status and all_files_passed
        if not file_status:
            return False

    if all_files_passed:
        print("All files passed.")
    else:
        print("Some files failed.")


def deep():
    test_case("./circuits/qwalk_n4_it10.qasm", "0000", "0000")
    #test_case("./circuits/qwalk_n4_it15.qasm", "0000", "0000")

if __name__ == "__main__":
    start = time.time()
    exhaustive(all_params=True)
    end = time.time()
    print("Time elapsed in total: ", end - start, "s")

    #deep()
# Runs .qasm files with both ./simulator and qiskit and compares all input/output.

import subprocess
import sys
import numpy as np
import time
from qiskit import QuantumCircuit
from qiskit.quantum_info import Statevector
from qiskit import qasm3

"""
Reads a statevector from a .hsv file and returns it as a numpy array of complex numbers. The file is in the format:
4
1
0x00: 0.0625+0i
0x01: 0.1875+0i
0x0A: -0.0625+0i
0x0F: 0.0625+0i

Note that only the non-zero amplitudes are stored in the file. We need to reconstruct the full statevector.
"""
def get_statevector_from_file(hsv_file, nr_qubytes):
    print("Reading statevector from file:", hsv_file, "with nr_qubytes:", nr_qubytes)
    statevector = np.zeros(2**(nr_qubytes*8), dtype=complex)
    with open(hsv_file, 'r') as f:
        for line in f:
            if line.startswith("0x"):
                key, value = line.split(":")
                index = int(key, 16)
                value = value.replace('i', 'j') # Make it Python complex format
                value = value.replace('+-', '-')
                #print("Parsed line:", line.strip(), "-> index:", index, "value:", value)
                #print("Complex value as string:", value.strip())
                statevector[index] = complex(value.strip())
    #print("Reconstructed statevector from file", hsv_file, ":", statevector)
    return statevector

def delete_file(file):
    cmd = ["rm",
           file]
    result = subprocess.run(cmd, capture_output=True, text=True)

    print(f"Output from rm {file}:")
    for line in result.stdout.splitlines():
        print("STDOUT:", line)

    for line in result.stderr.splitlines():
        print("STDERR:", line)

def run_simulator(n_mpi, nr_qubytes, input_hsv_file, qasm_file, hexstrings_file, output_hsv_file, p=None, r=None, fraction=None):
    cmd = ["mpirun",
           "-n", str(n_mpi),
           "./sv_prefetcher_subset_mpi.x",
           "-i", input_hsv_file,
           "-c", qasm_file,
           "-b", hexstrings_file,
           "-o", output_hsv_file]
    if p != None:
        cmd.append("-p")
        cmd.append(str(p))
    if r != None:
        cmd.append("-r")
        cmd.append(str(r))
    if fraction != None:
        cmd.append("-f")
        cmd.append(str(fraction))
    print("Running command:", " ".join(cmd))
    result = subprocess.run(cmd, capture_output=True, text=True)

    print("Full output:")
    for line in result.stdout.splitlines():
        print("STDOUT:", line)
    
    for line in result.stderr.splitlines():
        print("STDERR:", line)
    
    if result.returncode == 0:
        print("Simulator completed successfully. Getting statevector from output file.")
        sim_vector = get_statevector_from_file(output_hsv_file, nr_qubytes)
        return (sim_vector, result.stdout)
    else:
        raise RuntimeError(f"Simulator failed with return code {result.returncode}")


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

def run_qiskit(input_hsv_file, qasm_file, n_qubytes):
    try:
        qc = build_qiskit_circuit_from_custom_qasm(qasm_file)
        print("Built Qiskit circuit from QASM.")
        state = get_statevector_from_file(input_hsv_file, n_qubytes)
        #print("Initial statevector for Qiskit:", state)
        state = Statevector(state)
        #print("Qiskit statevector (after conversion):", state)
        state = state.evolve(qc)
        #print("Qiskit statevector after evolution:", state)
        qiskit_vector = state.data
        print("Qiskit statevector:", qiskit_vector)
        return qiskit_vector
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

def test_all_params(n_mpi, nr_qubytes, input_hsv_file, qasm_file, hexstrings_file, output_hsv_file, all_params = False, fraction = 1.0):
    delete_file(output_hsv_file) #Delete so that correct file doesn't already exist

    if all_params: #TODO: If possible, test systematically but not all of the possible parameters.
        try:
            (nr_gates, nr_art) = build_simulator(qasm_file)
            print("nr_gates returned: ", nr_gates, " and nr_art: ", nr_art)
            amp_qiskit = run_qiskit(input_hsv_file, qasm_file, nr_qubytes)
            all_params_status = True
            for p in range(nr_gates+1):
                for r in range(nr_gates - p + 1):
                    try:
                        (sim_vector, _) = run_simulator(n_mpi, nr_qubytes, input_hsv_file, qasm_file, hexstrings_file, output_hsv_file, p, r, fraction=fraction)
                        print("Simulator output statevector:", sim_vector)

                        match = np.allclose([sim_vector.real, sim_vector.imag], [amp_qiskit.real, amp_qiskit.imag], atol=1e-6)
                        status = "PASS" if match else "FAIL"
                        print(f"{qasm_file} | p: {p} r: {r} | sim: {sim_vector} | qiskit: {amp_qiskit} | {status}")
                        if "FAIL" in status:
                            all_params_status = False
                            print("Failed for this parameters. Simulator output was:")
                            print(stdout)
                            return False
                    except Exception as e:
                        print(f"{qasm_file} | p: {p} r: {r} | ERROR: {e}")
                        return False
            return all_params_status
        except Exception as e:
            print(f"{qasm_file} | Build ERROR: {e}")
            return False
    else:
        try:
            amp_qiskit = run_qiskit(input_hsv_file, qasm_file, nr_qubytes)
            (amp_sim, stdout) = run_simulator(n_mpi, nr_qubytes, input_hsv_file, qasm_file, hexstrings_file, output_hsv_file)
            #print("Simulator output statevector:", amp_sim)
            #print("a: ", [amp_sim.real, amp_sim.imag])
            #print("b: ", [amp_qiskit.real, amp_qiskit.imag])
            match = np.allclose(amp_sim, amp_qiskit, atol=1e-1, rtol=1e-1)
            status = "PASS" if match else "FAIL"
            print(f"{qasm_file} | sim: {amp_sim} | qiskit: {amp_qiskit} | {status}")
            #if "FAIL" in status:
            #    print("Failed. Simulator output was:")
            #    print(stdout)
        except Exception as e:
            print(f"{qasm_file} | ERROR: {e}")
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
                match = test_all_params(filename, input_bits, output_bits, all_params)
                all_passed = all_passed and match
                if not match:
                    return False
            except Exception as e:
                print(f"{filename} | ERROR: {e}")
                all_passed = False
    if all_passed:
        print(f"All tests passed for {filename}")
        return True
    else:
        print(f"Some tests failed for {filename}")
        return False


def test_fidelity(filename, n_qubits, fraction=1.0):
    print(f"Testing {filename} with {n_qubits} qubits")
    #inputs = bitstrings(n_qubits)
    inputs = ['111']
    outputs = bitstrings(n_qubits)
    all_passed = True
    for input_bits in inputs:
        sim_results = []
        qiskit_results = []
        for output_bits in outputs:
            try:
                (sim_res, sim_out) = run_simulator(filename, n_qubits * 8, input_bits, output_bits, fraction=fraction)
                print("sim_res: ", sim_res)
                sim_results.append(sim_res)
                qis_res = run_qiskit(filename, input_bits, output_bits)
                print("qis_res:", qis_res)
                qiskit_results.append(qis_res)
            except Exception as e:
                print(f"In test_fidelity: {filename} | in: {input_bits} out: {output_bits} | ERROR: {e}")
                all_passed = False

        print("sim_results: ", sim_results)
        sim_results = sim_results / np.linalg.norm(sim_results)
        print("sim results normalized: ", sim_results)

        

        print("qiskit_results: ", qiskit_results)
        dot_prod = np.dot(sim_results, qiskit_results)
        print("dot_prod: ", dot_prod)
        fidelity = np.abs(dot_prod) ** 2
        print(f"{filename} | in: {input_bits} | fidelity: {fidelity}")
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
    #get_prod("./circuits/qwalk_n4_it10.qasm", "0000", "0000")
    #get_prod("./circuits/qwalk_n4_it15.qasm", "0000", "0000")
    pass

def test_1_qubytes_it1(): #Pass
    test_all_params(n_mpi=4,
                    nr_qubytes=1,
                    input_hsv_file="./statevectors/ket0_size1.hsv",
                    qasm_file="./circuits/qwalk_n2_it1.qasm",
                    hexstrings_file="./hexstring_sets/nrhex256_size1_from0x0_to0x100.hs",
                    output_hsv_file="./outputs/size1HS.hsv",
                    all_params=False, fraction=1.0)

def test_n4_it10(): #Pass
    test_all_params(n_mpi=4,
                    nr_qubytes=1,
                    input_hsv_file="./statevectors/ket0_size1.hsv",
                    qasm_file="./circuits/qwalk_n4_it10.qasm",
                    hexstrings_file="./hexstring_sets/nrhex256_size1_from0x0_to0x100.hs",
                    output_hsv_file="./outputs/size1HS.hsv",
                    all_params=False, fraction=1.0)

def test_3_qubytes(): # About 30 sec for qiskit. Fails because different sizes.
    test_all_params(n_mpi=4,
                    nr_qubytes=3,
                    input_hsv_file="./statevectors/ket0_size3.hsv",
                    qasm_file="./circuits/qwalk_n4_it3.qasm",
                    hexstrings_file="./hexstring_sets/nrhex10_size3_from0x0_to0xA.hs",
                    output_hsv_file="./outputs/size3HS.hsv",
                    all_params=False, fraction=1.0)


if __name__ == "__main__":
    start = time.time()

    test_n4_it10()

    

    #exhaustive(all_params=True)
    #deep()

    #test_fidelity("./circuits/aa_n2_it1_mark1.qasm", 2, 0.5)
    #test_fidelity("./circuits/aa_n3_it3_mark1.qasm", 3, 0.5)

    end = time.time()
    print("Time elapsed in total: ", end - start, "s")

    #deep()
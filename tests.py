# Runs .qasm files with both ./sv_embedded and qiskit and calculates fidelity.

import subprocess
import sys
import numpy as np
import matplotlib.pyplot as plt
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
    cmd = ["mpirun", "-n", str(num_processes), "./sv_embedded_mpi.x", "-c", qasm_file, "-i", input_sv, "-o", output_sv, "-v", "3"]
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
    for line in result.stderr.splitlines():
        if not "mca_btl_tcp_proc_create_interface_graph" in line:
            print("STDERR:", line)
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
        # RX: rx(theta) q[0]
        elif line.startswith("rx"):
            gate, rest = line.split(" ", 1)
            theta = float(gate.split(")")[0].split("(")[1])
            
            print("Theta parsed as:", theta)
            q = int(rest.split("[")[1].split("]")[0])
            print("Qubit parsed as:", q)
            qc.rx(theta, q)
        # RY: ry(theta) q[0]
        elif line.startswith("ry"):
            gate, rest = line.split(" ", 1)
            theta = float(gate.split(")")[0].split("(")[1])
            q = int(rest.split("[")[1].split("]")[0])
            qc.ry(theta, q)
        # RZ: rz(theta) q[0]
        elif line.startswith("rz"):
            gate, rest = line.split(" ", 1)
            theta = float(gate.split(")")[0].split("(")[1])
            q = int(rest.split("[")[1].split("]")[0])
            qc.rz(theta, q)
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
    #print("sim_vector:", sim_vector) #TODO: Check why sim_vector is not already normalized
    #print("qiskit_vector:", qiskit_vector)
    sim_vector = sim_vector / np.linalg.norm(sim_vector)
    #print("Normalized sim_vector:", sim_vector)
    qiskit_vector = qiskit_vector / np.linalg.norm(qiskit_vector)
    dot_prod = np.dot(np.conj(sim_vector), qiskit_vector)
    fidelity = np.abs(dot_prod) ** 2
    return fidelity

def calculate_expectation_value(statevector, operator):
    #print("statevector: ", statevector)
    #print("statevector norm: ", np.linalg.norm(statevector))
    exp_val = np.vdot(statevector, operator @ statevector)
    return exp_val.real

# From the output of a quantum walk.
# qubit 0 is the coin qubit. The rest are position qubits.
# qubit 1 is the least significant bit of position.
def calculate_expected_position(statevector, n_qubits):
    #In each basis state, extract the position bits and calculate the expected position.
    n_position_qubits = n_qubits - 1
    expected_position = 0.0
    for i in range(2**n_qubits):
        amplitude = statevector[i]
        probability = np.abs(amplitude) ** 2
        position = 0
        for j in range(n_position_qubits):
            if (i >> (j+1)) & 1:
                position += 2**j
        #if probability > 1e-10:
            #print("state index:", i, "-> position:", position, "amplitude:", amplitude, "probability:", probability)
        expected_position += position * probability
    return expected_position

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
                value = value.replace('+-', '-')
                #print("Parsed line:", line.strip(), "-> index:", index, "value:", value)
                #print("Complex value as string:", value.strip())
                statevector[index] = complex(value.strip())
    return statevector

def test_fidelity(qasm_file, n_qubytes, fraction):
    fidelities = []
    runs = 1
    if (fraction < 2000.0):
        #Take average over multiple runs for better statistics
        runs = 10
    for i in range(runs):
        fidelity = 0
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
        fidelities.append(fidelity)
    fidelity = sum(fidelities) / len(fidelities)
    return fidelity

def test_expectation_value(qasm_file, n_qubytes, fraction, operator):
    input_sv = f"./statevectors/ket0_size{n_qubytes}.hsv"
    output_sv_sim = f"./outputs/sim_output_size{n_qubytes}.hsv"
    run_simulator(qasm_file, input_sv, output_sv_sim, num_processes=4, fraction=fraction)

    sim_vector = get_statevector_from_file(output_sv_sim, n_qubytes)
    #print("sim_vector:", sim_vector)

    qc = build_qiskit_circuit_from_custom_qasm(qasm_file)
    state = Statevector.from_int(0, 2**(n_qubytes*8))
    state = state.evolve(qc)
    qiskit_vector = state.data
    
    #print("qiskit_vector:", qiskit_vector)

    exp_val_sim = calculate_expectation_value(sim_vector, operator)
    exp_val_qiskit = calculate_expectation_value(qiskit_vector, operator)

    print(f"Expectation value from simulator: {exp_val_sim}")
    print(f"Expectation value from Qiskit: {exp_val_qiskit}")

    return exp_val_sim, exp_val_qiskit



def test_expected_position(qasm_file, n_qubytes, fraction, qiskit=True):
    start_position = 4
    input_sv = f"./statevectors/pos{start_position}_coin_super.hsv"

    if qiskit:
        qc = build_qiskit_circuit_from_custom_qasm(qasm_file)
        initial = np.zeros(2**(n_qubytes*8), dtype=complex)
        initial[start_position*2] = 1/np.sqrt(2)  # Coin |0>
        initial[start_position*2 + 1] = 1/np.sqrt(2) * 1j  # Coin |1>
        state = Statevector(initial)
        #print("Initial statevector:", state.data)
        #print("Evolving with Qiskit...")
        #print("Qiskit Circuit:\n", qc.draw())
        state = state.evolve(qc)
        qiskit_vector = state.data
        print("qiskit_vector:", qiskit_vector)
        expected_position_qiskit = calculate_expected_position(qiskit_vector, n_qubits=n_qubytes*8)
        #print(f"Expected position from Qiskit: {expected_position_qiskit}")
        return expected_position_qiskit
    else:
        output_sv_sim = f"./outputs/sim_output_size{n_qubytes}.hsv"
        run_simulator(qasm_file, input_sv, output_sv_sim, num_processes=4, fraction=fraction)
        sim_vector = get_statevector_from_file(output_sv_sim, n_qubytes)
        print("sim_vector:", sim_vector)
        expected_position_sim = calculate_expected_position(sim_vector, n_qubits=n_qubytes*8)
        #print(f"Expected position from simulator: {expected_position_sim}")
        return expected_position_sim
    

def test_imbalance(qasm_file, n_qubytes, fraction, qiskit=True):
    start_position = 4
    #input_sv = f"./statevectors/ket0_size1.hsv" #Note: Change below for qiskit also
    #input_sv = f"./statevectors/ket1_size1.hsv" #Note: Change below for qiskit also
    input_sv = f"./statevectors/ket_i.hsv" #Note: Change below for qiskit also

    if qiskit:
        qc = build_qiskit_circuit_from_custom_qasm(qasm_file)
        initial = np.zeros(2**(n_qubytes*8), dtype=complex)
        
        #ket0
        #initial[0] = 1
        
        #ket1
        #initial[1] = 1
        
        #ket i
        initial[0] = 1/np.sqrt(2)
        initial[1] = 1/np.sqrt(2) * 1j

        state = Statevector(initial)
        #print("Initial statevector:", state.data)
        #print("Evolving with Qiskit...")
        #print("Qiskit Circuit:\n", qc.draw())
        state = state.evolve(qc)
        qiskit_vector = state.data
        print("qiskit_vector:", qiskit_vector)
        expected_position_qiskit = calculate_expected_position(qiskit_vector, n_qubits=n_qubytes*8)
        #print(f"Expected position from Qiskit: {expected_position_qiskit}")
        return expected_position_qiskit
    else:
        output_sv_sim = f"./outputs/sim_output_size{n_qubytes}.hsv"
        run_simulator(qasm_file, input_sv, output_sv_sim, num_processes=4, fraction=fraction)
        sim_vector = get_statevector_from_file(output_sv_sim, n_qubytes)
        print("sim_vector:", sim_vector)
        expected_position_sim = calculate_expected_position(sim_vector, n_qubits=n_qubytes*8)
        #print(f"Expected position from simulator: {expected_position_sim}")
        return expected_position_sim
    
def fidelity_vs_f():
    #fractions = [100.0, 200.0, 300.0, 400.0, 1000.0, 4000.0, 5000.0, 10000.0, 50000.0, 100000.0, 500000.0, 1000000.0]
    #fractions = [1.0, 100.0, 200.0, 300.0, 400.0, 500.0, 600.0, 700.0, 800.0, 900.0, 1000.0]
    fractions = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 10.0]
    fidelities = []
    for f in fractions:
        print(f"Testing fidelity with fraction {f}")
        fidelity = test_fidelity("./circuits/qrng_n4.qasm", n_qubytes=1, fraction=f)
        fidelities.append(fidelity)
    for f, fid in zip(fractions, fidelities):
        print(f"Fraction: {f}, Fidelity: {fid}")
    # Plotting
    try:
        plt.plot(fractions, fidelities, marker='o')
        plt.xlabel('Fraction')
        plt.ylabel('Fidelity')
        plt.title('Fidelity vs Fraction')
        plt.grid(True)
        plt.savefig('fidelity_vs_fraction.png')
        plt.show()
    except ImportError:
        print("matplotlib not installed, skipping plot.")
        

def average_Z_first_qubits(total_qubits=8, active_qubits=4):
    Z = np.array([[1, 0], [0, -1]], dtype=complex)
    I = np.eye(2, dtype=complex)

    dim = 2**total_qubits
    operator = np.zeros((dim, dim), dtype=complex)

    for i in range(active_qubits):
        op = 1
        for q in range(total_qubits):
            if q == i:
                op = np.kron(op, Z)
            else:
                op = np.kron(op, I)
        operator += op

    return operator / active_qubits

def expectation_value_vs_f():
    fractions = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 100.0, 200.0]
    #fractions = [100.0, 200.0, 300.0, 400.0, 1000.0, 4000.0, 5000.0, 10000.0, 50000.0, 100000.0, 500000.0, 1000000.0]
    #fractions = [100.0]
    exp_vals_sim = []
    exp_vals_qiskit = []
    # Operator: Average of Z on all qubits
    n_qubits = 8
    n_qubytes = 1
    operator = average_Z_first_qubits(
        total_qubits=8 * n_qubytes,
        active_qubits=n_qubits
    )
    for f in fractions:
        print(f"Testing expectation value with fraction {f}")
        exp_val_sim, exp_val_qiskit = test_expectation_value("./circuits/qrng_n8.qasm", n_qubytes=1, fraction=f, operator=operator)
        exp_vals_sim.append(exp_val_sim)
        exp_vals_qiskit.append(exp_val_qiskit)
    for f, ev_sim, ev_qiskit in zip(fractions, exp_vals_sim, exp_vals_qiskit):
        print(f"Fraction: {f}, Exp Val Sim: {ev_sim}, Exp Val Qiskit: {ev_qiskit}")
    # Plotting
    try:
        plt.plot(fractions, exp_vals_sim, marker='o', label='Simulator')
        plt.plot(fractions, exp_vals_qiskit, marker='x', label='Qiskit')
        plt.xlabel('Fraction')
        plt.ylabel('Expectation Value')
        plt.title('Expectation Value vs Fraction')
        plt.legend()
        plt.grid(True)
        plt.savefig('expectation_value_vs_fraction.png')
        plt.show()
    except ImportError:
        print("matplotlib not installed, skipping plot.")

def expected_position_vs_f():
    #fractions = [1.0, 5.0, 7.0, 10.0, 100.0]
    fractions = [1000.0]
    
    circuit_file = "./circuits/qwalk_n4_it1_biased.qasm"
    
    average_over_runs = 1
    
    expected_positions_qiskit = []
    means_sim = []
    stds_sim = []
    vals_lst_sim = []
    
    for f in fractions:
        print(f"Testing expected position with fraction {f}")
        exp_pos_qiskit = test_expected_position(circuit_file, n_qubytes=1, fraction=f, qiskit=True)
        vals_sim = []
        for _ in range(average_over_runs):
            exp_pos_sim = test_expected_position(circuit_file, n_qubytes=1, fraction=f, qiskit=False)
            vals_sim.append(exp_pos_sim)
        expected_positions_qiskit.append(exp_pos_qiskit)
        means_sim.append(np.mean(vals_sim))
        stds_sim.append(np.std(vals_sim))
        vals_lst_sim.append(vals_sim)
    for f, pos_sim, std_sim, pos_qiskit in zip(fractions, means_sim, stds_sim, expected_positions_qiskit):
        print(f"Fraction: {f}, Expected Position Sim (mean): {pos_sim}, Expected Position Sim (std): {std_sim}, Expected Position Qiskit: {pos_qiskit}")
    # Plotting
    try:
        #Plot vals_lst_sim as dots
        for f, vals_sim in zip(fractions, vals_lst_sim):
            plt.scatter([f]*len(vals_sim), vals_sim, color='gray', alpha=0.5)
        #Plot mean and std
        
        plt.plot(fractions, means_sim, marker='o', label='Simulator Mean')
        plt.fill_between(fractions, np.array(means_sim) - np.array(stds_sim), np.array(means_sim) + np.array(stds_sim), alpha=0.2)
        plt.xlabel('Fraction')
        plt.ylabel('Expected Position')
        plt.title('Expected Position vs Fraction')
        plt.legend()
        plt.grid(True)
        plt.savefig('expected_position_vs_fraction.png')
        plt.show()
    except ImportError:
        print("matplotlib not installed, skipping plot.")
        
        
def imbalance():
    #fractions = [1.0, 5.0, 7.0, 10.0, 100.0]
    fractions = [10000000.0]
    
    circuit_file = "./circuits/rx_ry.qasm"
    
    average_over_runs = 1
    
    means_sim = []
    stds_sim = []
    vals_lst_sim = []
    
    for f in fractions:
        print(f"Testing expected position with fraction {f}")
        exp_pos_qiskit = test_imbalance(circuit_file, n_qubytes=1, fraction=f, qiskit=True)
        vals_sim = []
        for _ in range(average_over_runs):
            exp_pos_sim = test_imbalance(circuit_file, n_qubytes=1, fraction=f, qiskit=False)
            vals_sim.append(exp_pos_sim)
        means_sim.append(np.mean(vals_sim))
        stds_sim.append(np.std(vals_sim))
        vals_lst_sim.append(vals_sim)


def testing_average():
    n_qubytes = 1
    n_qubits = 8
    
    operator = average_Z_first_qubits(
        total_qubits=8 * n_qubytes,
        active_qubits=n_qubits
    )

    fractions = [0.01, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 2.0, 100.0, 200.0]
    average_over_runs = 5
    
    means = []
    stds = []

    for fraction in fractions:
        print(f"Testing expectation value with fraction {fraction} averaged over {average_over_runs} runs")

        vals = []
        for _ in range(average_over_runs):
            exp_val_sim, _ = test_expectation_value("./circuits/qrng_n8.qasm", n_qubytes=1, fraction=fraction, operator=operator)
            vals.append(exp_val_sim)

        means.append(np.mean(vals))
        stds.append(np.std(vals))

    for f, mean, std in zip(fractions, means, stds):
        print(f"Fraction: {f}, Exp Val Sim Mean: {mean}, Std: {std}")
        
    #Plotting
    try:
        plt.errorbar(fractions, means, yerr=stds, fmt='o', capsize=5)
        plt.xscale('log')
        plt.xlabel('Fraction')
        plt.ylabel('Expectation Value (Z average)')
        plt.title('Expectation Value vs Fraction with Error Bars')
        plt.grid(True)
        plt.savefig('expectation_value_vs_fraction_error_bars.png')
        plt.show()
    except ImportError:
        print("matplotlib not installed, skipping plot.")

if __name__ == "__main__":
    start = time.time()
    #run_simulator("./circuits/small.qasm", "./statevectors/ket0_size1.hsv", "./outputs/small_f1.0.hsv", num_processes=4, p=None, r=None, fraction=1.0, batch_size=None)

    #test_fidelity("./circuits/small.qasm", n_qubytes=1, fraction=100000.0)
    #test_fidelity("./circuits/qrng_n1.qasm", n_qubytes=1, fraction=100.0)
    #test_fidelity("./circuits/qrng_n4.qasm", n_qubytes=1, fraction=3000.0)
    #test_fidelity("./circuits/qrng_n8.qasm", n_qubytes=1, fraction=30000.0)
    #fidelity_vs_f()
    #expectation_value_vs_f()
    #test_fidelity("./circuits/rx_n1.qasm", n_qubytes=1, fraction=1000.0)
    # finally works

    #testing_average()
    
    #expected_position_vs_f()
    
    imbalance()
    
    end = time.time()
    print("Time elapsed in total: ", end - start, "s")

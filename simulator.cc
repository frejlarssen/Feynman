#include <unistd.h>
#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include "src/circuit.h"
#include <complex>
#include <cstdio>
#include <stdexcept>

using namespace std;

struct Options {
    string circuit_file;
    vector<bool> input_bits;
    vector<bool> output_bits;
};

const vector<bool> bit_array_from_string(const string& s) {
    vector<bool> bits(s.size());
    for (size_t i = 0; i < s.size(); i++) {
        if (s[i] == '1') {
            bits[s.size() -1 - i] = true;
        } else if (s[i] == '0') {
            bits[s.size() -1 - i] = false;
        } else {
            cerr << "Invalid bitstring!" << endl;
            exit(1);
        }
    }
    return bits;
}

const string string_from_bit_array(const vector<bool> bit_arr) {
    string str = "";
    for (int i = 0; i < bit_arr.size(); i++) {
        if (bit_arr[bit_arr.size()-1 - i]) {
            str += "q" + to_string(bit_arr.size()-1 - i) + "=1";
        } else {
            str += "q" + to_string(bit_arr.size()-1 - i) + "=0";
        }
    }
    return str;
}

Options get_options(int argc, char* argv[]) {
    Options opts;

    int k;

    auto to_int = [](const std::string& word) -> unsigned {
        return std::atoi(word.c_str());
    };

      while ((k = getopt(argc, argv, "c:d:k:p:r:i:o:t:v:z")) != -1) {
        switch (k) {
          case 'c':
            opts.circuit_file = optarg;
            break;
          case 'i': //Not necessary. We could leave to the user to initialize in circuit_file and always start at state |0>.
            opts.input_bits = bit_array_from_string(optarg);
            break;
          case 'o':
            opts.output_bits = bit_array_from_string(optarg);
            break;
          default:
            fprintf(stderr, "Usage: ./feynqft -c circuit_file -i input_bitstring -o output_bitstring\n");
            exit(1);
        }
      }
    return opts;
}

// If the gate is of a type where the target doesn't end internal wire, input and output is guaranteed to be the same.
// But in this case we also need to check for circuit input/output conflict.
struct Environemnt {
    vector<bool> ctrls;
    vector<bool> inputs; // Target input ordered as parameter list.
    vector<bool> outputs; // Target output
};

// Need to get the above.
// Special case: ctrl is on an internal wire defined both as circuit input and output. If they are the same, go for it.
// If they conflict, throw exception and catch (contribution = 0 from that history and all other histories.)

Environemnt get_environment(Gate gate, Options opts, int history) {
    int num_controls = gate_type_infos[gate.type].num_controls;
    int num_targets = gate_type_infos[gate.type].num_qubits - num_controls;
    Environemnt env = {vector<bool>(num_controls),
                       vector<bool>(num_targets),
                       vector<bool>(num_targets)};

    // Loop through control arguments
    for (int qparam = 0; qparam < num_controls; qparam++) {
        GateQubit arg_qubit = gate.qubits[qparam];
        if (arg_qubit.at_input && arg_qubit.at_output) { //Special case
            if (opts.input_bits[arg_qubit.wire] != opts.output_bits[arg_qubit.wire]) {
                throw std::logic_error("Conflicting input/output at wire " + to_string(arg_qubit.wire));
            }
        }

        if (arg_qubit.at_input) {
            //Here or in seperate function?
            env.ctrls.at(qparam) = opts.input_bits[arg_qubit.wire]; // Push pack would also work if it wasn't filled.
        } else if (arg_qubit.at_output) {
            env.ctrls.at(qparam) = opts.output_bits[arg_qubit.wire];
        } else {
            env.ctrls.at(qparam) = history >> gate.qubits[0].internal_index_out & 1;
        }
    }

    // Loop through target output arguments
    for (int param = num_controls; param < num_controls + num_targets; param++) {
        GateQubit arg_qubit = gate.qubits[param];

        if (arg_qubit.at_input && arg_qubit.at_output && !gate_type_infos[gate.type].breaks_internal_wire) { //Special case
            if (opts.input_bits[arg_qubit.wire] != opts.output_bits[arg_qubit.wire]) {
                printf("Throwing...\n");
                throw std::logic_error("Conflicting input/output at wire " + to_string(arg_qubit.wire));
            }
        }

        if (arg_qubit.at_output) {
            env.outputs.at(param - num_controls) = opts.output_bits[arg_qubit.wire];
        } else {
            env.outputs.at(param - num_controls) = history >> arg_qubit.internal_index_out & 1;
        }
    }

    if (!gate_type_infos[gate.type].breaks_internal_wire) {
        env.inputs = env.outputs;
    } else {
        // Loop through target input arguments
        //cout << "Loop through target input arguments\n";
        for (int param = num_controls; param < num_controls + num_targets; param++) {
            GateQubit arg_qubit = gate.qubits[param];

            if (arg_qubit.at_input) {
                env.inputs.at(param - num_controls) = opts.input_bits[arg_qubit.wire];
            } else {
                env.inputs.at(param - num_controls) = history >> (arg_qubit.internal_index_out + 1) & 1;
            }
        }
    }

    return env;
}

complex <float> simulate(Options opts) {
    const int num_internal_wires = Circuit::num_internal_wires;

    cout << "Number of internal wires: " << num_internal_wires << "\n";

    complex <float> total_amplitude = 0.0;
    complex <float> contribution;
    // TODO: OpenMP. (GPU/CUDA?)
    for (u_int64_t history = 0; history < u_int64_t(1) << num_internal_wires; history++) {
        cout << "History: " << history << "\n";
        contribution = 1.0;
        for (const Gate& gate : Circuit::gates) {
            cout << gate_type_to_string(gate.type) << " activates\n";

            Environemnt env = get_environment(gate, opts, history);

            switch (gate.type) {
            case HADAMARD:
                if (env.inputs[0] && env.outputs[0]) {
                    contribution *= -1.0 / sqrt(2.0);
                } else {
                    contribution *= 1.0 / sqrt(2.0);
                }
                break;
            case CNOT:
                if (env.ctrls[0]) { // NOT
                    printf("Control activates negation\n");
                    if (env.inputs[0] == env.outputs[0]) {
                        contribution = 0;
                    }
                    // Otherwise, accepts
                } else { // Identity
                    printf("Control activates identity\n");
                    if (env.inputs[0] != env.outputs[0]) {
                        contribution = 0; // Denies
                    }
                    // Otherwise, accepts
                }
                break;
            case CPHASE:
                if (env.inputs[0] != env.outputs[0]) {
                    contribution *= 0.0;
                }
                else if (env.ctrls[0] && env.inputs[0]) {
                    contribution *= std::exp(complex<float>(0.0, gate.params[0]));
                }
                else {
                    contribution *= 1.0;
                }
                break;
            case SWAP:
                if (env.inputs[0] == env.outputs[1] && env.inputs[1] == env.outputs[0]) {
                    contribution *= 1.0;
                } else {
                    contribution *= 0.0;
                }
                break;
            default:
                cerr << "Gate not implemented!" << endl;
                exit(1);
            }
            printf("Contribution after %s application: %f + i%f\n", gate_type_to_string(gate.type).c_str(), contribution.real(), contribution.imag());

        }
        std::printf("Contribution from history %lu: %f + i%f\n", history, contribution.real(), contribution.imag());
        total_amplitude += contribution;
    }

    printf("Total amplitude: %f + i%f\n", total_amplitude.real(), total_amplitude.imag());
    return total_amplitude;
}

int main(int argc, char* argv[]) {

    Options opts = get_options(argc, argv);

    Circuit::parse_circuit(opts.circuit_file);

    Circuit::build_gate_list();

    printf("Gates:\n");
    for (int i = 0; i < Circuit::gates.size(); i++){
        printf("\t%s\n", gate_to_string(Circuit::gates[i]).c_str());
    }

    printf("Number of internal wires: %d\n", Circuit::num_internal_wires);

    simulate(opts);
    return 0;
}
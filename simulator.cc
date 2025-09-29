#include <unistd.h>
#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include <complex>
#include <cstdio>
#include <stdexcept>
#include "src/circuit.h"
#include "src/utils.h"

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

    const char* helpstr = "Usage: ./feynqft -c circuit_file -i input_bitstring -o output_bitstring\n";

    if (argc < 4) {
        cout << helpstr;
        exit(1);
    }

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
            cout << helpstr;
            exit(1);
        }
    }
    return opts;
}

#pragma omp declare reduction( \
    complex_add : std::complex<float> : omp_out += omp_in) \
    initializer(omp_priv = std::complex<float>(0,0))

complex <float> simulate(Circuit base_circ, Options opts) {
    const int num_artificial = Circuit::num_artificial;

    // Set values of those reached from natural
    // Implement similarly as FakeRun

    // Both R->L and L->R to make sure to set those reached from output and input.
    // Takes x2 time for each history, but in return we have more reach from natural
    // sources, less artificial sources and exponentially less histories.


    if (!Circuit::right_to_left_natural(base_circ, opts.input_bits, opts.output_bits)) {
        // Input and output not compatible with deterministic gates
        return 0.0;
    }

    complex <float> total_amplitude = 0.0;

    auto simulate_start = get_time();
    duration<double> total_coretime_deep_copy = zero_duration();
    duration<double> total_coretime_after_deep_copy = zero_duration();
    // With n=16, about x3 speedup with openmp compared to without
    #pragma omp parallel for reduction(complex_add : total_amplitude)
    for (u_int64_t history = 0; history < u_int64_t(1) << num_artificial; history++) {
        //cout << "History " << history << endl;

        auto start_deep_copy = get_time();
        Circuit circ = base_circ.deep_copy(); // Implement deep_copy() in Circuit
        auto end_deep_copy = get_time();
        total_coretime_deep_copy += get_duration(start_deep_copy, end_deep_copy);

        auto start_after_deep_copy = get_time();

        for (const std::shared_ptr<InternalWire>& w : circ.artificial_sources) {
            w->val = history >> w->artificial & 1;
            w->val_set = true;
        }

        // TODO: Make a real run setting the values of all internal wires.
        // We only need to iterate a vector of all deterministic, wire-breaking gates!

        if (!Circuit::right_to_left_artificial(circ, history)) {
            // Input, output and artificial not compatible with deterministic gates
            continue;
        }

//        printf("Gates after aftifical pass:\n");
//        for (int i = 0; i < circ.gates.size(); i++){
//            printf("  %s\n", gate_to_string(*circ.gates[i]).c_str());
//        }

        // Then we need to iterate all to calculate contribution.

        complex <float> contribution = 1.0;
        for (const shared_ptr<Gate>& gateptr : circ.gates) {
            Gate& gate = *gateptr;

            int num_ctrl = gate.num_controls;

            // Check if the gate is activated
            bool activate = true;
            for (int c = 0; c < num_ctrl; c++) {
                // wire_right or wire_left doesn't matter for controls
                if (!gate.qubits[c]->wire_right->val) {
                    activate = false;
                    break;
                }
            }

            if (!activate) {
                // Compare if input = output
                bool accept = true;
                for (int t = num_ctrl; t < num_ctrl + gate_type_infos[gate.type].num_targets; t++) {
                    if (gate.qubits[t]->wire_left->val != gate.qubits[t]->wire_right->val) {
                        accept = false;
                        break;
                    }
                }
                if (!accept) {
                    contribution = 0; // TODO: Here we could break out of both loops.
                }
                continue; // Go on to the next gate.
            }

            // Activate gate
            switch (gate.type) {
            case HADAMARD:
                if (gate.qubits[num_ctrl]->wire_left->val && gate.qubits[num_ctrl]->wire_right->val) {
                    contribution *= -1.0 / sqrt(2.0);
                } else {
                    contribution *= 1.0 / sqrt(2.0);
                }
                break;
            case NOT:
                if (gate.qubits[num_ctrl]->wire_left->val == gate.qubits[num_ctrl]->wire_right->val) {
                    contribution = 0;
                }
                break;
            case PHASE:
                if (gate.qubits[num_ctrl]->wire_left->val != gate.qubits[num_ctrl]->wire_right->val) {
                    contribution *= 0.0;
                }
                else if (gate.qubits[num_ctrl]->wire_left->val) {
                    contribution *= std::exp(complex<float>(0.0, gate.params[0]));
                }
                break;
            case SWAP:
                if (gate.qubits[num_ctrl]->wire_left->val == gate.qubits[num_ctrl+1]->wire_right->val &&
                    gate.qubits[num_ctrl+1]->wire_left->val == gate.qubits[num_ctrl]->wire_right->val) {
                    contribution *= 1.0;
                } else {
                    contribution *= 0.0;
                }
                break;
            case PAULIZ:
                if (gate.qubits[num_ctrl]->wire_left->val != gate.qubits[num_ctrl]->wire_right->val) {
                    contribution *= 0.0;
                }
                else if (gate.qubits[num_ctrl]->wire_left->val) {
                    contribution *= -1;
                }
                break;
            default:
                cerr << "Gate not implemented!" << endl;
                exit(1);
            }
            //printf("Contribution after %s application: %f + i%f\n", gate_type_to_string(gate.type).c_str(), contribution.real(), contribution.imag());

        }
        //std::printf("Contribution from history %lu: %f + i%f\n", history, contribution.real(), contribution.imag());
        total_amplitude += contribution;

        auto end_after_deep_copy = get_time();
        total_coretime_after_deep_copy = end_after_deep_copy - start_after_deep_copy;
    }
    cout << "Total core time deep_copy: " << duration_to_double(total_coretime_deep_copy) << " s" << endl;
    cout << "Total core time after deep_copy: " << duration_to_double(total_coretime_after_deep_copy) << " s" << endl;

    auto simulate_end = get_time();
    cout << "Total clock time simulate: " << duration_to_double(simulate_start, simulate_end) << " s" << endl;

    return total_amplitude;
}

int main(int argc, char* argv[]) {

    Options opts = get_options(argc, argv);

    Circuit::parse_circuit(opts.circuit_file);

    Circuit base_circ = Circuit::build_circuit();

//    printf("Gates after build:\n");
//    for (int i = 0; i < base_circ.gates.size(); i++){
//        printf("  %s\n", gate_to_string(*base_circ.gates[i]).c_str());
//    }

    printf("Number of artificial sources: %d\n", Circuit::num_artificial);
    complex<float> amp = simulate(base_circ, opts);
    printf("Total amplitude: %f + i%f\n", amp.real(), amp.imag());
    return 0;
}
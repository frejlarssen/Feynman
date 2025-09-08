#include <unistd.h>
#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include "src/circuit_qft.h"
#include <complex>
#include <cstdio>

using namespace std;

struct Options {
    string input_bitstring;
    string output_bitstring;
    //string input_circuit;
};

Options get_options(int argc, char* argv[]) {
    Options opts;

    int k;

    auto to_int = [](const std::string& word) -> unsigned {
        return std::atoi(word.c_str());
    };

      while ((k = getopt(argc, argv, "c:d:k:p:r:i:o:t:v:z")) != -1) {
        switch (k) {
          //case 'c':
          //  opts.circuit_file = optarg;
          //  break;
          case 'i':
            opts.input_bitstring = optarg;
            break;
          case 'o':
            opts.output_bitstring = optarg;
            break;
          default:
            fprintf(stderr, "Usage: ./feynqft -i input_bitstring -o output_bitstring\n");
            exit(1);
        }
      }
    return opts;
}

bool lookup_intenal_wire(int history, int wire, int internal_index) {
    return (history >> wire * (2*NUM_QUBITS - wire + 1 ) / 2 + internal_index ) & 1;}

const vector<bool> bit_array_from_string(const string& s) {
    vector<bool> bits(s.size());
    for (size_t i = 0; i < s.size(); i++) {
        if (s[i] == '1') {
            bits[i] = true;
        } else if (s[i] == '0') {
            bits[i] = false;
        } else {
            cerr << "Invalid bitstring!" << endl;
            exit(1);
        }
    }
    return bits;
}

int main(int argc, char* argv[]) {

    Options opts = get_options(argc, argv);
    cout << "Input bitstring: " << opts.input_bitstring << "\n";
    cout << "Output bitstring: " << opts.output_bitstring << "\n";

    //for (const Gate& gate : Circuit::gates) {
    //    cout << "Gate type: " << gate.type << ", acting on qubits: ";
    //    for (const GateQubit& gq : gate.qubits) {
    //        cout << "(wire: " << gq.wire << ", index: " << gq.internal_index_in << ", control: " << gq.is_control << ") ";
    //    }
    //    cout << "\n";
    //}

    const vector<bool> input_bits = bit_array_from_string(opts.input_bitstring);
    const vector<bool> output_bits = bit_array_from_string(opts.output_bitstring);

    const int num_internal_wires = NUM_QUBITS * (NUM_QUBITS + 1) / 2;

    cout << "Number of internal wires: " << num_internal_wires << "\n";

    complex <float> total_amplitude = 0.0;
    complex <float> contribution;
    //OpenMP
    for (u_int64_t history = 0; history < u_int64_t(1) << num_internal_wires; history++) {
        //cout << "History: " << history << "\n";
        contribution = 1.0;
        for (const Gate& gate : Circuit::gates) {
            //cout << gate_type_to_string(gate.type) << " activates\n";
            switch (gate.type) {
            case HADAMARD:
                bool input_bit;
                bool output_bit;

                if (gate.qubits[0].at_input) {
                    input_bit = input_bits[gate.qubits[0].wire];
                } else {
                    input_bit = history >> gate.qubits[0].global_index & 1;
                }

                if (gate.qubits[0].at_output) {
                    output_bit = output_bits[gate.qubits[0].wire];
                } else {
                    output_bit = history >> gate.qubits[0].global_index - 1 & 1;
                }

                if (input_bit && output_bit) {
                    contribution *= -1.0 / sqrt(2.0);
                    } else {
                    contribution *= 1.0 / sqrt(2.0);
                }
                break;
            case CPHASE:
                bool control_bit;
                bool target_input_bit;
                bool target_output_bit;

                if (gate.qubits[0].at_input && gate.qubits[0].at_output) {
                    if (input_bits[gate.qubits[0].wire] != output_bits[gate.qubits[0].wire]) {
                        contribution *= 0.0;
                        break;
                    }
                    else {
                        control_bit = input_bits[gate.qubits[0].wire];
                    }
                } else if (gate.qubits[0].at_input) {
                    control_bit = input_bits[gate.qubits[0].wire];
                }
                else if (gate.qubits[0].at_output) {
                    control_bit = output_bits[gate.qubits[0].wire];
                }
                else {
                    control_bit = history >> gate.qubits[0].global_index & 1;
                }

                if (gate.qubits[1].at_input) {
                    target_input_bit = input_bits[gate.qubits[1].wire];
                } else {
                    target_input_bit = history >> gate.qubits[1].global_index & 1;
                }

                if (gate.qubits[1].at_output) {
                    target_output_bit = output_bits[gate.qubits[1].wire];
                } else {
                    target_output_bit = history >> gate.qubits[1].global_index - 1 & 1;
                }

                if (target_input_bit != target_output_bit) {
                    contribution *= 0.0;
                }
                else if (control_bit) {
                    contribution *= std::exp(complex<float>(0.0, gate.parameter));
                }
                else {
                    contribution *= 1.0;
                }

                break;
            case SWAP:
                bool bit1_input;
                bool bit1_output;
                bool bit2_input;
                bool bit2_output;
                if (gate.qubits[0].at_input) {
                    bit1_input = input_bits[gate.qubits[0].wire];
                } else {
                    bit1_input = history >> gate.qubits[0].global_index & 1;
                }
                if (gate.qubits[0].at_output) {
                    bit1_output = output_bits[gate.qubits[0].wire];
                } else {
                    bit1_output = history >> gate.qubits[0].global_index - 1 & 1;
                }

                if (gate.qubits[1].at_input) {
                    bit2_input = input_bits[gate.qubits[1].wire];
                } else {
                    bit2_input = history >> gate.qubits[1].global_index & 1;
                }
                if (gate.qubits[1].at_output) {
                    bit2_output = output_bits[gate.qubits[1].wire];
                } else {
                    bit2_output = history >> gate.qubits[1].global_index - 1 & 1;
                }

                if (bit1_input == bit2_output && bit2_input == bit1_output) {
                    contribution *= 1.0;
                } else {
                    contribution *= 0.0;
                }
                break;
            default:
                cerr << "Unknown gate type!" << endl;
                exit(1);
            }
            //printf("Contribution after %s application: %f + i%f\n", gate_type_to_string(gate.type).c_str(), contribution.real(), contribution.imag());

        }
        //printf("Contribution from history %lu: %f + i%f\n", history, contribution.real(), contribution.imag());
        total_amplitude += contribution;
    }

    printf("Total amplitude: %f + i%f\n", total_amplitude.real(), total_amplitude.imag());

    return 0;
}
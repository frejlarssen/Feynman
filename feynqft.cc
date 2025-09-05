#include <unistd.h>
#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include "src/circuit.h"
#include <complex>

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
    return (history >> wire * (2*NUM_QUBITS - wire + 1 ) / 2 + internal_index ) & 1;

int main(int argc, char* argv[]) {

    Options opts = get_options(argc, argv);
    cout << "Input bitstring: " << opts.input_bitstring << "\n";
    cout << "Output bitstring: " << opts.output_bitstring << "\n";

    for (const Gate& gate : Circuit::gates) {
        cout << "Gate type: " << gate.type << ", acting on qubits: ";
        for (const GateQubit& gq : gate.qubits) {
            cout << "(wire: " << gq.wire << ", index: " << gq.internal_index << ", control: " << gq.is_control << ") ";
        }
        cout << "\n";
    }

    const int num_internal_wires = NUM_QUBITS * (NUM_QUBITS + 1) / 2;

    complex <float> total_amplitude = 0.0;
    complex <float> contribution;
    for (int history = 0; history < 1 << num_internal_wires; history++) {
        cout << "History: " << history << "\n";
        contribution = 1.0;
        for (const Gate& gate : Circuit::gates) {
            cout << "  Gate type: " << gate.type << " activates\n";
            switch (gate.type) {
            case HADAMARD:
                if (lookup_intenal_wire(history, gate.qubits[0].wire, gate.qubits[0].internal_index) && 
                    lookup_intenal_wire(history, gate.qubits[0].wire, gate.qubits[0].internal_index - 1)):
                    contribution *= 1.0 / sqrt(2.0);
                break;
            case CPHASE:
                break;
            case SWAP:
                break;
            default:
                cerr << "Unknown gate type!" << endl;
                exit(1);
            }
            if (gate.type == HADAMARD) {
                
            } else if (gate.type == CPHASE) {
                contribution *= 1.0; // Placeholder for actual phase factor
            } else if (gate.type == SWAP) {
                contribution *= 1.0; // Placeholder for actual swap factor
            }
        }
    }

    return 0;
}
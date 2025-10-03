#include <unistd.h>
#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include <complex>
#include <cstdio>
#include <stdexcept>
#include "src/circuit.h"

using namespace std;

struct Options {
    string circuit_file;
    vector<bool> input_bits;
    vector<bool> output_bits;
    int num_chunk1 = 0;
    int num_chunk2 = 0;
};

const vector<bool> bit_array_from_string(const string& s) {
    vector<bool> bits(s.size());
    for (size_t i = 0; i < s.size(); i++) {
        if (s.at(i) == '1') {
            bits.at(s.size() -1 - i) = true;
        } else if (s.at(i) == '0') {
            bits.at(s.size() -1 - i) = false;
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
        if (bit_arr.at(bit_arr.size()-1 - i)) {
            str += "q" + to_string(bit_arr.size()-1 - i) + "=1";
        } else {
            str += "q" + to_string(bit_arr.size()-1 - i) + "=0";
        }
    }
    return str;
}

Options get_options(int argc, char* argv[]) {
    Options opts;

    const char* helpstr = "Usage: ./feynqft -c circuit_file -i input_bitstring -o output_bitstring -p num_chunk1 -r num_chunk2\n";

    if (argc < 4) {
        cout << helpstr;
        exit(1);
    }

    int k;

    auto to_int = [](const std::string& word) -> unsigned {
        return std::atoi(word.c_str());
    };

    //cout << "Parsing options" << endl;
    //cout << "argc: " << argc << endl;
    //cout << "argv: ";
    for (int i = 0; i < argc; i++) {
        cout << argv[i] << " ";
    }
    cout << endl;

    while ((k = getopt(argc, argv, "c:i:o:p:r:")) != -1) {
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
          case 'p':
            opts.num_chunk1 = to_int(optarg);
            break;
          case 'r':
            opts.num_chunk2 = to_int(optarg);
            break;
          default:
            cout << helpstr;
            exit(1);
        }
    }
    return opts;
}

complex<float> chunk_contribution(const Chunk& chunk, u_int64_t thread/*, std::ostringstream& buf_history*/) {
    complex <float> contribution = 1.0;
    for (const shared_ptr<Gate>& gateptr : chunk.gates) {
        Gate& gate = *gateptr;

        //cout << "Calculating contribution from gate " << gate_to_string(gate, 2) << endl;

        int num_ctrl = gate.num_controls;

        // Check if the gate is activated
        bool activate = true;
        for (int c = 0; c < num_ctrl; c++) {
            // wire_right or wire_left doesn't matter for controls
            if (!gate.qubits.at(c)->wire_right->get_val(thread)) {
                activate = false;
                break;
            }
        }

        if (!activate) {
            //cout << "  Gate not activated." << endl;
            // Compare if input = output
            bool accept = true;
            for (int t = num_ctrl; t < num_ctrl + gate_type_infos.at(gate.type).num_targets; t++) {
                if (gate.qubits.at(t)->wire_left->get_val(thread) != gate.qubits.at(t)->wire_right->get_val(thread)) {
                    accept = false;
                    break;
                }
            }
            if (!accept) {
                contribution = 0; // TODO: Here we could break out of both loops.
            }
            continue; // Go on to the next gate.
        }


        uint8_t left_val;
        uint8_t right_val;
        // Activate gate
        switch (gate.type) {
        case HADAMARD:
            if (gate.qubits.at(num_ctrl)->wire_left->get_val(thread) &&
                gate.qubits.at(num_ctrl)->wire_right->get_val(thread)) {
                contribution *= -1.0 / sqrt(2.0);
            } else {
                contribution *= 1.0 / sqrt(2.0);
            }
            //cout << "  Hadamard gate done." << endl;
            break;
        case NOT:
            //cout << "  NOT gate activated." << endl;
            if (gate.qubits.at(num_ctrl)->wire_left->get_val(thread) ==
                gate.qubits.at(num_ctrl)->wire_right->get_val(thread)) {
                contribution = 0;
            }
            break;
        case PHASE:
            //cout << "  PHASE gate activated." << endl;
            if (gate.qubits.at(num_ctrl)->wire_left->get_val(thread) !=
                gate.qubits.at(num_ctrl)->wire_right->get_val(thread)) {
                contribution *= 0.0;
            }
            else if (gate.qubits.at(num_ctrl)->wire_left->get_val(thread)) {
                contribution *= std::exp(complex<float>(0.0, gate.params.at(0)));
            }
            break;
        case SWAP:
            if (gate.qubits.at(num_ctrl)->wire_left->get_val(thread) ==
                gate.qubits.at(num_ctrl+1)->wire_right->get_val(thread)
                &&
                gate.qubits.at(num_ctrl+1)->wire_left->get_val(thread) ==
                gate.qubits.at(num_ctrl)->wire_right->get_val(thread)
                ) {
                contribution *= 1.0;
            } else {
                contribution *= 0.0;
            }
            break;
        case PAULIZ:
            if (gate.qubits.at(num_ctrl)->wire_left->get_val(thread) !=
                gate.qubits.at(num_ctrl)->wire_right->get_val(thread)) {
                contribution *= 0.0;
            }
            else if (gate.qubits.at(num_ctrl)->wire_left->get_val(thread)) {
                contribution *= -1;
            }
            break;
        default:
            cerr << "Gate not implemented!" << endl;
            exit(1);
        }
        printf("Contribution after %s application: %f + i%f\n", gate_type_to_string(gate.type).c_str(), contribution.real(), contribution.imag());
        //fprintf_stream(buf_history, "Contribution after %s application: %f + i%f\n", gate_type_to_string(gate.type).c_str(), contribution.real(), contribution.imag());
    }
    return contribution;
}

//#pragma omp declare reduction( \
//    complex_add : std::complex<float> : omp_out += omp_in) \
//    initializer(omp_priv = std::complex<float>(0,0))

complex <float> simulate(Options opts, std::ostringstream& buf, int verbosity = 0) {
    // Set values of those reached from natural
    // Implement similarly as FakeRun

    // Both R->L and L->R to make sure to set those reached from output and input.
    // Takes x2 time for each history, but in return we have more reach from natural
    // sources, less artificial sources and exponentially less histories.


    cout << "In simulate" << endl;

    // One for each chunk, one for the wires that starts in INPUT, and one for OUTPUT.
    //array<u_int64_t, NUM_CHUNKS+2> histories = {0, 0, 0, 0, 0};

    for (const std::shared_ptr<InternalWire>& w : Circuit::output_sources) {
        printf("Setting output wire: %s\n", internal_wire_to_string(w, 2).c_str());
        w->set_safe_all(1, opts.output_bits.at(w->wire));
        printf("After setting output wire: %s\n", internal_wire_to_string(w, 2).c_str());
    }

    //cout << "Output set." << endl;

    for (const std::shared_ptr<InternalWire>& w : Circuit::input_sources) {
        if (!w->set_safe_all(1, opts.input_bits.at(w->wire))) { return false; }
    }

    cout << "Output and input set." << endl;


    printf("Gates after output and input set:\n");
    for (Chunk chunk : Circuit::chunks) {
        printf("Chunk %d\n:", chunk.id);
        for (shared_ptr<Gate>& gate : chunk.gates) {
            printf("%s\n", gate_to_string(*gate, 2).c_str());
        }
    }
    

    complex <float> total_amplitude = 0.0;

    auto simulate_start = get_time();
    duration<double> total_coretime_history2 = zero_duration();

    Chunk& chunk2 = Circuit::chunks.at(2);
    const int num_artificial2 = chunk2.num_artificial;
    printf("Number of artificial sources in chunk 2: %d\n", num_artificial2);

    if (!chunk2.right_to_left_natural_all(1 << num_artificial2)) {
        return 0.0;
    }

    // With n=16, about x3 speedup with openmp compared to without
//    #pragma omp parallel for reduction(complex_add : total_amplitude)
    for (u_int64_t history2 = 0; history2 < u_int64_t(1) << num_artificial2; history2++) {
        u_int64_t thread = history2;
        cout << "In history2: " << history2 << endl;
        //histories.at(2) = history2;

        //std::ostringstream buf_history; // Uncomment these to debug
        //fprintf_stream(buf_history, "History: %d\n", history);

        auto start_history2 = get_time();

        // TODO: Make a real run setting the values of all internal wires.
        // We only need to iterate a vector of all deterministic, wire-breaking gates!
        
        if (!chunk2.right_to_left_vals(history2, thread/*, buf_history*/)) {
            // Input, output and artificial not compatible with deterministic gates
            std::printf("    Vals pass rejected history --%ld.\n", history2);
            continue;
        }

        cout << "    Chunk2 Artificial pass done." << endl;

//        printf("Gates after aftifical pass:\n");
//        for (int i = 0; i < circ.gates.size(); i++){
//            printf("  %s\n", gate_to_string(*circ.gates.at(i)).c_str());
//        }

        // Then we need to iterate all to calculate contribution.

        complex <float> contribution2 = chunk_contribution(chunk2, thread/*, buf_history*/);
        
        // --0 means the gates in chunk2 with C2 history 0.
        std::printf("Contribution from history --%ld: %f + i%f\n", history2, contribution2.real(), contribution2.imag());


        Chunk& chunk1 = Circuit::chunks.at(1);
        const int num_artificial1 = chunk1.num_artificial;
        printf("  Number of artificial sources in chunk 2: %d\n", num_artificial1);

        for (u_int64_t history1 = 0; history1 < u_int64_t(1) << num_artificial1; history1++) {
            cout << "  In history1: " << history1 << endl;
            //histories.at(1) = history1;

            chunk1.reset_values();

            if (!chunk1.right_to_left_vals(history1, thread/*, buf_history*/)) {
                std::printf("    Vals pass rejected history -%ld%ld.\n", history1, history2);
                continue;
            }

            printf("Gates after vals pass of chunk 1:\n");
            for (int i = 0; i < chunk1.gates.size(); i++){
                printf("  %s\n", gate_to_string(*chunk1.gates.at(i), 2).c_str());
            }

            complex <float> contribution1 = contribution2 * chunk_contribution(chunk1, thread/*, buf_history*/);

            std::printf("  Contribution from history -%ld%ld: %f + i%f\n", history1, history2, contribution1.real(), contribution1.imag());

            Chunk& chunk0 = Circuit::chunks.at(0);
            const int num_artificial0 = chunk0.num_artificial;
            printf("    Number of artificial sources in chunk 0: %d\n", num_artificial0);

            

            //printf("    Chunk0 Gates after natural pass:\n");
            //for (shared_ptr<Gate>& gate : chunk0.gates) {
            //    printf("    %s\n", gate_to_string(*gate, 2).c_str());
            //}

            for (u_int64_t history0 = 0; history0 < u_int64_t(1) << num_artificial0; history0++) {
                cout << "    In history0: " << history0 << endl;

                chunk0.reset_values();

                //printf("    Gates in chunk 0 before vals pass in history -%ld%ld:\n", history1, history2);
                //for (shared_ptr<Gate>& gate : chunk0.gates) {
                //    printf("    %s\n", gate_to_string(*gate, 2).c_str());
                //}

                //histories.at(0) = history0;

                if (!chunk0.right_to_left_vals(history0, thread/*, buf_history*/)) {
                    std::printf("    Artificial pass rejected history %ld%ld%ld.\n", history0, history1, history2);
                    continue;
                }

                //cout << "    Chunk0 Artificial pass done." << endl;

                complex <float> contribution0 = contribution1 * chunk_contribution(chunk0, thread/*, buf_history*/);

                std::printf("    Contribution from history %ld%ld%ld: %f + i%f\n", history0, history1, history2, contribution0.real(), contribution0.imag());
                total_amplitude += contribution0;
            }
            std::printf("  Contribution from history A%ld%ld: %f + i%f\n", history1, history2, contribution1.real(), contribution1.imag());
        }
        std::printf("Contribution from history AA%ld: %f + i%f\n", history2, contribution2.real(), contribution2.imag());

        auto end_history2 = get_time();
        total_coretime_history2 = end_history2 - start_history2;
    }
    if (verbosity > 2) {
        cout << "Total core time history2's: " << duration_to_double(total_coretime_history2) << " s" << endl;
    }

    auto simulate_end = get_time();
    if (verbosity > 2) {
        cout << "Total clock time simulate: " << duration_to_double(simulate_start, simulate_end) << " s" << endl;
    }

    return total_amplitude;
}

int main(int argc, char* argv[]) {

    Options opts = get_options(argc, argv);

    ParsedCircuit::parse_circuit(opts.circuit_file);

    //printf("Parsed circuit:\n");
    //printf("  %s\n", ParsedCircuit::parsed_circuit_to_string().c_str());

    Circuit::build_circuit(opts.num_chunk1, opts.num_chunk2);

    printf("Gates after build:\n");
    for (int i = 0; i < NUM_CHUNKS; i++) {
        printf("Chunk %d with %d artificial sources:\n", i, Circuit::chunks.at(i).num_artificial);
        for (const shared_ptr<Gate>& gate: Circuit::chunks.at(i).gates) {
            printf("  %s\n", gate_to_string(*gate, 2).c_str());
        }
    }

    printf("Output wires after build:\n");
    for (shared_ptr<InternalWire>& iw : Circuit::output_sources) {
        printf("%s\n", internal_wire_to_string(iw, 2).c_str());
    }

    std::ostringstream buf;

    complex<float> amp = simulate(opts, buf, 3);
    printf("Total amplitude: %f + i%f\n", amp.real(), amp.imag());
    return 0;
}
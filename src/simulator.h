#include <unistd.h>
#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include <complex>
#include <cstdio>
#include <stdexcept>
#include <thread>
#include <atomic>
#include <cstdlib>
#include <mutex>	
#include "src/circuit.h"
#include "src/parallel_for.h"

#define fLIMIT 0.9999999

using namespace std;

struct Options {
    string circuit_file;
    vector<bool> input_bits;
    vector<bool> output_bits;
    int num_chunk1 = -1;
    int num_chunk2 = -1;
    float fraction = 1.0;
    bool only_build = false;
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

    const char* helpstr = "Usage: ./feynqft -c circuit_file -i input_bitstring -o output_bitstring -p num_chunk1 -r num_chunk2 (-B)\n";

    if (argc < 4) {
        cout << helpstr;
        exit(1);
    }

    int k;

    auto to_int = [](const std::string& word) -> unsigned {
        return std::atoi(word.c_str());
    };

    auto to_float = [](const std::string& word) -> float {
        return std::atof(word.c_str());
    };

    //cout << "Parsing options" << endl;
    //cout << "argc: " << argc << endl;
    //cout << "argv: ";
    for (int i = 0; i < argc; i++) {
        cout << argv[i] << " ";
    }
    cout << endl;

    while ((k = getopt(argc, argv, "c:i:o:p:r:f:B")) != -1) {
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
            opts.num_chunk2 = to_int(optarg);
            break;
          case 'r':
            opts.num_chunk1 = to_int(optarg);
            break;
          case 'f':
            cout << "f optarg: " << optarg << endl;
            opts.fraction = to_float(optarg);
            printf("opts.fraction: %f\n", opts.fraction);
            cout << "opts.fraction: " << opts.fraction << endl;
            break;
          case 'B':
            opts.only_build = true;
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
            left_val = gate.qubits.at(num_ctrl)->wire_left->get_val(thread);
            right_val = gate.qubits.at(num_ctrl)->wire_right->get_val(thread);
            if (left_val &&
                right_val) {
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
        //printf("Contribution after %s application with id %d: %f + i%f\n", gate_type_to_string(gate.type).c_str(), gate.id, contribution.real(), contribution.imag());
        //fprintf_stream(buf_history, "Contribution after %s application: %f + i%f\n", gate_type_to_string(gate.type).c_str(), contribution.real(), contribution.imag());
    }
    return contribution;
}

// 4 warnings in total when introducing this one.
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
        w->set_safe_all(1, opts.output_bits.at(w->wire));
    }

    //cout << "Output set." << endl;

    for (const std::shared_ptr<InternalWire>& w : Circuit::input_sources) {
        if (!w->set_safe_all(1, opts.input_bits.at(w->wire))) { return false; }
    }

//    cout << "Output and input set." << endl;


//    printf("Gates after output and input set:\n");
//    for (Chunk chunk : Circuit::chunks) {
//        printf("Chunk %d:\n", chunk.id);
//        for (shared_ptr<Gate>& gate : chunk.gates) {
//            printf("%s\n", gate_to_string(*gate, -1, 2).c_str());
//        }
//    }


//      int total = 0;

    auto simulate_start = get_time();
    duration<double> total_coretime_history2 = zero_duration();

    Chunk& chunk2 = Circuit::chunks.at(2);
    const int num_artificial2 = chunk2.num_artificial;
    printf("Number of artificial sources in chunk 2: %d\n", num_artificial2);

    if (!chunk2.right_to_left_natural_all(1 << num_artificial2)) {
        return 0.0;
    }

    u_int64_t num_histories_c2 = u_int64_t(1) << num_artificial2;

    cout << "fraction: " << opts.fraction << endl;

    size_t num_par_histories = static_cast<size_t>(static_cast<double>(num_histories_c2) * opts.fraction);

    printf("num_par_histories (to simulate): %lu\n", num_par_histories);

    vector<u_int64_t> par_histories(num_par_histories);

    vector<complex<float>> amplitudes(num_par_histories);

    //srand(time({}));
    srand(0);
    // Non-unique should work I think?
    //for (u_int64_t i = 0; i < num_par_histories; i++) {
    //    par_histories.at(i) = std::rand() % num_histories_c2;
    //}
    for (size_t i = 0; i < num_par_histories;) {
        int cand = std::rand() % num_histories_c2;
        bool cand_ok = true;
        for (size_t j = 0; j < i; j++) {
            if (par_histories.at(j) == cand) {
                cand_ok = false;
                break;
            }
        }
        if (cand_ok) {
            par_histories.at(i++) = cand;
        }
    }



    // With n=16, about x3 speedup with openmp compared to without

    parallel_for(0, num_par_histories, [&](size_t history2_ind) {
        std::complex<float> local_sum(0,0);

        size_t thread_ind = history2_ind; //TODO: Maybe, make one index for each actual thread (from hardware_concurrency) instead of history2?
        u_int64_t history2;
        if (opts.fraction > fLIMIT) { //TODO: fix this
            history2 = history2_ind;
        }
        else {
            history2 = par_histories.at(history2_ind);
        }

        auto start_history2 = get_time();

        // TODO: Make a real run setting the values of all internal wires.
        // We only need to iterate a vector of all deterministic, wire-breaking gates!

        if (!chunk2.right_to_left_vals(history2, thread_ind/*, buf_history*/)) {
            // Input, output and artificial not compatible with deterministic gates
            std::printf("    Vals pass rejected history --%ld.\n", history2);
            amplitudes.at(history2_ind) = 0;
            return;
        }
      
        // Then we need to iterate all to calculate contribution.
      
        complex <float> contribution2 = chunk_contribution(chunk2, thread_ind/*, buf_history*/);
                
        // --0 means the gates in chunk2 with C2 history 0.
        //std::printf("Contribution from history --%ld: %f + i%f\n", history2, contribution2.real(), contribution2.imag());
      
      
        Chunk& chunk1 = Circuit::chunks.at(1);
        const int num_artificial1 = chunk1.num_artificial;
        //printf("  Number of artificial sources in chunk 2: %d\n", num_artificial1);
      
        for (u_int64_t history1 = 0; history1 < u_int64_t(1) << num_artificial1; history1++) {
            //cout << "  In history1: " << history1 << endl;
            //histories.at(1) = history1;

            chunk1.reset_values(thread_ind); //Introduces two warnings}
      
            if (!chunk1.right_to_left_vals(history1, thread_ind/*, buf_history*/)) {
                //std::printf("    Vals pass rejected history -%ld%ld.\n", history1, history2);
                continue;
            }

            complex <float> contribution1 = contribution2 * chunk_contribution(chunk1, thread_ind/*, buf_history*/);
            
            //std::printf("  Contribution from history -%ld%ld: %f + i%f\n", history1, history2, contribution1.real(), contribution1.imag());
      
            Chunk& chunk0 = Circuit::chunks.at(0);
            const int num_artificial0 = chunk0.num_artificial;
            //printf("    Number of artificial sources in chunk 0: %d\n", num_artificial0);
      
            for (u_int64_t history0 = 0; history0 < u_int64_t(1) << num_artificial0; history0++) {
                //cout << "    In history0: " << history0 << endl;                        

                chunk0.reset_values(thread_ind);      
      
                if (!chunk0.right_to_left_vals(history0, thread_ind)) {
                    std::printf("    Artificial pass rejected history %ld%ld%ld.\n", history0, history1, history2);
                    continue;
                }
      
                //printf("    contribution1: %f + i%f\n", contribution1.real(), contribution1.imag());
      
                complex <float> contribution0 = contribution1 * chunk_contribution(chunk0, thread_ind);
      
                //std::printf("    Contribution from history %ld%ld%ld: %f + i%f\n", history0, history1, history2, contribution0.real(), contribution0.imag());
                local_sum += contribution0;
            }
        }

        //auto end_history2 = get_time();
        //total_coretime_history2 = end_history2 - start_history2;

        // Combine into total_amplitude safely
        printf("h2ind-%ld: local_sum: %f + i%f\n", history2_ind, local_sum.real(), local_sum.imag());
        amplitudes.at(history2_ind) = local_sum;
    });

    auto total_amplitude = parallel_reduce(0, num_par_histories, [&](size_t i) {
        return amplitudes[i];
    });    

    return total_amplitude * (float)num_histories_c2 / (float)num_par_histories;
}

int main(int argc, char* argv[]) {

    Options opts = get_options(argc, argv);

    ParsedCircuit::parse_circuit(opts.circuit_file);

    //printf("Parsed circuit:\n");
    //printf("  %s\n", ParsedCircuit::parsed_circuit_to_string().c_str());


    //TODO: Autotuning: Build circuit many times with different cp-params, save the best params and build once more for those.

    if (opts.num_chunk1 == -1 && opts.num_chunk2 == -1) {
        Circuit::build_autotuned_circuit();
    }
    else if (opts.num_chunk1 > -1 && opts.num_chunk2 > -1) {
        Circuit::build_circuit(opts.num_chunk1, opts.num_chunk2);
    }
    else {
        cerr << "Both -p and -r must be set, or none of them for autotuning." << endl;
        exit(1);
    }

    printf("After build:\n");
    for (int i = 0; i < NUM_CHUNKS; i++) {
        printf("Chunk %d with %zu gates and %d artificial sources:\n", i, Circuit::chunks.at(i).gates.size(), Circuit::chunks.at(i).num_artificial);
        for (const shared_ptr<Gate>& gate: Circuit::chunks.at(i).gates) {
            printf("  %s\n", gate_to_string(*gate, -1, 2).c_str());
        }
    }

    //printf("Output wires after build:\n");
    //for (shared_ptr<InternalWire>& iw : Circuit::output_sources) {
    //    printf("%s\n", internal_wire_to_string(iw, 2).c_str());
    //}

//    printf("Chunks internal wires after build (to reset): \n");
//    for (int i = 0; i < NUM_CHUNKS; i++) {
//        printf("Chunk %d with %ld internal wires:\n", i, Circuit::chunks.at(i).internal_wires.size());
//        for (const shared_ptr<InternalWire>& iw : Circuit::chunks.at(i).internal_wires) {
//            printf("  %s\n", internal_wire_to_string(iw, -1, 2).c_str());
//        }
//    }

    if (opts.only_build) {
        size_t total_gates = 0;
        int total_artificial_sources = 0;
        for (int i = 0; i < NUM_CHUNKS; i++) {
            total_gates += Circuit::chunks.at(i).gates.size();
            total_artificial_sources += Circuit::chunks.at(i).num_artificial;
            printf("Chunk %d: %ld gates, %d artificial sources.\n", i, Circuit::chunks.at(i).gates.size(), Circuit::chunks.at(i).num_artificial);
        }
        printf("Total gates: %ld\n", total_gates);
        printf("Artificial sources: %d\n", total_artificial_sources);
    }
    else {
        std::ostringstream buf;

        // TODO: For benchmarking: Run this many times with different input/output pairs.
        complex<float> amp = simulate(opts, buf, 3);
//        int a = simulate();
        printf("Total amplitude: %f + i%f\n", amp.real(), amp.imag());
    }

    return 0;
}
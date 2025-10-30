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
#include "circuit.h"
#include "parallel_for.h"

#ifdef USE_MPI
#include <mpi.h>
#endif

#define fLIMIT 0.9999999

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

complex <float> simulate(vector<bool> output_bits, vector<bool> input_bits, float fraction, std::ostringstream& buf, int verbosity = 0) {
    // Set values of those reached from natural
    // Implement similarly as FakeRun

    // Both R->L and L->R to make sure to set those reached from output and input.
    // Takes x2 time for each history, but in return we have more reach from natural
    // sources, less artificial sources and exponentially less histories.


    //cout << "In simulate" << endl;

    //cout << "Output bits: ";
    //for (int i = Circuit::n - 1; i >= 0; i--) {
    //    cout << output_bits.at(i);
    //}
    //cout << endl;
//
    //cout << "Input bits: ";
    //for (int i = Circuit::n - 1; i >= 0; i--) {
    //    cout << input_bits.at(i);
    //}
    //cout << endl;
//
    //cout << "fraction: " << fraction << endl;

    // One for each chunk, one for the wires that starts in INPUT, and one for OUTPUT.
    //array<u_int64_t, NUM_CHUNKS+2> histories = {0, 0, 0, 0, 0};

    for (const std::shared_ptr<InternalWire>& w : Circuit::output_sources) {
        w->set_safe_all(1, output_bits.at(w->wire));
    }

    //cout << "Output set." << endl;

    for (const std::shared_ptr<InternalWire>& w : Circuit::input_sources) {
        if (!w->set_safe_all(1, input_bits.at(w->wire))) { return false; }
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

    size_t num_par_histories = static_cast<size_t>(static_cast<double>(num_histories_c2) * fraction);

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

#ifdef USE_MPI
        int rank;
        MPI_Comm_rank(MPI_COMM_WORLD, &rank);
        printf("MPI rank %d processing history2_ind %lu / %lu\n", rank, history2_ind, num_par_histories);
#else
        printf("Processing history2_ind %lu / %lu\n", history2_ind, num_par_histories);
#endif


        std::complex<float> local_sum(0,0);

        size_t thread_ind = history2_ind; //TODO: Maybe, make one index for each actual thread (from hardware_concurrency) instead of history2?
        u_int64_t history2;
        if (fraction > fLIMIT) { //TODO: fix this
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

    complex<float> retval = total_amplitude * (float)num_histories_c2 / (float)num_par_histories;

    cout << "  Simulator returning amplitude: " << retval.real() << " + i" << retval.imag() << endl;
    
    return retval;
}

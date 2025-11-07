#pragma once
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
#include <mpi.h>
#include "typedef.h"

#ifdef USE_OPENMP
    #include <omp.h>
#endif

#define fLIMIT 0.9999999 // If fraction > fLIMIT, we make an exact simulation.

complex<float> chunk_contribution(const Chunk& chunk, TypeLongInt thread) {
    complex <float> contribution = 1.0;
    for (const shared_ptr<Gate>& gateptr : chunk.gates) {
        Gate& gate = *gateptr;
        const auto& qubits_vector = gate.qubits;  

        const int num_ctrl = gate.num_controls;

        // Check if the gate is activated
        bool activate = true;
        for (int c = 0; c < num_ctrl; c++) {
            // wire_right or wire_left doesn't matter for controls
            if (!qubits_vector[c]->wire_right->get_val(thread)) {
                activate = false;
                break;
            }
        }

        if (!activate) {
            // Compare if input = output
            const int num_targets = gate_type_infos.at(gate.type).num_targets;
            bool accept = true;
            for (int t = num_ctrl; t < num_ctrl + num_targets; t++) {
                const auto& qubit_t = qubits_vector[t];
                if(qubit_t->wire_left->get_val(thread) != qubit_t->wire_right->get_val(thread)) {
                    accept = false;
                    break;
                }
            }
            if (!accept) {
                contribution = 0;
                break;
            }
            continue; // Go on to the next gate.
        }
        const auto wire_left_value = gate.qubits.at(num_ctrl)->wire_left->get_val(thread);
        const auto wire_right_value = gate.qubits.at(num_ctrl)->wire_right->get_val(thread);
        const float inv_over_sqrt2 = 1.0 / sqrt(2.0);
        // Activate gate
        switch (gate.type) {
        case HADAMARD:
            if (wire_left_value && wire_right_value) {
                contribution *= -inv_over_sqrt2;
            } else {
                contribution *= inv_over_sqrt2;
            }
            break;
        case PHASE:
            if (wire_left_value) {
                contribution *= std::exp(complex<float>(0.0, gate.params.at(0)));
            }
            break;
        case PAULIZ:
            if (wire_left_value) {
                contribution *= -1;
            }
            break;
        case NOT:
            break;
        case SWAP:
            break;
        default:
            cerr << "Gate not implemented!" << endl;
            exit(1);
        }
    }
    return contribution;
}

complex <float> simulate(vector<bool> output_bits, vector<bool> input_bits, complex<float> input_amp, float fraction, float threshold = 0.0, int verbosity = 1) {

    // Debugging that should be printed only by one rank.
    bool print_rank0_timings = (verbosity >= 1);

    // Set output and input bits given from caller.
    for (const std::shared_ptr<InternalWire>& w : Circuit::output_sources) {
        w->set_safe_all(1, output_bits.at(w->wire));
    }

    for (const std::shared_ptr<InternalWire>& w : Circuit::input_sources) {
        if (!w->set_safe_all(1, input_bits.at(w->wire))) { return false; }
    }

    // Chunk 2 is the rightmost, and the one we parallelize over.
    Chunk& chunk2 = Circuit::chunks.at(2);
    const int num_artificial2 = chunk2.num_artificial;
#ifdef USE_OPENMP
        const int t_omp = omp_get_max_threads() * PADDING;
#else
        const int t_omp = 1;
#endif
    // Propagate the determinism from the output.
    if (!chunk2.right_to_left_natural_all(t_omp)) {
        return 0.0;
    }

    TypeLongInt num_histories_c2 = TypeLongInt(1) << num_artificial2;

    size_t num_par_histories = static_cast<size_t>(static_cast<double>(num_histories_c2) * fraction);

    vector<TypeLongInt> par_histories(num_par_histories);

    vector<complex<float>> amplitudes(num_par_histories);

    // TODO: Random seed or fixed for reproducibility?
    //srand(time({}));
    srand(0);

    // TODO: Check if non-unique histories is ok.
    for (TypeLongInt i = 0; i < num_par_histories; i++) {
        par_histories.at(i) = std::rand() % num_histories_c2;
    }

    // MPI, OpenMP, or threads parallelizing over histories in chunk 2.
    const float threshold2 = threshold * threshold;
    parallel_for(0, num_par_histories, [&](size_t history2_ind, size_t t_idx) {

        std::complex<float> local_sum(0,0);

        //TODO: Maybe, make one index for each actual thread (from hardware_concurrency) instead of history2?
        //TODO: The vector with "thread" indexing is not necessary for MPI-parallelization.
        const size_t thread_ind = t_idx * PADDING;
        const TypeLongInt history2 = (fraction > fLIMIT) ? history2_ind : par_histories.at(history2_ind);

        auto start_history2 = get_time();

        // TODO: Make a real run setting the values of all internal wires.
        // We only need to iterate a vector of all deterministic, wire-breaking gates!

        if (!chunk2.right_to_left_vals(history2, thread_ind)) {
            // Input, output and artificial not compatible with deterministic gates. The history is rejected.
            amplitudes[history2_ind] = std::complex<float>{0.f, 0.f};
            return;
        }
      
        complex <float> contribution2 = input_amp * chunk_contribution(chunk2, thread_ind);

        //Check if amplitude so far is small enough to neglect.
        if (std::norm(contribution2) < threshold2) {
            amplitudes[history2_ind] = std::complex<float>{0.f, 0.f};
            return;
        }
        
        // --0 means the gates in chunk2 with C2 history 0.
        //std::printf("Contribution from history --%ld: %f + i%f\n", history2, contribution2.real(), contribution2.imag());

        Chunk& chunk1 = Circuit::chunks.at(1);
        const int num_artificial1 = chunk1.num_artificial;
        //printf("  Number of artificial sources in chunk 2: %d\n", num_artificial1);
      
        for (TypeLongInt history1 = 0; history1 < TypeLongInt(1) << num_artificial1; history1++) {
            //cout << "  In history1: " << history1 << endl;
            //histories.at(1) = history1;

            chunk1.reset_values(thread_ind); //Introduces two warnings}
      
            if (!chunk1.right_to_left_vals(history1, thread_ind)) {
                //std::printf("    Vals pass rejected history -%ld%ld.\n", history1, history2);
                continue;
            }

            const std::complex<float> contribution1 = contribution2 * chunk_contribution(chunk1, thread_ind);
            if (std::norm(contribution1) < threshold2) continue;

            //std::printf("  Contribution from history -%ld%ld: %f + i%f\n", history1, history2, contribution1.real(), contribution1.imag());
      
            Chunk& chunk0 = Circuit::chunks.at(0);
            const int num_artificial0 = chunk0.num_artificial;
            //printf("    Number of artificial sources in chunk 0: %d\n", num_artificial0);
      
            for (TypeLongInt history0 = 0; history0 < TypeLongInt(1) << num_artificial0; history0++) {
                //cout << "    In history0: " << history0 << endl;                        

                chunk0.reset_values(thread_ind);      
      
                if (!chunk0.right_to_left_vals(history0, thread_ind)) continue;
      
                //printf("    contribution1: %f + i%f\n", contribution1.real(), contribution1.imag());
      
                complex <float> contribution0 = contribution1 * chunk_contribution(chunk0, thread_ind);
      
                //std::printf("    Contribution from history %ld%ld%ld: %f + i%f\n", history0, history1, history2, contribution0.real(), contribution0.imag());
                local_sum += contribution0;
            }
        }

        //auto end_history2 = get_time();

        // Combine into total_amplitude safely
        //printf("h2ind-%ld: local_sum: %f + i%f\n", history2_ind, local_sum.real(), local_sum.imag());
        amplitudes.at(history2_ind) = local_sum;
        const int wires_num = Circuit::all_internal_wires.size();
        for(int i=0; i < 3; ++i){
            Chunk& chunk = Circuit::chunks.at(i);
            chunk.reset_values(thread_ind);
        }
    });

    auto total_amplitude = parallel_reduce(0, num_par_histories, [&](size_t i) {
        return amplitudes[i];
    });    

    complex<float> retval = total_amplitude * (float)num_histories_c2 / (float)num_par_histories;

    //cout << "  Simulator returning amplitude: " << retval.real() << " + i" << retval.imag() << endl;
    
    return retval;
}

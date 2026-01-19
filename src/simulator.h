#pragma once
#include <unistd.h>
#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include <complex>
#include <cstdio>
#include <cmath>
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

// Only accounts for phase factors, since magnitude changes are accounted for
// by how many times a history appears in the sampling.
complex<float> chunk_contribution(const Chunk& chunk, TypeLongInt thread, int verbosity = 0) {
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
        const float over_sqrt2 = 1.0 / sqrt(2.0);
        const amplitude i_over_sqrt2 = complex<float>(0.0, 1.0) * over_sqrt2;
        const amplitude sqrt_i = complex<float>(1.0, 1.0) * over_sqrt2;
        const amplitude i = complex<float>(0.0, 1.0);
        const amplitude sqrt_neg_i = complex<float>(1.0, -1.0) * over_sqrt2;
        // Activate gate
        switch (gate.type) {
        case HADAMARD:
            if (wire_left_value && wire_right_value) {
                contribution *= -1;
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
        case RX:
            {
                float theta = gate.params.at(0);
                float cos_theta_2 = cos(theta / 2.0f); // TODO: Enough to check mod pi. Is that faster?
                float sin_theta_2 = sin(theta / 2.0f);
                if (wire_left_value == wire_right_value) {
                    if (cos_theta_2 < 0) {
                        contribution *= -1;
                    }
                }
                else {
                    if (sin_theta_2 < 0) {
                        contribution *= i;
                    } else {
                        contribution *= -i;
                    }
                }
            }
            break;
        case RY:
            {
                float theta = gate.params.at(0);
                float cos_theta_2 = cos(theta / 2.0f);
                float sin_theta_2 = sin(theta / 2.0f);
                if (wire_left_value == wire_right_value) {
                    if (cos_theta_2 < 0) {
                        contribution *= -1;
                    }
                }
                else {
                    if ((!wire_left_value && (sin_theta_2 < 0)) || (wire_left_value && (sin_theta_2 > 0))) {
                        contribution *= -1;
                    }
                }
            }
            break;
        case SX:
            if (wire_left_value == wire_right_value) {
                contribution *= 1;
            } else {
                contribution *= -i;
            }
            break;
        case SY:
            if (wire_left_value && !wire_right_value) {
                contribution *= -1;
            }
            else {
                contribution *= 1;
            }
            break;
        case SW:
            if (wire_left_value == wire_right_value) {
                contribution *= 1;
            } else if (wire_left_value) {
                contribution *= -sqrt_i;
            } else {
                contribution *= sqrt_neg_i;
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

// TODO: Batching. MPI processes calls simulate for a batch of histories, if processes over input entries is not enough.
unordered_statevector simulate(bitstr input_bits, amplitude input_amp, float fraction, float threshold = 0.0, int verbosity = 1) {

    // Debugging that should be printed only by one rank.
    bool print_rank0_timings = (verbosity >= 1);

    // Set input bits.
    for (const std::shared_ptr<InternalWire>& w : Circuit::input_sources) {
        w->set_safe_all(1, input_bits.test(w->wire));
    }
    
    // Convert bitstr to index
    long long input_index = input_bits.to_ulong();

    // Print input_amplitude for debugging.
    int world_rank;
    MPI_Comm_rank(MPI_COMM_WORLD, &world_rank);
    //std::cout << "Rank: " << world_rank << " ind: " << input_index << " Input amplitude: " << input_amp << std::endl;

    // Chunk 0 is the leftmost, and the one we parallelize over.
    Chunk& chunk0 = Circuit::chunks.at(0);
    const int num_artificial0 = chunk0.num_artificial;
#ifdef USE_OPENMP
        const int t_omp = omp_get_max_threads() * PADDING;
#else
        const int t_omp = 1;
#endif
    // Propagate the determinism from the input.
    chunk0.left_to_right_natural_all(t_omp);

    unordered_statevector global_statevector;
    

    TypeLongInt num_histories_c0 = TypeLongInt(1) << num_artificial0;

    size_t num_par_histories;
    
    Chunk& chunk1 = Circuit::chunks.at(1);
    const int num_artificial1 = chunk1.num_artificial;
    
    Chunk& chunk2 = Circuit::chunks.at(2);
    const int num_artificial2 = chunk2.num_artificial;
    
    const int num_artificial = num_artificial0 + num_artificial1 + num_artificial2;
    const long long num_samples_total = llround(static_cast<double>(TypeLongInt(1) << num_artificial) * fraction); // S

    //printf("Rank %d ind %lld num_samples_total: %lld\n", world_rank, input_index, num_samples_total);

    // TODO: Compare different strategies.
    float fraction0 = pow(fraction, 1.0f / 3.0f);
    float fraction1 = pow(fraction, 1.0f / 3.0f);
    // Number of histories in chunk 2 is determined by total number of histories.

    num_par_histories = round(static_cast<double>(num_histories_c0) * fraction0);

    vector<unordered_statevector> statevectors(num_par_histories);

    TypeLongInt num_sim_histories_c1 = max(llround((TypeLongInt(1) << num_artificial1) * fraction1), TypeLongInt(1));

    //printf("Rank %d ind %lld num_par_histories: %zu\n", world_rank, input_index, num_par_histories);
    //printf("Rank %d ind %lld num_sim_histories_c1: %lld\n", world_rank, input_index, num_sim_histories_c1);
    TypeLongInt num_sim_histories_c2 = max(llround(float(num_samples_total) / (num_par_histories * num_sim_histories_c1)), TypeLongInt(1));

    //printf("Rank %d ind %lld num_sim_histories_c2: %lld\n", world_rank, input_index, num_sim_histories_c2);

    //srand(0);
    srand(time(NULL) + input_bits.to_ulong()); // Different seed for each MPI rank.

    // MPI, OpenMP, or threads parallelizing over histories in chunk 0.
    const float threshold_sqr = threshold * threshold;
    parallel_for(0, num_par_histories, [&](size_t history0, size_t t_idx) {

        //printf("Rank %d ind %lld In history0 index %zu (thread %zu)\n", world_rank, input_index, history0, t_idx);

        unordered_statevector& local_sv = statevectors[history0];

        auto start_history0 = get_time();

        // Make a real run setting the values of all internal wires.
        float prob0 = chunk0.left_to_right_vals(t_idx);

        complex <float> contribution0 = input_amp * chunk_contribution(chunk0, t_idx);

        //Check if amplitude so far is small enough to neglect.
        if (std::norm(contribution0) < threshold_sqr) {
            return;
        }

        // 0-- means the gates in chunk0 with C0 history 0.
        //std::printf("Contribution from history %ld--: %f + i%f\n", history0, contribution0.real(), contribution0.imag());
        for (TypeLongInt history1 = 0; history1 < num_sim_histories_c1; history1++) {
            //cout << "  Rank " << world_rank << " ind " << input_index << " In history1: " << history1 << endl;
            //histories.at(1) = history1;

            chunk1.reset_values(t_idx);

            float prob1 = prob0 * chunk1.left_to_right_vals(t_idx);
            
            //printf("    Rank-%d-ind-%d prob1 (for this history): %f\n", world_rank, input_index, prob1);

            const amplitude contribution1 = contribution0 * chunk_contribution(chunk1, t_idx);
            if (std::norm(contribution1) < threshold_sqr) continue;

            for (TypeLongInt history2 = 0; history2 < num_sim_histories_c2; history2++) {
                //cout << "    Rank " << world_rank << " ind " << input_index << " In history2: " << history2 << endl;

                chunk2.reset_values(t_idx);

                float prob2 = prob1 * chunk2.left_to_right_vals(t_idx); 
                
                
                // Old: local_sum += contribution2;
                // TODO: Find output state of history.
                bitstr output_state;
                for (const std::shared_ptr<InternalWire>& w : Circuit::output_sources)
                    output_state.set(w->wire, w->get_val(t_idx));
      
                //printf("    contribution2: %f + i%f\n", contribution2.real(), contribution2.imag());
                
                //int chunk_verbosity = 0;
                //if (Circuit::all_internal_wires[1]->get_val(t_idx) && output_state.to_ullong() == 0) {
                //    std::printf("    Rank %d inind %lld iw1-1 outind %lld: calculating chunk_contribution2...\n", world_rank, input_index, output_state.to_ullong());
                //    chunk_verbosity = 3;
                //}
                
                complex <float> chunk_contribution2 = chunk_contribution(chunk2, t_idx, 0);
      
                complex <float> contribution2 = contribution1 * chunk_contribution2;
                
                //printf("    Rank-%d-ind-%d-outind-%lld prob2 (for this history): %f\n", world_rank, input_index, output_state.to_ullong(), prob2);
                    
                float sqr_prob = sqrt(prob2);
                //printf("    Rank-%d-ind-%d-outind-%lld sqrt_prob (for this history): %f\n", world_rank, input_index, output_state.to_ullong(), sqr_prob);
                
                local_sv[output_state] += contribution2 / sqr_prob;
                // Dividing with sqrt(prob2) converts the probability induced by sampling it to amplitude
            }
        }

        //auto end_history0 = get_time();

        for(int i=0; i < 3; ++i){
            Circuit::chunks.at(i).reset_values(t_idx);
        }
    });

    printf("  Rank %d ind %lld Simulated %lld samples over %d artificial sources.\n", world_rank, input_index, num_samples_total, num_artificial);

    // TODO: Do parallel for and reduce together for performance? Or tree based reduction?
    for (const auto& local_sv : statevectors) {
        //printf("  Rank %d ind %lld Merging local statevector with %zu entries into global statevector.\n", world_rank, input_index, local_sv.size());
        for (const auto& [idx, amplitude] : local_sv) {
            //printf("    Rank %d ind %lld Adding amplitude %f + i%f to state %s\n", world_rank, input_index, amplitude.real(), amplitude.imag(), idx.to_string().c_str());
            global_statevector[idx] += amplitude / float(num_samples_total);
        }
    }
    
    // Print global_statevector for debugging.
    printf("Rank %d ind %lld Output statevector after scaling:\n", world_rank, input_index);
    for (const auto& [idx, amplitude] : global_statevector) {
        printf("  Index: %s Amplitude: %f + i%f\n", idx.to_string().c_str(), amplitude.real(), amplitude.imag());
    }
    // Print sum of magnitudes for debugging.
    float sum_magnitudes = 0.0f;
    for (const auto& [idx, amplitude] : global_statevector) {
        sum_magnitudes += std::abs(amplitude);
    }
    printf("Rank %d ind %lld Sum of magnitudes in output statevector: %f\n", world_rank, input_index, sum_magnitudes);

    return global_statevector;
}

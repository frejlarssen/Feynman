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

#define fLIMIT 0.9999999 // If fraction > fLIMIT, we make an exact simulation.

complex<float> chunk_contribution(const Chunk& chunk, __int128 thread) {
    complex <float> contribution = 1.0;
    for (const shared_ptr<Gate>& gateptr : chunk.gates) {
        Gate& gate = *gateptr;

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
            // Compare if input = output
            bool accept = true;
            for (int t = num_ctrl; t < num_ctrl + gate_type_infos.at(gate.type).num_targets; t++) {
                if (gate.qubits.at(t)->wire_left->get_val(thread) != gate.qubits.at(t)->wire_right->get_val(thread)) {
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

        // Activate gate
        switch (gate.type) {
        case HADAMARD:
            if (gate.qubits.at(num_ctrl)->wire_left->get_val(thread) &&
                gate.qubits.at(num_ctrl)->wire_right->get_val(thread)) {
                contribution *= -1.0 / sqrt(2.0);
            } else {
                contribution *= 1.0 / sqrt(2.0);
            }
            break;
        case NOT:
            if (gate.qubits.at(num_ctrl)->wire_left->get_val(thread) ==
                gate.qubits.at(num_ctrl)->wire_right->get_val(thread)) {
                contribution = 0;
            }
            break;
        case PHASE:
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
    }
    return contribution;
}

complex <float> simulate(vector<bool> output_bits, vector<bool> input_bits, float fraction, int verbosity = 1) {

    // Debugging that should be printed only by one rank.
    bool print_rank0_timings = (verbosity >= 1);
#ifdef USE_MPI
    int world_rank;
    MPI_Comm_rank(MPI_COMM_WORLD, &world_rank);
    if (world_rank != 0) {
        print_rank0_timings = false;
    }
#endif

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

    // Propagate the determinism from the output.
    if (!chunk2.right_to_left_natural_all(1 << num_artificial2)) {
        return 0.0;
    }

    __int128 num_histories_c2 = __int128(1) << num_artificial2;

    size_t num_par_histories = static_cast<size_t>(static_cast<double>(num_histories_c2) * fraction);

    vector<__int128> par_histories(num_par_histories);

    vector<complex<float>> amplitudes(num_par_histories);

    // TODO: Random seed or fixed for reproducibility?
    //srand(time({}));
    srand(0);

    // TODO: Check if non-unique histories is ok.
    for (__int128 i = 0; i < num_par_histories; i++) {
        par_histories.at(i) = std::rand() % num_histories_c2;
    }

    // MPI, OpenMP, or threads parallelizing over histories in chunk 2.
    parallel_for(0, num_par_histories, [&](size_t history2_ind) {

#ifdef USE_MPI
        MPI_Comm_rank(MPI_COMM_WORLD, &world_rank);
#endif

        std::complex<float> local_sum(0,0);

        //TODO: Maybe, make one index for each actual thread (from hardware_concurrency) instead of history2?
        //TODO: The vector with "thread" indexing is not necessary for MPI-parallelization.
        size_t thread_ind = history2_ind;
        __int128 history2;
        if (fraction > fLIMIT) {
            history2 = history2_ind;
        }
        else {
            history2 = par_histories.at(history2_ind);
        }

        auto start_history2 = get_time();

        // TODO: Make a real run setting the values of all internal wires.
        // We only need to iterate a vector of all deterministic, wire-breaking gates!

        if (!chunk2.right_to_left_vals(history2, thread_ind)) {
            // Input, output and artificial not compatible with deterministic gates. The history is rejected.
            amplitudes.at(history2_ind) = 0;
            return;
        }
      
        complex <float> contribution2 = chunk_contribution(chunk2, thread_ind);
                
        // --0 means the gates in chunk2 with C2 history 0.
        //std::printf("Contribution from history --%ld: %f + i%f\n", history2, contribution2.real(), contribution2.imag());

        Chunk& chunk1 = Circuit::chunks.at(1);
        const int num_artificial1 = chunk1.num_artificial;
        //printf("  Number of artificial sources in chunk 2: %d\n", num_artificial1);
      
        for (__int128 history1 = 0; history1 < __int128(1) << num_artificial1; history1++) {
            //cout << "  In history1: " << history1 << endl;
            //histories.at(1) = history1;

            chunk1.reset_values(thread_ind); //Introduces two warnings}
      
            if (!chunk1.right_to_left_vals(history1, thread_ind)) {
                //std::printf("    Vals pass rejected history -%ld%ld.\n", history1, history2);
                continue;
            }

            complex <float> contribution1 = contribution2 * chunk_contribution(chunk1, thread_ind);
            
            //std::printf("  Contribution from history -%ld%ld: %f + i%f\n", history1, history2, contribution1.real(), contribution1.imag());
      
            Chunk& chunk0 = Circuit::chunks.at(0);
            const int num_artificial0 = chunk0.num_artificial;
            //printf("    Number of artificial sources in chunk 0: %d\n", num_artificial0);
      
            for (__int128 history0 = 0; history0 < __int128(1) << num_artificial0; history0++) {
                //cout << "    In history0: " << history0 << endl;                        

                chunk0.reset_values(thread_ind);      
      
                if (!chunk0.right_to_left_vals(history0, thread_ind)) {
                    continue;
                }
      
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
    });

    auto total_amplitude = parallel_reduce(0, num_par_histories, [&](size_t i) {
        return amplitudes[i];
    });    

    complex<float> retval = total_amplitude * (float)num_histories_c2 / (float)num_par_histories;

    //cout << "  Simulator returning amplitude: " << retval.real() << " + i" << retval.imag() << endl;
    
    return retval;
}

#pragma once
#include "circuit.h"
#include "parallel_for.h"
#include "typedef.h"
#include <chrono>
#include <cmath>
#include <complex>
#include <cstdio>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <map>
#include <unistd.h>
#include <vector>

#ifdef USE_OPENMP
#include <omp.h>
#endif

#define fLIMIT 0.9999999 // If fraction > fLIMIT, we make an exact simulation.

inline TypeLongInt random_below(TypeLongInt upper) {
  if (upper <= 0) {
    return 0;
  }

  using UnsignedLongInt = unsigned __int128;
  constexpr UnsignedLongInt rand_base =
      static_cast<UnsignedLongInt>(RAND_MAX) + 1u;

  UnsignedLongInt candidate = 0;
  UnsignedLongInt place_value = 1;
  const UnsignedLongInt unsigned_upper = static_cast<UnsignedLongInt>(upper);
  while (place_value < unsigned_upper) {
    candidate +=
        static_cast<UnsignedLongInt>(std::rand()) * place_value;
    place_value *= rand_base;
  }

  return static_cast<TypeLongInt>(candidate % unsigned_upper);
}

inline vector<TypeLongInt>
sample_histories_without_replacement(TypeLongInt total_histories,
                                     size_t sample_count) {
  vector<TypeLongInt> sampled_histories(sample_count);
  if (sample_count == 0 || total_histories <= 0) {
    return sampled_histories;
  }

  if (static_cast<TypeLongInt>(sample_count) >= total_histories) {
    for (TypeLongInt i = 0; i < total_histories; ++i) {
      sampled_histories.at(static_cast<size_t>(i)) = i;
    }
    return sampled_histories;
  }

  // Sample without replacement using a virtual Fisher-Yates shuffle over
  // [0, total_histories) backed by a sparse map of swaps.
  std::map<TypeLongInt, TypeLongInt> swaps;
  for (size_t i = 0; i < sample_count; ++i) {
    const TypeLongInt remaining =
        total_histories - static_cast<TypeLongInt>(i);
    const TypeLongInt picked_index = random_below(remaining);
    const TypeLongInt last_index = remaining - 1;

    const auto picked_it = swaps.find(picked_index);
    const TypeLongInt picked_value =
        (picked_it == swaps.end()) ? picked_index : picked_it->second;

    const auto last_it = swaps.find(last_index);
    const TypeLongInt last_value =
        (last_it == swaps.end()) ? last_index : last_it->second;

    sampled_histories.at(i) = picked_value;
    swaps[picked_index] = last_value;
  }

  return sampled_histories;
}

inline unsigned int history_sampling_seed() {
  static const unsigned int seed = []() {
    const char *env_value = std::getenv("FEYNMAN_HISTORY_SEED");
    if (env_value == nullptr || *env_value == '\0') {
      return 0u;
    }

    char *end_ptr = nullptr;
    const unsigned long long parsed = std::strtoull(env_value, &end_ptr, 10);
    if (end_ptr == env_value) {
      return 0u;
    }
    return static_cast<unsigned int>(parsed);
  }();
  return seed;
}

TypeAmp chunk_contribution(const Chunk &chunk, TypeLongInt thread,
                           TypeAmp contribution,
                           TypeAmpReal threshold2 = 0.0) {
  for (const shared_ptr<Gate> &gateptr : chunk.gates) {
    Gate &gate = *gateptr;
    const auto &qubits_vector = gate.qubits;

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
        const auto &qubit_t = qubits_vector[t];
        if (qubit_t->wire_left->get_val(thread) !=
            qubit_t->wire_right->get_val(thread)) {
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
    const auto wire_left_value =
        gate.qubits.at(num_ctrl)->wire_left->get_val(thread);
    const auto wire_right_value =
        gate.qubits.at(num_ctrl)->wire_right->get_val(thread);
    const TypeAmpReal inv_over_sqrt2 = 1.0 / sqrt(2.0);
    const auto exp_i = [](TypeAmpReal theta) {
      return std::exp(TypeAmp(0.0, theta));
    };
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
        contribution *= exp_i(gate.params.at(0));
      }
      break;
    case FSIM: {
      const auto wire_left_value_2 =
          gate.qubits.at(num_ctrl + 1)->wire_left->get_val(thread);
      const auto wire_right_value_2 =
          gate.qubits.at(num_ctrl + 1)->wire_right->get_val(thread);
      const TypeAmpReal theta = gate.params.at(0);
      const TypeAmpReal phi = gate.params.at(1);
      const uint8_t in_state =
          (static_cast<uint8_t>(wire_left_value) << 1) |
          static_cast<uint8_t>(wire_left_value_2);
      const uint8_t out_state =
          (static_cast<uint8_t>(wire_right_value) << 1) |
          static_cast<uint8_t>(wire_right_value_2);
      const TypeAmpReal cos_theta = std::cos(theta);
      const TypeAmpReal sin_theta = std::sin(theta);

      if (in_state == 0 && out_state == 0) {
        contribution *= 1.0;
      } else if (in_state == 1 && out_state == 1) {
        contribution *= cos_theta;
      } else if (in_state == 2 && out_state == 2) {
        contribution *= cos_theta;
      } else if ((in_state == 1 && out_state == 2) ||
                 (in_state == 2 && out_state == 1)) {
        contribution *= TypeAmp(0.0, -sin_theta);
      } else if (in_state == 3 && out_state == 3) {
        contribution *= exp_i(-phi);
      } else {
        contribution = 0.0;
      }
      break;
    }
    case T:
      if (wire_left_value) {
        contribution *= exp_i(static_cast<TypeAmpReal>(PI) / 4.0);
      }
      break;
    case TDG:
      if (wire_left_value) {
        contribution *= exp_i(-static_cast<TypeAmpReal>(PI) / 4.0);
      }
      break;
    case PAULIZ:
      if (wire_left_value) {
        contribution *= -1;
      }
      break;
    case RX: {
      const TypeAmpReal theta = gate.params.at(0);
      const TypeAmpReal cos_half = std::cos(theta * 0.5);
      const TypeAmpReal sin_half = std::sin(theta * 0.5);
      if (wire_left_value == wire_right_value) {
        contribution *= cos_half;
      } else {
        contribution *= TypeAmp(0.0, -sin_half); // -i sin(theta/2)
      }
      break;
    }
    case RY: {
      const TypeAmpReal theta = gate.params.at(0);
      const TypeAmpReal cos_half = std::cos(theta * 0.5);
      const TypeAmpReal sin_half = std::sin(theta * 0.5);
      if (wire_left_value == wire_right_value) {
        contribution *= cos_half;
      } else if (!wire_left_value && wire_right_value) {
        contribution *= sin_half;
      } else {
        contribution *= -sin_half;
      }
      break;
    }
    case U2: {
      const TypeAmpReal phi = gate.params.at(0);
      const TypeAmpReal lambda = gate.params.at(1);
      if (!wire_left_value && !wire_right_value) {
        contribution *= inv_over_sqrt2;
      } else if (wire_left_value && !wire_right_value) {
        contribution *= -exp_i(lambda) * inv_over_sqrt2;
      } else if (!wire_left_value && wire_right_value) {
        contribution *= exp_i(phi) * inv_over_sqrt2;
      } else {
        contribution *= exp_i(phi + lambda) * inv_over_sqrt2;
      }
      break;
    }
    case U3: {
      const TypeAmpReal theta = gate.params.at(0);
      const TypeAmpReal phi = gate.params.at(1);
      const TypeAmpReal lambda = gate.params.at(2);
      const TypeAmpReal cos_half = std::cos(theta * 0.5);
      const TypeAmpReal sin_half = std::sin(theta * 0.5);
      if (!wire_left_value && !wire_right_value) {
        contribution *= cos_half;
      } else if (wire_left_value && !wire_right_value) {
        contribution *= -exp_i(lambda) * sin_half;
      } else if (!wire_left_value && wire_right_value) {
        contribution *= exp_i(phi) * sin_half;
      } else {
        contribution *= exp_i(phi + lambda) * cos_half;
      }
      break;
    }
    case NOT:
    case SWAP:
      break;
    default:
      cerr << "Gate not implemented!" << '\n';
      exit(1);
    }

    // Each gate contributes a single matrix element whose magnitude is at most
    // 1. Once the running product falls below threshold, the remaining gates in
    // this chunk cannot bring the full contribution back above threshold.
    if (threshold2 > 0.0 && std::norm(contribution) < threshold2) {
      return TypeAmp(0.0, 0.0);
    }
  }
  return contribution;
}

struct AmplitudeAbsStats {
  TypeAmpReal min_nonzero_abs = std::numeric_limits<TypeAmpReal>::infinity();
  TypeAmpReal max_abs = TypeAmpReal(0.0);
  TypeLongInt count = 0;
  TypeLongInt count_nonzero = 0;

  void observe(const TypeAmp &value) {
    const TypeAmpReal abs_value = std::abs(value);
    if (abs_value > TypeAmpReal(0.0)) {
      if (abs_value < min_nonzero_abs) {
        min_nonzero_abs = abs_value;
      }
      ++count_nonzero;
    }
    if (abs_value > max_abs) {
      max_abs = abs_value;
    }
    ++count;
  }

  void merge_from(const AmplitudeAbsStats &other) {
    if (other.count == 0) {
      return;
    }
    if (other.min_nonzero_abs < min_nonzero_abs) {
      min_nonzero_abs = other.min_nonzero_abs;
    }
    if (other.max_abs > max_abs) {
      max_abs = other.max_abs;
    }
    count += other.count;
    count_nonzero += other.count_nonzero;
  }
};

struct SimulateAbsStats {
  AmplitudeAbsStats contribution2;
  AmplitudeAbsStats contribution1;
  AmplitudeAbsStats contribution0;

  void merge_from(const SimulateAbsStats &other) {
    contribution2.merge_from(other.contribution2);
    contribution1.merge_from(other.contribution1);
    contribution0.merge_from(other.contribution0);
  }
};

TypeAmp simulate(vector<bool> output_bits, vector<bool> input_bits,
                 TypeAmp input_amp, TypeAmpReal fraction,
                 TypeAmpReal threshold = 0.0, int verbosity = 1,
                 SimulateAbsStats *simulate_abs_stats = nullptr) {
  Circuit::validate_chunk_history_capacity("Simulation");

  // Debugging that should be printed only by one rank.
  bool print_rank0_timings = (verbosity >= 1);

  // Set output and input bits given from caller.
  for (const std::shared_ptr<InternalWire> &w : Circuit::output_sources) {
    w->set_safe_all(1, output_bits.at(w->wire));
  }

  for (const std::shared_ptr<InternalWire> &w : Circuit::input_sources) {
    if (!w->set_safe_all(1, input_bits.at(w->wire))) {
      return TypeAmp(0.0, 0.0);
    }
  }

  // Chunk 2 is the rightmost, and the one we parallelize over.
  Chunk &chunk2 = Circuit::chunks.at(2);
  const int num_artificial2 = chunk2.num_artificial;
#ifdef USE_OPENMP
  const int t_omp = omp_get_max_threads() * PADDING;
#else
  const int t_omp = 1;
#endif
  // Propagate the determinism from the output.
  if (!chunk2.right_to_left_natural_all(t_omp)) {
    return TypeAmp(0.0, 0.0);
  }

  TypeLongInt num_histories_c2 =
      pow2_checked(num_artificial2, "Chunk-2 history count");

  size_t num_par_histories =
      static_cast<size_t>(static_cast<double>(num_histories_c2) * fraction);

  vector<TypeLongInt> par_histories(num_par_histories);

  vector<TypeAmp> amplitudes(num_par_histories);
  vector<SimulateAbsStats> thread_simulate_abs_stats(static_cast<size_t>(t_omp));

  std::srand(history_sampling_seed());

  par_histories =
      sample_histories_without_replacement(num_histories_c2, num_par_histories);

  // MPI, OpenMP, or threads parallelizing over histories in chunk 2.
  const TypeAmpReal threshold2 = threshold * threshold;
  parallel_for(0, num_par_histories, [&](TypeLongInt history2_ind, int t_idx) {
    TypeAmp local_sum(0, 0);

    const int thread_ind = t_idx;
    const TypeLongInt history2 =
        (fraction > fLIMIT) ? history2_ind : par_histories.at(history2_ind);

    auto start_history2 = std::chrono::steady_clock::now();

    // TODO: Make a real run setting the values of all internal wires.
    // We only need to iterate a vector of all deterministic, wire-breaking
    // gates!

    if (!chunk2.right_to_left_vals(history2, thread_ind)) {
      // Input, output and artificial not compatible with deterministic gates.
      // The history is rejected.
      amplitudes[history2_ind] = TypeAmp{0.0, 0.0};
      return;
    }

    TypeAmp contribution2 =
        chunk_contribution(chunk2, thread_ind, input_amp, threshold2);
    thread_simulate_abs_stats.at(static_cast<size_t>(thread_ind))
        .contribution2.observe(contribution2);

    // Check if amplitude so far is small enough to neglect.
    if (std::norm(contribution2) < threshold2) {
      amplitudes[history2_ind] = TypeAmp{0.0, 0.0};
      return;
    }

    // --0 means the gates in chunk2 with C2 history 0.
    // std::printf("Contribution from history --%ld: %f + i%f\n", history2,
    // contribution2.real(), contribution2.imag());

    Chunk &chunk1 = Circuit::chunks.at(1);
    const int num_artificial1 = chunk1.num_artificial;
    // printf("  Number of artificial sources in chunk 2: %d\n",
    // num_artificial1);

    const TypeLongInt num_histories_c1 =
        pow2_checked(num_artificial1, "Chunk-1 history count");
    for (TypeLongInt history1 = 0; history1 < num_histories_c1;
         history1++) {
      // cout << "  In history1: " << history1 << '\n';
      // histories.at(1) = history1;

      chunk1.reset_values(thread_ind); // Introduces two warnings}

      if (!chunk1.right_to_left_vals(history1, thread_ind)) {
        // std::printf("    Vals pass rejected history -%ld%ld.\n", history1,
        // history2);
        continue;
      }

      const TypeAmp contribution1 =
          chunk_contribution(chunk1, thread_ind, contribution2, threshold2);
      thread_simulate_abs_stats.at(static_cast<size_t>(thread_ind))
          .contribution1.observe(contribution1);
      if (std::norm(contribution1) < threshold2)
        continue;

      // std::printf("  Contribution from history -%ld%ld: %f + i%f\n",
      // history1, history2, contribution1.real(), contribution1.imag());

      Chunk &chunk0 = Circuit::chunks.at(0);
      const int num_artificial0 = chunk0.num_artificial;
      // printf("    Number of artificial sources in chunk 0: %d\n",
      // num_artificial0);

      const TypeLongInt num_histories_c0 =
          pow2_checked(num_artificial0, "Chunk-0 history count");
      for (TypeLongInt history0 = 0; history0 < num_histories_c0; history0++) {
        // cout << "    In history0: " << history0 << '\n';

        chunk0.reset_values(thread_ind);

        if (!chunk0.right_to_left_vals(history0, thread_ind))
          continue;

        // printf("    contribution1: %f + i%f\n", contribution1.real(),
        // contribution1.imag());

        TypeAmp contribution0 =
            chunk_contribution(chunk0, thread_ind, contribution1, threshold2);
        thread_simulate_abs_stats.at(static_cast<size_t>(thread_ind))
            .contribution0.observe(contribution0);

        // std::printf("    Contribution from history %ld%ld%ld: %f + i%f\n",
        // history0, history1, history2, contribution0.real(),
        // contribution0.imag());
        local_sum += contribution0;
      }
    }

    // auto end_history2 = get_time();

    // Combine into total_amplitude safely
    // printf("h2ind-%ld: local_sum: %f + i%f\n", history2_ind,
    // local_sum.real(), local_sum.imag());
    amplitudes.at(history2_ind) = local_sum;
    for (int i = 0; i < 3; ++i) {
      Circuit::chunks.at(i).reset_values(thread_ind);
    }
  });

  auto total_amplitude = parallel_reduce(
      0, num_par_histories, [&](size_t i) { return amplitudes[i]; });

  if (simulate_abs_stats != nullptr) {
    for (const SimulateAbsStats &thread_stats : thread_simulate_abs_stats) {
      simulate_abs_stats->merge_from(thread_stats);
    }
  }

  TypeAmp retval = total_amplitude * static_cast<TypeAmpReal>(num_histories_c2) /
                   static_cast<TypeAmpReal>(num_par_histories);

  // cout << "  Simulator returning amplitude: " << retval.real() << " + i" <<
  // retval.imag() << '\n';

  return retval;
}

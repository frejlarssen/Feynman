// Target to be containerized to use in cloud workflow

#include "../src/iofiles.h"
#include "../src/simulator.h"
#include "../src/typedef.h"
#include "../src/utils.h"
#include <filesystem>
#include <iostream>
#ifdef USE_OPENMP
#include <omp.h>
#endif

#define EXECUTE_RUN 1
#define PERF_INSTRUMENT 0
#define CLOSE_TO_ZERO 1e-8

using namespace std;
namespace fs = std::filesystem;

struct Options {
  string circuit_file;
  string input_statevector_file;
  string batch_file;
  string output_statevector_file;
  int num_chunk1 = -1;
  int num_chunk2 = -1;
  float fraction = 1.0;
  float threshold = CLOSE_TO_ZERO;
  int verbosity = 1;
  bool dense = false;
};

Options get_options(int argc, char *argv[]) {
  Options opts;

  const char *helpstr =
      "Usage: ./cloud_task.x -c circuit_file -i input_statevector_file "
      "-b batch_file -o output_statevector_file -p num_chunk1 -r num_chunk2 "
      "-f fraction_of_histories -v verbosity (-D [Dense])\n";

  if (argc < 4) {
    cout << helpstr;
    exit(1);
  }

  int k;

  auto to_int = [](const std::string &word) -> int {
    return std::atoi(word.c_str());
  };

  auto to_float = [](const std::string &word) -> float {
    return float(std::atof(word.c_str()));
  };

  for (int i = 0; i < argc; i++) {
    cout << argv[i] << " ";
  }
  cout << '\n';

  while ((k = getopt(argc, argv, "c:i:b:o:p:r:s:f:t:v:D")) != -1) {
    switch (k) {
    case 'c':
      opts.circuit_file = optarg;
      break;
    case 'i':
      opts.input_statevector_file = optarg;
      break;
    case 'b':
      opts.batch_file = optarg;
      break;
    case 'o':
      opts.output_statevector_file = optarg;
      break;
    case 'p':
      opts.num_chunk2 = to_int(optarg);
      break;
    case 'r':
      opts.num_chunk1 = to_int(optarg);
      break;
    case 'f':
      opts.fraction = to_float(optarg);
      break;
    case 't':
      opts.threshold = to_float(optarg);
      break;
    case 'v':
      opts.verbosity = to_int(optarg);
      break;
    case 'D':
      opts.dense = true;
      break;
    default:
      cout << helpstr;
      exit(1);
    }
  }
  return opts;
}

void run(Options &opts) {
  auto start_svcc_all = get_time();
#ifdef USE_OPENMP
  const int t_omp = omp_get_max_threads();
#else
  const int t_omp = 0;
#endif

  ParsedCircuit::parse_circuit(opts.circuit_file);
  const bool use_autotune = (opts.num_chunk1 == -1 && opts.num_chunk2 == -1);

  if (use_autotune) {
    // Autotune if checkpoints not given. (This takes longer time initially.)
    Circuit::build_autotuned_circuit();
  } else if (opts.num_chunk1 > -1 && opts.num_chunk2 > -1) {
    Circuit::build_circuit(opts.num_chunk1, opts.num_chunk2);
  } else {
    cerr << "Both -p and -r must be set, or none of them for autotuning."
         << '\n';
    exit(1);
  }

  if (opts.verbosity >= 3)
    printf("After build: %s\n", Circuit::circuit_to_string(-1, 2).c_str());

  if (opts.verbosity >= 1) {
    const int num_gates = ParsedCircuit::nr_gates;
    printf("Circuit has %d gates. Distributed as:\n", num_gates);
    printf("  Chunk 0: %zu gates\n", Circuit::chunks.at(0).gates.size());
    printf("  Chunk 1: %zu gates\n", Circuit::chunks.at(1).gates.size());
    printf("  Chunk 2: %zu gates\n", Circuit::chunks.at(2).gates.size());
    const int num_artificial = Circuit::chunks.at(0).num_artificial +
                               Circuit::chunks.at(1).num_artificial +
                               Circuit::chunks.at(2).num_artificial;
    printf("Total number of artificial sources: %d. Distributed as:\n",
           num_artificial);
    printf("  Chunk 0: %d\n", Circuit::chunks.at(0).num_artificial);
    printf("  Chunk 1: %d\n", Circuit::chunks.at(1).num_artificial);
    printf("  Chunk 2: %d\n", Circuit::chunks.at(2).num_artificial);

    const TypeLongInt num_histories_total =
        (TypeLongInt(1) << Circuit::chunks.at(0).num_artificial) *
        (TypeLongInt(1) << Circuit::chunks.at(1).num_artificial) *
        (TypeLongInt(1) << Circuit::chunks.at(2).num_artificial);

    printf("For each simulate call we simulate over: \n");
    printf("  %lld histories in total.\n", num_histories_total);
    printf("  %d histories in parallel.\n",
           (1 << Circuit::chunks.at(2).num_artificial));
    if (use_autotune) {
      printf(
          "Autotuning time: %.6f seconds (candidates=%d, step_size=%d, "
          "best_gate_ops_estimate=%lld, mode=autotuned)\n",
          Circuit::last_autotune_seconds, Circuit::last_autotune_candidates,
          Circuit::last_autotune_step_size, Circuit::last_autotune_best_gate_ops);
    } else {
      printf(
          "Autotuning time: 0.000000 seconds (candidates=0, step_size=0, "
          "best_gate_ops_estimate=0, mode=fixed)\n");
    }
  }

  // Load input bitstrings
  vector<InputBitstrings> input_bitstrings = read_input_bitstrings_from_file(
      opts.input_statevector_file, opts.dense);

  // Load output bitstrings to simulate (if the option is ON)
  // #ifdef USE_SUBSET_OUTBITSTRINGS
  vector<vector<bool>> output_bitstrings = load_output_bitvectors_from_file(
      opts.batch_file);
  const TypeLongInt total_output_bitstrings =
      static_cast<TypeLongInt>(output_bitstrings.size());
  // #else
  //     const TypeLongInt total_output_bitstrings = 1ULL << Circuit::n; //
  //     overflow if n >= 128
  // #endif
  if (opts.verbosity >= 1)
    std::cout << "Total output bitstrings to simulate: "
              << static_cast<std::size_t>(total_output_bitstrings) << '\n';

  const fs::path output_path(opts.output_statevector_file);
  if (output_path.has_parent_path()) {
    fs::create_directories(output_path.parent_path());
  }
  const fs::path timing_file_path =
      replace_filename(opts.output_statevector_file, "timeBitstrings.tm");
  if (timing_file_path.has_parent_path()) {
    fs::create_directories(timing_file_path.parent_path());
  }

  // Loop through all input-output pairs. Start with amplitude depending on
  // input statevector.
  std::string local_buf;
  local_buf.reserve(1 << 20);
  std::string local_buf_timing;
  local_buf_timing.reserve(1 << 16);

  if (opts.verbosity >= 1) {
    printf(
        "Starting simulation over all input-output pairs:\n -- Total output "
        "bitstrings = %lld - OMP_THREADS per worker = "
        "%d --:\n",
        total_output_bitstrings, t_omp);
  }

  duration<double> total_clocktime_simulate = zero_duration();
  int num_calls_simulate = 0;

  // Loop though all output bitstrings
  std::size_t count_processed_bitstrings = 0;
  auto start_svcc_sim = get_time();
  const std::size_t progress_interval =
      (total_output_bitstrings <= 10)
          ? 1
          : (total_output_bitstrings <= 100 ? 10 : 100);

  // Worker body
  auto process_outputs = [&](std::size_t start, std::size_t end) {

  };
  // prctl(PR_TASK_PERF_EVENTS_ENABLE, 0, 0, 0, 0);
#if PERF_INSTRUMENT
  ioctl(fd, PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP);  // zero all
  ioctl(fd, PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP); // begin region
#endif

#if EXECUTE_RUN
  // Run the simulation
  for (std::size_t output_int = 0; output_int < output_bitstrings.size(); ++output_int) {
    if (output_int >= total_output_bitstrings)
      break;
    //    #ifdef USE_SUBSET_OUTBITSTRINGS
    const vector<bool> output_bits = output_bitstrings[output_int];
    //    #else
    //            const TypeLongInt bitstringDecimal = output_int;
    //            std::vector<bool> output_bits =
    //            bit_array_from_int(bitstringDecimal, Circuit::n);
    //    #endif
    auto start_simulate_bitstring = get_time();
    ++count_processed_bitstrings;

    std::complex<float> output_amp(0, 0);

    // Loop through the input bitstrings specified in input file
    for (const auto &input : input_bitstrings) {
      std::vector<bool> input_bits = input.index;

      std::complex<float> amp_in = input.amp;

      auto start_simulate = get_time();
      output_amp += simulate(output_bits, input_bits, amp_in, opts.fraction,
                               opts.threshold, 3);
      auto end_simulate = get_time();
      num_calls_simulate++;

      const duration<double> clocktime_simulate =
          end_simulate - start_simulate;

      if (opts.verbosity >= 2) {
        printf("Clocktime to simulate input |");
        for (int i = Circuit::n - 1; i >= 0; --i)
          printf("%d", input_bits[i] ? 1 : 0);
        printf("> to output |");
        for (int i = Circuit::n - 1; i >= 0; --i)
          printf("%d", output_bits[i] ? 1 : 0);
        printf("> : %f seconds\n", clocktime_simulate.count());
      }

      total_clocktime_simulate += clocktime_simulate;
      // Reset all values (for all threads if OpenMP is used)
      Circuit::reset_values_all();
    }

      auto end_simulate_bitstring = get_time();
      const duration<double> clocktime_bitstring =
          end_simulate_bitstring - start_simulate_bitstring;
      local_buf_timing += bitvector_to_hexstring(output_bits) + ":" +
                          std::to_string(clocktime_bitstring.count()) + "\n";

      // Write to output file
      bool writeFlag = (opts.dense || (std::abs(output_amp) > opts.threshold));
      if (writeFlag) {
        local_buf += bitvector_to_hexstring(output_bits) + ":" +
                     std::to_string(output_amp.real()) + "+" +
                     std::to_string(output_amp.imag()) + "i\n";
      }

      const bool should_report_progress =
          opts.verbosity >= 1 &&
          (count_processed_bitstrings == total_output_bitstrings ||
           (count_processed_bitstrings % progress_interval) == 0);
      if (should_report_progress) {
        const duration<double> elapsed_progress = get_time() - start_svcc_sim;
        const double elapsed_seconds = elapsed_progress.count();
        const double processed = static_cast<double>(count_processed_bitstrings);
        const double total = static_cast<double>(total_output_bitstrings);
        const double percent_done = (total > 0.0) ? (100.0 * processed / total) : 100.0;
        const double rate =
            (elapsed_seconds > 0.0) ? (processed / elapsed_seconds) : 0.0;
        const double eta_seconds =
            (rate > 0.0) ? ((total - processed) / rate) : 0.0;
        printf(
            "Progress: processed %zu / %lld output bitstrings (%.1f%%, "
            "elapsed %.1fs, rate %.2f bitstrings/s, eta %.1fs)\n",
            count_processed_bitstrings, total_output_bitstrings, percent_done,
            elapsed_seconds, rate, eta_seconds);
      }
    }
#endif
#if PERF_INSTRUMENT
  ioctl(fd, PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP);
  // prctl(PR_TASK_PERF_EVENTS_DISABLE, 0, 0, 0, 0);
#endif

  auto end_svcc_simulation = get_time();

  // parallel output to disk
  write_string_to_file(opts.output_statevector_file, local_buf);
  write_string_to_file(timing_file_path.string(), local_buf_timing);

  if (opts.verbosity >= 1) {
    printf("Number of simulate calls: %d\n", num_calls_simulate);
    printf("Total clocktime for all simulate calls: %f seconds\n",
           total_clocktime_simulate.count());
    printf("Average clocktime per simulate call: %f seconds\n",
           total_clocktime_simulate.count() / num_calls_simulate);
  }

  // out_file.close();
  fflush(stdin);

  auto end_svcc_full = get_time();

  duration<double> total_clocktime_svcc_sim =
      end_svcc_simulation - start_svcc_sim;
  duration<double> total_clocktime_svcc_full = end_svcc_full - start_svcc_all;
  duration<double> total_clocktime_svcc_writing =
      end_svcc_full - end_svcc_simulation;

  if (opts.verbosity >= 1) {
    printf("Total clocktime sim for sv.cpp: %f seconds\n",
           total_clocktime_svcc_sim.count());
    printf("Total clocktime writing to disk for sv.cpp: %f seconds\n",
           total_clocktime_svcc_writing.count());
    printf("Total clocktime (including I/O) for sv.cpp: %f seconds\n",
           total_clocktime_svcc_full.count());
  }
}

int main(int argc, char *argv[]) {
  // prctl(PR_TASK_PERF_EVENTS_DISABLE, 0, 0, 0, 0);
#if PERF_INSTRUMENT
  int fd =
      open_leader(getpid(), -1, PERF_TYPE_HARDWARE, PERF_COUNT_HW_CPU_CYCLES);
#endif

  Options opts = get_options(argc, argv);

  try {
    run(opts);
  } catch (const std::exception &e) {
    cerr << "Exception in run() function: " << e.what() << '\n';
    return 1;
  }

  return 0;
}

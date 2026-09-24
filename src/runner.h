#pragma once

#include "execution.h"
#include "memory_profile.h"
#include "simulator.h"
#include <filesystem>
#include <getopt.h>
#include <limits>
#include <stdexcept>

namespace feynman {
namespace fs = std::filesystem;

struct Options {
  std::string circuit_file, input_file, output_bits_file, output_file;
  std::string input_bits, output_bits;
#ifdef USE_MPI
  std::string schedule = "prefetch";
#else
  std::string schedule = "serial";
#endif
  int chunk1 = -1, chunk2 = -1;
  std::size_t batch_size = 32;
  TypeAmpReal fraction = 1.0, threshold = 1e-8;
  int verbosity = 1;
  bool dense = false, build_only = false, help = false;
};

inline void print_help() {
  std::cout
      << "Usage: feynman.x / feynman_mpi.x -c CIRCUIT [options]\n"
         "  -i FILE -b FILE -o FILE  Input amplitudes, requested outputs, "
         "result file\n"
         "  --input-bits BITS --output-bits BITS  One basis transition "
         "(binary, MSB first)\n"
         "                          Prints amplitude; -o optionally saves "
         "artifacts\n"
         "  -B, --build-only         Build/report circuit without simulating\n"
         "  -p N -r N               Gate counts in rightmost and middle "
         "chunks\n"
         "                          Omit both to autotune checkpoints\n"
         "  -f FRACTION             Fraction of outer histories (0 < f <= 1)\n"
         "  -t THRESHOLD            Pruning/output threshold (default 1e-8)\n"
         "  -D                      Write zero/rejected outputs too\n"
         "  -v LEVEL                Verbosity (default 1)\n"
#ifdef USE_MPI
         "  --schedule MODE         static-block, static-cyclic, dynamic, "
         "prefetch (default)\n"
         "  -s, --batch-size N       Positive batch size for dynamic/prefetch "
         "(default 32)\n"
#endif
         "  -h, --help              Show this help\n";
}

inline Options parse_options(int argc, char **argv) {
  Options opts;
  const option long_options[] = {
      {"input-bits", required_argument, nullptr, 1000},
      {"output-bits", required_argument, nullptr, 1001},
#ifdef USE_MPI
      {"schedule", required_argument, nullptr, 1002},
      {"batch-size", required_argument, nullptr, 's'},
#endif
      {"build-only", no_argument, nullptr, 'B'},
      {"help", no_argument, nullptr, 'h'},
      {nullptr, 0, nullptr, 0}};
  const auto number = [](const char *text) {
    std::size_t consumed = 0;
    double value = std::stod(text, &consumed);
    if (consumed != std::string(text).size() || !std::isfinite(value))
      throw std::invalid_argument("Invalid number: " + std::string(text));
    return value;
  };
  const auto integer = [&](const char *text) {
    double value = number(text);
    if (value < 0 || value > std::numeric_limits<int>::max() ||
        std::floor(value) != value)
      throw std::invalid_argument("Expected nonnegative integer: " +
                                  std::string(text));
    return static_cast<int>(value);
  };
  int flag;
  while ((flag = getopt_long(argc, argv,
#ifdef USE_MPI
                             "c:i:b:o:p:r:s:f:t:v:DBh",
#else
                             "c:i:b:o:p:r:f:t:v:DBh",
#endif
                             long_options, nullptr)) != -1) {
    switch (flag) {
    case 'c':
      opts.circuit_file = optarg;
      break;
    case 'i':
      opts.input_file = optarg;
      break;
    case 'b':
      opts.output_bits_file = optarg;
      break;
    case 'o':
      opts.output_file = optarg;
      break;
    case 'p':
      opts.chunk2 = integer(optarg);
      break;
    case 'r':
      opts.chunk1 = integer(optarg);
      break;
    case 's':
      opts.batch_size = integer(optarg);
      break;
    case 'f':
      opts.fraction = number(optarg);
      break;
    case 't':
      opts.threshold = number(optarg);
      break;
    case 'v':
      opts.verbosity = integer(optarg);
      break;
    case 'D':
      opts.dense = true;
      break;
    case 'B':
      opts.build_only = true;
      break;
    case 'h':
      opts.help = true;
      break;
    case 1000:
      opts.input_bits = optarg;
      break;
    case 1001:
      opts.output_bits = optarg;
      break;
    case 1002:
      opts.schedule = optarg;
      break;
    default:
      throw std::invalid_argument("Unknown option; use --help");
    }
  }
  if (opts.help)
    return opts;
  if (optind != argc)
    throw std::invalid_argument("Unexpected positional argument");
  if (opts.circuit_file.empty())
    throw std::invalid_argument("-c CIRCUIT is required");
  if ((opts.chunk1 == -1) != (opts.chunk2 == -1))
    throw std::invalid_argument("Set both -p and -r, or neither");
  if (opts.fraction <= 0 || opts.fraction > 1 || opts.threshold < 0)
    throw std::invalid_argument("Require 0 < fraction <= 1 and threshold >= 0");
  if (opts.batch_size == 0)
    throw std::invalid_argument("Batch size must be positive; select static "
                                "scheduling with --schedule");
#ifdef USE_MPI
  if (opts.schedule != "static-block" && opts.schedule != "static-cyclic" &&
      opts.schedule != "dynamic" && opts.schedule != "prefetch")
    throw std::invalid_argument("Unknown schedule: " + opts.schedule);
#endif
  if (!opts.build_only) {
    const bool bits = !opts.input_bits.empty() || !opts.output_bits.empty();
    if (bits) {
      if (opts.input_bits.empty() || opts.output_bits.empty() ||
          !opts.input_file.empty() || !opts.output_bits_file.empty())
        throw std::invalid_argument(
            "Use both --input-bits and --output-bits, without -i/-b");
    } else if (opts.input_file.empty() || opts.output_bits_file.empty() ||
               opts.output_file.empty()) {
      throw std::invalid_argument("File mode requires -i, -b and -o");
    }
  }
  return opts;
}

inline std::vector<bool> basis_bits(const std::string &text) {
  if (text.size() != static_cast<std::size_t>(ParsedCircuit::declared_n) ||
      text.find_first_not_of("01") != std::string::npos)
    throw std::invalid_argument(
        "Basis bitstrings must contain exactly n binary digits, MSB first");
  auto bits = bit_array_from_string(text);
  bits.resize(Circuit::n, false);
  return bits;
}

// Same instrumentation scope for both executables: history evaluation only.
class PerfRegion {
  int fd = -1;

public:
  PerfRegion() {
#if FEYNMAN_ENABLE_LINUX_PERF
    fd =
        open_leader(getpid(), -1, PERF_TYPE_HARDWARE, PERF_COUNT_HW_CPU_CYCLES);
    if (fd == -1)
      throw std::runtime_error("perf_event_open failed");
#endif
  }
  void start() {
#if FEYNMAN_ENABLE_LINUX_PERF
    ioctl(fd, PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP);
    ioctl(fd, PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP);
#endif
  }
  void stop() {
#if FEYNMAN_ENABLE_LINUX_PERF
    ioctl(fd, PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP);
#endif
  }
  ~PerfRegion() {
#if FEYNMAN_ENABLE_LINUX_PERF
    close(fd);
#endif
  }
};

inline void report_circuit(bool print, bool autotuned) {
  if (print) {
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

    printf("For each simulate call we simulate over: \n");
    try {
      const TypeLongInt num_histories_total = mul_checked(
          mul_checked(pow2_checked(Circuit::chunks.at(0).num_artificial,
                                   "Chunk-0 history count"),
                      pow2_checked(Circuit::chunks.at(1).num_artificial,
                                   "Chunk-1 history count"),
                      "Total history count partial product"),
          pow2_checked(Circuit::chunks.at(2).num_artificial,
                       "Chunk-2 history count"),
          "Total history count");
      const TypeLongInt num_histories_parallel = pow2_checked(
          Circuit::chunks.at(2).num_artificial, "Chunk-2 history count");
      std::cout << "  " << type_long_int_to_string(num_histories_total)
                << " histories in total.\n";
      std::cout << "  " << type_long_int_to_string(num_histories_parallel)
                << " histories in parallel.\n";
    } catch (const std::runtime_error &err) {
      std::cout << "  exact total history count unavailable: " << err.what()
                << '\n';
    }
    if (autotuned) {
      std::cout << "Autotuning time: " << Circuit::last_autotune_seconds
                << " seconds (candidates=" << Circuit::last_autotune_candidates
                << ", step_size=" << Circuit::last_autotune_step_size
                << ", best_gate_ops_estimate="
                << type_long_int_to_string(Circuit::last_autotune_best_gate_ops)
                << ", mode=autotuned)\n";
    } else {
      printf("Autotuning time: 0.000000 seconds (candidates=0, step_size=0, "
             "best_gate_ops_estimate=0, mode=fixed)\n");
    }
  }
}

inline void append_stats(std::string &buffer, const std::string &bits,
                         const AmplitudeAbsStats &stats) {
  buffer += bits + ",";
  if (stats.count == 0) {
    buffer += "nan,nan,0,0\n";
  } else {
    buffer += (std::isfinite(stats.min_nonzero_abs)
                   ? real_to_string(stats.min_nonzero_abs)
                   : "nan") +
              "," + real_to_string(stats.max_abs) + "," +
              type_long_int_to_string(stats.count) + "," +
              type_long_int_to_string(stats.count_nonzero) + "\n";
  }
}

inline void run(const Options &opts, const Execution &execution) {
  const memory_profile::Profile memory;
  const auto start_full = get_time();
  const bool print = execution.rank == 0 && opts.verbosity >= 1;
  ParsedCircuit::parse_circuit(opts.circuit_file);
  const bool autotuned = opts.chunk1 == -1;
  if (autotuned)
    Circuit::build_autotuned_circuit();
  else
    Circuit::build_circuit(opts.chunk1, opts.chunk2);
  if (print && opts.verbosity >= 3)
    std::cout << Circuit::circuit_to_string(-1, 2) << '\n';
  report_circuit(print || (opts.build_only && execution.rank == 0), autotuned);
  if (opts.build_only)
    return;

  std::vector<InputBitstrings> inputs;
  std::vector<std::vector<bool>> outputs;
  const bool amplitude_mode = !opts.input_bits.empty();
  if (amplitude_mode) {
    inputs.push_back({basis_bits(opts.input_bits), TypeAmp(1, 0)});
    outputs.push_back(basis_bits(opts.output_bits));
  } else {
    inputs = execution.inputs(opts.input_file, opts.dense);
    outputs = execution.outputs(opts.output_bits_file);
  }
  for (const auto &input : inputs)
    if (input.index.size() < static_cast<std::size_t>(Circuit::n))
      throw std::invalid_argument(
          "Input bitstring width is smaller than the circuit");
  for (const auto &output : outputs)
    if (output.size() < static_cast<std::size_t>(Circuit::n))
      throw std::invalid_argument(
          "Output bitstring width is smaller than the circuit");

  fs::path output_path(opts.output_file);
  if (!opts.output_file.empty() && execution.rank == 0 &&
      output_path.has_parent_path())
    fs::create_directories(output_path.parent_path());
  const auto artifact = [&](const std::string &suffix) {
    return output_path.parent_path() /
           (output_path.stem().string() + "." + suffix);
  };
  const int threads = omp_get_max_threads();
  if (print) {
    std::cout << "Total output bitstrings to simulate: " << outputs.size()
              << '\n'
              << "Execution: schedule=" << opts.schedule
              << " ranks=" << execution.size << '\n'
              << "Starting simulation over all input-output pairs:\n"
              << " -- Total output bitstrings = " << outputs.size()
              << " -- active workers = " << execution.workers(opts.schedule)
              << " - OMP_THREADS per worker = " << threads
              << " - batch_size = " << opts.batch_size << " --:\n";
  }
  std::string amplitudes;
  std::string timings =
      execution.rank == 0 ? "bitstring_hex,elapsed_seconds,status\n" : "";
  std::array<std::string, 3> stats;
  for (auto &buffer : stats)
    if (execution.rank == 0)
      buffer = "bitstring_hex,min_nonzero_abs,max_abs,count,count_nonzero\n";
  uint64_t calls = 0;
  double call_seconds = 0;
  std::size_t processed = 0;
  TypeAmp single_amplitude(0, 0);
  PerfRegion perf;
  execution.barrier();
  const auto start_sim = get_time();
  const std::size_t progress_interval = outputs.size() <= 10    ? 1
                                        : outputs.size() <= 100 ? 10
                                                                : 100;
  const auto process_outputs = [&](std::size_t begin, std::size_t end) {
    for (std::size_t i = begin; i < end; ++i) {
      const auto start_output = get_time();
      TypeAmp amplitude(0, 0);
      SimulateAbsStats abs_stats;
      for (const auto &input : inputs) {
        const auto start_call = get_time();
        amplitude += simulate(outputs[i], input.index, input.amp, opts.fraction,
                              opts.threshold, opts.verbosity, &abs_stats);
        call_seconds += duration<double>(get_time() - start_call).count();
        ++calls;
        Circuit::reset_values_all();
      }
      if (amplitude_mode)
        single_amplitude = amplitude;
      const double seconds =
          duration<double>(get_time() - start_output).count();
      const bool supported = std::abs(amplitude) > opts.threshold;
      const auto bits = bitvector_to_hexstring(outputs[i]);
      timings += bits + "," + real_to_string(seconds) + "," +
                 (supported ? "supported" : "rejected") + "\n";
      append_stats(stats[0], bits, abs_stats.contribution0);
      append_stats(stats[1], bits, abs_stats.contribution1);
      append_stats(stats[2], bits, abs_stats.contribution2);
      if (opts.dense || supported)
        amplitudes += bits + ":" + complex_to_string(amplitude) + "\n";
      ++processed;
      if (opts.verbosity >= 2)
        std::cout << "Rank " << execution.rank << " output " << bits << ": "
                  << seconds << " seconds\n";
      if (print && execution.size == 1 &&
          (processed == outputs.size() || processed % progress_interval == 0)) {
        std::cout << "Progress: processed " << processed << " / "
                  << outputs.size() << " output bitstrings\n";
      }
    }
  };
  perf.start();
  execution.process(outputs.size(), opts.schedule, opts.batch_size,
                    process_outputs);
  perf.stop();
  execution.barrier();
  const double simulation_seconds =
      duration<double>(get_time() - start_sim).count();
  const uint64_t total_calls = execution.sum(calls);
  const double total_call_seconds = execution.sum(call_seconds);
  if (amplitude_mode) {
    const double re =
        execution.sum(static_cast<double>(single_amplitude.real()));
    const double im =
        execution.sum(static_cast<double>(single_amplitude.imag()));
    if (execution.rank == 0)
      std::cout << "Total amplitude: " << complex_to_string(TypeAmp(re, im))
                << '\n';
  }
  const auto start_io = get_time();
  if (!opts.output_file.empty()) {
    execution.write(opts.output_file, amplitudes);
    execution.write(artifact("timeBitstrings.csv").string(), timings);
    for (int i = 0; i < 3; ++i)
      execution.write(
          artifact("contribution" + std::to_string(i) + "AbsMinMax.csv")
              .string(),
          stats[i]);
    const std::string suffix =
        execution.size == 1
            ? "memory.json"
            : "rank" + std::to_string(execution.rank) + ".memory.json";
    memory.write(artifact(suffix));
  }
  execution.barrier();
  const double io_seconds = duration<double>(get_time() - start_io).count();
  const double full_seconds = duration<double>(get_time() - start_full).count();
  if (print) {
    std::cout << "Number of simulate calls: " << total_calls << '\n';
    printf("Total clocktime for all simulate calls: %.9f seconds\n",
           total_call_seconds);
    printf("Average clocktime per simulate call: %.9f seconds\n",
           total_calls ? total_call_seconds / total_calls : 0.0);
    printf("Total clocktime sim for feynman: %.9f seconds\n",
           simulation_seconds);
    printf("Total clocktime writing to disk for feynman: %.9f seconds\n",
           io_seconds);
    printf("Total clocktime (including I/O) for feynman: %.9f seconds\n",
           full_seconds);
  }
}

inline int main_entry(int argc, char **argv) {
  Execution execution(argc, argv);
  std::cout << std::unitbuf;
  std::cerr << std::unitbuf;
  std::setvbuf(stdout, nullptr, _IOLBF, 0);
  try {
    const auto opts = parse_options(argc, argv);
    if (opts.help) {
      if (execution.rank == 0)
        print_help();
    } else {
      run(opts, execution);
    }
  } catch (const std::exception &error) {
    std::cerr << "Rank " << execution.rank << ": " << error.what() << '\n';
    execution.abort();
    return 1;
  }
  return 0;
}
} // namespace feynman

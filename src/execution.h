#pragma once

#include "iofiles.h"
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <stdexcept>
#include <string>
#ifdef USE_MPI
#include "mpiScheduler.h"
#endif

namespace feynman {

// Only the execution layer knows whether this process belongs to an MPI job.
class Execution {
public:
  int rank = 0;
  int size = 1;

  Execution(int &argc, char **&argv) {
#ifdef USE_MPI
    int provided = 0;
    MPI_Init_thread(&argc, &argv, MPI_THREAD_FUNNELED, &provided);
    if (provided < MPI_THREAD_FUNNELED) {
      MPI_Abort(MPI_COMM_WORLD, 1);
      throw std::runtime_error("MPI_THREAD_FUNNELED is required");
    }
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);
#endif
  }
  ~Execution() {
#ifdef USE_MPI
    MPI_Finalize();
#endif
  }
  void abort() const {
#ifdef USE_MPI
    MPI_Abort(MPI_COMM_WORLD, 1);
#endif
  }
  void barrier() const {
#ifdef USE_MPI
    MPI_Barrier(MPI_COMM_WORLD);
#endif
  }
  double sum(double value) const {
#ifdef USE_MPI
    double result = 0;
    MPI_Allreduce(&value, &result, 1, MPI_DOUBLE, MPI_SUM, MPI_COMM_WORLD);
    return result;
#else
    return value;
#endif
  }
  uint64_t sum(uint64_t value) const {
#ifdef USE_MPI
    uint64_t result = 0;
    MPI_Allreduce(&value, &result, 1, MPI_UINT64_T, MPI_SUM, MPI_COMM_WORLD);
    return result;
#else
    return value;
#endif
  }
  std::vector<InputBitstrings> inputs(const std::string &path,
                                      bool dense) const {
#ifdef USE_MPI
    return load_input_bitvectors_from_master(path, dense, rank, MPI_COMM_WORLD);
#else
    return read_input_bitstrings_from_file(path, dense);
#endif
  }
  std::vector<std::vector<bool>> outputs(const std::string &path) const {
#ifdef USE_MPI
    return load_output_bitvectors_from_master(path, rank, MPI_COMM_WORLD);
#else
    return load_output_bitvectors_from_file(path);
#endif
  }
  void write(const std::string &path, const std::string &buffer) const {
#ifdef USE_MPI
    if (write_output_to_disk(path, buffer, rank, MPI_COMM_WORLD) != MPI_SUCCESS)
      throw std::runtime_error("Cannot write output: " + path);
#else
    write_string_to_file(path, buffer);
#endif
  }
  int workers(const std::string &schedule) const {
    return size > 1 && (schedule == "dynamic" || schedule == "prefetch")
               ? size - 1
               : size;
  }

  template <typename F>
  void process(std::size_t total, const std::string &schedule,
               std::size_t batch_size, F &&outputs) const {
    if (size == 1) {
      outputs(0, total);
    } else if (schedule == "static-block") {
      const std::size_t base = total / size, remainder = total % size;
      const std::size_t start =
          base * rank + std::min<std::size_t>(rank, remainder);
      outputs(start,
              start + base + (static_cast<std::size_t>(rank) < remainder));
    } else if (schedule == "static-cyclic") {
      for (std::size_t i = rank; i < total; i += size)
        outputs(i, i + 1);
    } else {
#ifdef USE_MPI
      if (rank == 0) {
        run_master(total, batch_size, MPI_COMM_WORLD);
      } else if (schedule == "prefetch") {
        Prefetcher pf;
        run_worker_with(pf, MPI_COMM_WORLD, outputs);
      } else {
        std::size_t start = 0, count = 0;
        while (request_next_batch(start, count, MPI_COMM_WORLD))
          outputs(start, start + count);
      }
#endif
    }
  }
};
} // namespace feynman

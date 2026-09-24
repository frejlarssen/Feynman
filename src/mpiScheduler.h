#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <mpi.h>

using namespace std;

/**
 * Scheduler for MPI processes
 * Assume MPI rank 0 is the master and all the other processes in the
 * communicator are workers
 */

enum : int {
  TAG_REQUEST = 1, // worker -> master (0-byte ping)
  TAG_WORK = 2,    // master -> worker (payload: start,count)
  TAG_STOP = 3     // master -> worker (no payload)
};

// Send {start,count} to a worker
static inline void send_work(int worker, std::size_t start, std::size_t count,
                             MPI_Comm comm) {
  std::uint64_t payload[2] = {start, count};
  MPI_Send(payload, 2, MPI_UINT64_T, worker, TAG_WORK, comm);
}

// Master process: hands out work on demand
void run_master(std::size_t total, std::size_t batch_size, MPI_Comm comm) {
  int world_size;
  MPI_Comm_size(comm, &world_size);
  int active_workers = std::max(0, world_size - 1);
  std::size_t next_start = 0;

  MPI_Status st;
  // Serve requests until every worker has received STOP
  while (active_workers > 0) {
    // Wait for worker request
    MPI_Recv(nullptr, 0, MPI_BYTE, MPI_ANY_SOURCE, TAG_REQUEST, comm, &st);
    int w = st.MPI_SOURCE;

    if (next_start >= total) {
      // No more work: stop this worker
      MPI_Send(nullptr, 0, MPI_BYTE, w, TAG_STOP, comm);
      --active_workers;
    } else {
      std::size_t count = std::min(batch_size, total - next_start);
      send_work(w, next_start, count, comm);
      next_start += count;
    }
  }
}

// Worker: one-step receive
bool request_next_batch(std::size_t &start, std::size_t &count, MPI_Comm comm) {
  // Ask for work
  MPI_Send(nullptr, 0, MPI_BYTE, 0, TAG_REQUEST, comm);

  MPI_Status st;
  std::uint64_t payload[2];
  // Master sends either STOP (0B) or WORK (2x uint64)
  MPI_Recv(payload, 2, MPI_UINT64_T, 0, MPI_ANY_TAG, comm, &st);

  if (st.MPI_TAG == TAG_STOP)
    return false;
  start = payload[0];
  count = payload[1];
  return true;
}

struct Prefetcher {
  MPI_Request req = MPI_REQUEST_NULL;
  MPI_Status st{};
  std::uint64_t buf[2];

  // Get the very first batch (blocking)
  bool first(std::size_t &start, std::size_t &count, MPI_Comm comm) {
    MPI_Send(nullptr, 0, MPI_BYTE, 0, TAG_REQUEST, comm);
    MPI_Recv(buf, 2, MPI_UINT64_T, 0, MPI_ANY_TAG, comm, &st);
    if (st.MPI_TAG == TAG_STOP)
      return false;
    start = buf[0];
    count = buf[1];
    return true;
  }

  // While computing the current batch, ask for the next one
  void prefetch_next(MPI_Comm comm) {
    MPI_Send(nullptr, 0, MPI_BYTE, 0, TAG_REQUEST, comm);
    MPI_Irecv(buf, 2, MPI_UINT64_T, 0, MPI_ANY_TAG, comm, &req);
  }

  // After compute, finish the nonblocking receive
  bool finish(std::size_t &start, std::size_t &count) {
    MPI_Wait(&req, &st);
    if (st.MPI_TAG == TAG_STOP)
      return false;
    start = buf[0];
    count = buf[1];
    return true;
  }
};

template <typename PF, typename Func>
void run_worker_with(PF &pf, MPI_Comm comm, Func &&process_outputs) {
  std::size_t start = 0, count = 0;
  if (!pf.first(start, count, comm))
    return;
  for (;;) {
    pf.prefetch_next(comm); // overlap comm with compute
    process_outputs(start, start + count);
    if (!pf.finish(start, count))
      break; // next becomes current
  }
}

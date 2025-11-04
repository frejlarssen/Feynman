#pragma once
#include <mpi.h>

/**
 * Scheduler for MPI processes
 * Assume MPI rank 0 is the master and all the other processes in the communicator are workers
 */

enum : int {
    TAG_REQUEST = 1,   // worker -> master (0-byte ping)
    TAG_WORK    = 2,   // master -> worker (payload: start,count)
    TAG_STOP    = 3    // master -> worker (no payload)
};

// Send {start,count} to a worker
static inline void send_work(int worker, std::size_t start, std::size_t count, MPI_Comm comm) {
    std::size_t payload[2] = {start, count};
    MPI_Send(payload, 2, MPI_UINT64_T, worker, TAG_WORK, comm);
}

// Master process: hands out work on demand
void run_master(std::size_t total, std::size_t batch_size, MPI_Comm comm) {
    int world_size; MPI_Comm_size(comm, &world_size);
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

// Worker: request work until STOP; returns false when stopped
bool request_next_batch(std::size_t &start, std::size_t &count, MPI_Comm comm) {
    MPI_Status st;
    // Ask for work
    MPI_Send(nullptr, 0, MPI_BYTE, 0, TAG_REQUEST, comm);
    // Receive either WORK (with payload) or STOP
    // Master will answer immediately with either WORK or STOP; just Recv
    MPI_Probe(0, MPI_ANY_TAG, comm, &st);
    if (st.MPI_TAG == TAG_STOP) {
        MPI_Recv(nullptr, 0, MPI_BYTE, 0, TAG_STOP, comm, MPI_STATUS_IGNORE);
        return false;
    }
    // WORK payload: two std::size_t
    std::size_t payload[2];
    MPI_Recv(payload, 2, MPI_UINT64_T, 0, TAG_WORK, comm, MPI_STATUS_IGNORE);
    start = payload[0];
    count = payload[1];
    return true;
}

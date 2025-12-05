#include <mpi.h>
#include "typedef.h"
#include "utils.h"

void global_sum_reduce(const unordered_statevector &local_sv, ordered_statevector* global_sv_recv_buf, MPI_Comm comm) {
    int rank, size;
    MPI_Comm_rank(comm, &rank);
    MPI_Comm_size(comm, &size);

    std::vector<uint8_t> local_buf = serialize_statevector(local_sv);
    int local_size = local_buf.size();

    // Gather sizes
    std::vector<int> recv_sizes(size);
    MPI_Gather(&local_size, 1, MPI_INT,
               recv_sizes.data(), 1, MPI_INT, 0, comm);

    std::vector<int> displs;
    std::vector<uint8_t> recv_buf;

    if (rank == 0) {
        displs.resize(size);
        int total = 0;
        for (int i = 0; i < size; i++) {
            displs[i] = total;
            total += recv_sizes[i];
        }
        recv_buf.resize(total);
    }

    MPI_Gatherv(local_buf.data(), local_size, MPI_BYTE,
                recv_buf.data(), recv_sizes.data(), displs.data(), MPI_BYTE,
                0, comm);

    if (rank == 0) {
        ordered_statevector &global_sv = *global_sv_recv_buf;

        for (int i = 0; i < size; i++) {
            const uint8_t *ptr = recv_buf.data() + displs[i];
            auto sv = deserialize_statevector(ptr);

            // Merge
            for (auto &p : sv) {
                global_sv[p.first] += p.second;
            }
        }
    }
}
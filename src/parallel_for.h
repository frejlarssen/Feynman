#pragma once
#include <thread>
#include <vector>
#include <complex>
#include <algorithm>
#include <functional>

#ifdef USE_OPENMP
    #include <omp.h>
#elif defined(USE_MPI)
    #include <mpi.h>
#endif

inline void parallel_for(size_t start, size_t end, const std::function<void(size_t)>& func) {
#ifdef USE_OPENMP
    #pragma omp parallel for
    for (size_t i = start; i < end; ++i)
        func(i);

#elif defined(USE_MPI)
    int rank, size;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);

    //printf("MPI rank %d of %d starting parallel_for from %lu to %lu\n", rank, size, start, end);

    size_t total = end - start;
    size_t chunk_size = (total + size - 1) / size;

    size_t chunk_start = start + rank * chunk_size;
    size_t chunk_end   = min(chunk_start + chunk_size, end);

    for (size_t i = chunk_start; i < chunk_end; ++i)
        func(i);

    MPI_Barrier(MPI_COMM_WORLD);

#else
    unsigned int num_threads = std::thread::hardware_concurrency();
    if (num_threads == 0) num_threads = 4;

    size_t chunk_size = (end - start + num_threads - 1) / num_threads;
    vector<thread> threads;

    for (unsigned int t = 0; t < num_threads; ++t) {
        threads.emplace_back([=, &func]() {
            size_t chunk_start = start + t * chunk_size;
            size_t chunk_end = min(chunk_start + chunk_size, end);
            for (size_t i = chunk_start; i < chunk_end; ++i)
                func(i);
        });
    }
    for (auto& th : threads)
        th.join();
#endif
}

// sum complex values across all indices
inline complex<float>
parallel_reduce(size_t start, size_t end,
                const function<complex<float>(size_t)>& func)
{
#ifdef USE_OPENMP
    complex<float> result(0.0f, 0.0f);
    #pragma omp parallel for reduction(+:result)
    for (size_t i = start; i < end; ++i)
        result += func(i);
    return result;

#elif defined(USE_MPI)
    int rank, size;
    MPI_Comm_rank(MPI_COMM_WORLD, &rank);
    MPI_Comm_size(MPI_COMM_WORLD, &size);

    size_t total = end - start;
    size_t chunk_size = (total + size - 1) / size;
    size_t chunk_start = start + rank * chunk_size;
    size_t chunk_end   = min(chunk_start + chunk_size, end);

    complex<float> local_sum(0.0f, 0.0f);
    for (size_t i = chunk_start; i < chunk_end; ++i)
        local_sum += func(i);

    complex<float> global_sum(0.0f, 0.0f);

    // MPI can’t directly reduce complex<float>, so treat as 2 floats
    float local_data[2]  = { local_sum.real(), local_sum.imag() };
    float global_data[2] = { 0.0f, 0.0f };

    MPI_Allreduce(local_data, global_data, 2, MPI_FLOAT, MPI_SUM, MPI_COMM_WORLD);

    global_sum = { global_data[0], global_data[1] };
    return global_sum;

#else
    unsigned int num_threads = thread::hardware_concurrency();
    if (num_threads == 0) num_threads = 4;

    size_t chunk_size = (end - start + num_threads - 1) / num_threads;
    vector<thread> threads;
    vector<complex<float>> partial(num_threads, {0.0f, 0.0f});

    for (unsigned int t = 0; t < num_threads; ++t) {
        threads.emplace_back([=, &func, &partial]() {
            size_t chunk_start = start + t * chunk_size;
            size_t chunk_end = min(chunk_start + chunk_size, end);
            complex<float> local(0.0f, 0.0f);
            for (size_t i = chunk_start; i < chunk_end; ++i)
                local += func(i);
            partial[t] = local;
        });
    }
    for (auto& th : threads)
        th.join();

    std::complex<float> total(0.0f, 0.0f);
    for (auto& val : partial)
        total += val;
    return total;
#endif
}

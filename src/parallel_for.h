#pragma once
#include <thread>
#include <vector>
#include <complex>
#include <algorithm>
#include <functional>

#ifdef USE_OPENMP
    #include <omp.h>
#endif

inline void parallel_for(size_t start, size_t end, const std::function<void(size_t)>& func) {
#ifdef USE_OPENMP
    #pragma omp parallel for
    for (size_t i = start; i < end; ++i)
        func(i);
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

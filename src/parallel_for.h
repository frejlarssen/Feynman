#pragma once
#include <thread>
#include <vector>
#include <complex>
#include <algorithm>
#include <functional>

#ifdef USE_OPENMP
    #include <omp.h>
#endif
template<typename F>
inline void parallel_for(size_t start, size_t end, F&& func) {
#ifdef USE_OPENMP
    #pragma omp parallel
    {
        #pragma omp single nowait
        {
            const int T = 4 * omp_get_num_threads();      // threads in this team
            #pragma omp taskloop num_tasks(T)         // at most T tasks (hint)
            for (std::size_t i = start; i < end; ++i) func(i);
        }
    }
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
template<typename F>
inline complex<float>
parallel_reduce(size_t start, size_t end, F&& func)
{
#ifdef USE_OPENMP
    float re = 0.0f, im = 0.0f;
    #pragma omp parallel for reduction(+:re, im)
    for (size_t i = start; i < end; ++i) {
        auto v = func(i);
        re += v.real();
        im += v.imag();
    }
    std::complex<float> result(re, im);
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

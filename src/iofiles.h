#pragma once

#include <mpi.h>
#include <string>
#include <vector>
#include <cstdint>
#include <complex>
#include <fstream>
#include <charconv>   // for from_chars (C++17)
#include <type_traits>

#include "typedef.h"
#include "utils.h"



struct InputBitstrings {
    TypeLongInt index;           // basis-state index
    std::complex<float> amp;          // amplitude
};
static_assert(std::is_trivially_copyable_v<InputBitstrings>);

static inline bool parse_int(const char* b, const char* e, TypeLongInt& out) {
    auto res = std::from_chars(b, e, out, 10);
    return res.ec == std::errc{} && res.ptr == e;
}

// Load & parse once
static inline std::vector<InputBitstrings>
read_input_bitstrings(const std::string& path, const bool dense){
    std::ifstream in(path);
    if (!in) throw std::runtime_error("Cannot open input bitstring file " + path);

    std::vector<InputBitstrings> entries;
    entries.reserve(1 << 16);

    std::string line;
    TypeLongInt next_dense_idx = 0;
    while (std::getline(in, line)) {
        if (line.empty()) continue;

        InputBitstrings e{};
        if (dense) {
            e.index = next_dense_idx++;                  // 0,1,2,...
            e.amp   = string_to_complex(line);
        } else {
            const size_t c = line.find(':');
            if (c == string::npos)
                throw std::runtime_error("Bad line in input: " + line);
            const string idx_str = line.substr(0, c);
            const string amp_str = line.substr(c + 1);

            TypeLongInt idx{};
            if (!parse_int(idx_str.data(), idx_str.data() + idx_str.size(), idx))
                throw std::runtime_error("Bad index: " + idx_str);

            e.index = idx;
            e.amp   = string_to_complex(amp_str);
        }
        entries.push_back(e);
    }
    return entries;
}


inline std::vector<InputBitstrings>
load_input_bitstrings_from_master(const std::string& path, const bool dense,
                                    const int world_rank, MPI_Comm comm){

    std::vector<InputBitstrings> input_bitstrings;
    std::size_t n_input_bitstrings = 0;
    if (world_rank == 0) {
        input_bitstrings = read_input_bitstrings(path, dense);
        n_input_bitstrings = input_bitstrings.size();
    }
    // broadcast size
    MPI_Bcast(&n_input_bitstrings, 1, MPI_UNSIGNED_LONG_LONG, 0, comm);
    // resize & broadcast
    if (world_rank != 0) input_bitstrings.resize(n_input_bitstrings);
    // !! currently can send INT_MAX number of data --> implemente broadcast as loop since we could have up to 2^n-1 bitstrings !!
    MPI_Bcast(input_bitstrings.data(), static_cast<int>(n_input_bitstrings * sizeof(InputBitstrings)), MPI_BYTE, 0, comm);
    return input_bitstrings;
}


static inline std::vector<std::size_t>
read_output_bitstrings(const std::string& path){
    
    std::vector<std::size_t> output_bitstrings;
    std::ifstream in(path);
    if (!in) {
        throw std::runtime_error("Cannot open output bitstring file: " + path);
    }
    std::string line;
    while (std::getline(in, line)) {
        std::string_view sv(line);

        // trim leading/trailing whitespace
        auto l = sv.find_first_not_of(" \t\r\n");
        if (l == std::string_view::npos) continue; // empty/whitespace-only
        sv.remove_prefix(l);
        auto r = sv.find_last_not_of(" \t\r\n");
        sv = sv.substr(0, r + 1);

        // parse integer (base 10) using from_chars
        std::size_t tmp = 0;
        const char* first = sv.data();
        const char* last  = sv.data() + sv.size();
        auto [ptr, ec] = std::from_chars(first, last, tmp, 10);

        if (ec != std::errc{} || ptr != last) {
            throw std::runtime_error("Invalid integer line in " + path + ": \"" + std::string(sv) + "\"");
        }
        if (tmp > static_cast<unsigned long long>(std::numeric_limits<std::size_t>::max())) {
            throw std::runtime_error("Integer out of range for size_t in: \"" + std::string(sv) + "\"");
        }
        output_bitstrings.push_back(static_cast<std::size_t>(tmp));
    }
    return output_bitstrings;
}

inline std::vector<std::size_t>
load_output_bitstrings_from_master(const std::string& path, const int world_rank, MPI_Comm comm){

    std::vector<std::size_t> output_bitstrings;
    std::size_t n_output_bitstrings = 0;
    if (world_rank == 0) {
        output_bitstrings = read_output_bitstrings(path);
        n_output_bitstrings = output_bitstrings.size();
    }
    // broadcast size
    unsigned long long sz64 = static_cast<unsigned long long>(n_output_bitstrings);
    MPI_Bcast(&sz64, 1, MPI_UNSIGNED_LONG_LONG, 0, comm);
    n_output_bitstrings = static_cast<std::size_t>(sz64);

    // resize & broadcast
    if (world_rank != 0) output_bitstrings.resize(n_output_bitstrings);
    const int INT_MAX_COUNT = std::numeric_limits<int>::max();
    MPI_Datatype mpi_size_t;
    MPI_Type_match_size(MPI_TYPECLASS_INTEGER, sizeof(std::size_t), &mpi_size_t);
    std::size_t offset = 0;
    while (offset < n_output_bitstrings){
        const std::size_t remaining = n_output_bitstrings - offset;
        const int chunk = static_cast<int>(remaining > static_cast<std::size_t>(INT_MAX_COUNT) ? INT_MAX_COUNT : remaining);
        MPI_Bcast(output_bitstrings.data() + offset, chunk, mpi_size_t, 0, comm);
        offset += static_cast<std::size_t>(chunk);
    }
    return output_bitstrings;
}


inline int write_output_to_disk(const std::string& filename,
                         const std::string& local_buf,
                         const int world_rank, MPI_Comm comm)
{
    MPI_File fh;
    if (world_rank == 0) MPI_File_delete(filename.c_str(), MPI_INFO_NULL);
    MPI_Barrier(comm);

    int rc = MPI_File_open(comm, filename.c_str(), MPI_MODE_CREATE | MPI_MODE_WRONLY,
                           MPI_INFO_NULL, &fh);

    MPI_Offset my_bytes  = static_cast<MPI_Offset>(local_buf.size());
    MPI_Offset my_offset = 0;
    MPI_Exscan(&my_bytes, &my_offset, 1, MPI_OFFSET, MPI_SUM, comm);
    if (world_rank == 0) my_offset = 0;

    MPI_Status st;
    MPI_File_write_at_all(fh, my_offset,
                          const_cast<char*>(local_buf.data()),
                          static_cast<int>(my_bytes),
                          MPI_BYTE, &st);
    MPI_File_close(&fh);
    return rc;
}
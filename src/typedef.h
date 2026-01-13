#pragma once

#include <vector>
#include <map>
#include <unordered_map>
#include <complex>
#include <bitset>

#define STR_IMPL(x) #x
#define STR(x) STR_IMPL(x)

// Define bitstring size in bytes (the string representation would be 8x this)
#define BITSTRING_SIZE 8

// tune to cpu cache line size such that uint8 * PADDING = cache line size
// for x86
// constexpr int PADDING = 64;
// for ARM
// constexpr int PADDING = 256;
// for large datastructures
constexpr int PADDING = 1;

// Select type

//using TypeLongInt = __int128;

//Fall back for ARM
using TypeLongInt = long long;

using bitstr = std::bitset<BITSTRING_SIZE * 8>;  // 8 bits per byte
using amplitude = std::complex<float>;

struct StatevectorEntry {
    bitstr index;
    amplitude amp;
};

// Used for output, since we need fast access to amplitudes by index.
using unordered_statevector = std::unordered_map<bitstr, amplitude>;

struct BitstrLess {
    bool operator()(bitstr const& a, bitstr const& b) const {
        // compare from MSB to LSB:
        for (int i = bitstr().size() - 1; i >= 0; --i) {
            if (a[i] != b[i])
                return a[i] < b[i];
        }
        return false;
    }
};

using ordered_statevector = std::map<bitstr, amplitude, BitstrLess>;
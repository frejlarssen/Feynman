#pragma once
#include <chrono>
#include <iostream>
#include <sstream>
#include <cstdarg>
#include <vector>
#include <cstdio>
#include "typedef.h"
#include <string>
#include <cstring>

#include <sys/prctl.h>
#include <linux/prctl.h>
#include <linux/perf_event.h>
#include <sys/syscall.h>
#include <sys/ioctl.h>
#include <unistd.h>
#include <iostream>

using namespace std;
using namespace std::chrono;


static int
open_leader(pid_t pid, int cpu, uint64_t type, uint64_t config) {
  struct perf_event_attr attr;
  memset(&attr, 0, sizeof(attr));
  attr.type = type;              // e.g., PERF_TYPE_HARDWARE
  attr.config = config;          // e.g., PERF_COUNT_HW_CPU_CYCLES
  attr.size = sizeof(attr);
  attr.disabled = 1;             // start disabled
  attr.inherit = 1;              // include child threads
  attr.exclude_kernel = 1;       // user-space only (optional)

  return syscall(__NR_perf_event_open, &attr, pid, cpu, -1, 0);
}


std::string replace_filename(const std::string& path_str, const std::string& new_filename){
    const auto pos = path_str.find_last_of("/\\");
    if (pos == std::string::npos) return new_filename;
    return path_str.substr(0, pos + 1) + new_filename;
}


inline duration<double> zero_duration() {
    return duration<double>::zero();
}

inline steady_clock::time_point get_time() {
  return steady_clock::now();
}

inline duration<double> get_duration(const steady_clock::time_point& start,
                          const steady_clock::time_point& end) {
  return end - start;
}

inline double duration_to_double(duration<double> duration) {
    return duration.count();
}

inline double duration_to_double(const steady_clock::time_point& start,
                          const steady_clock::time_point& end) {
    duration<double> dur = end - start;
    return dur.count();
}

// printf-style function that writes to any std::ostream safely
// Let's you write to a buffer and then output when desired.
void fprintf_stream(std::ostream& os, const char* fmt, ...) {
    va_list args;

    // Compute length of the formatted string
    va_start(args, fmt);
    int len = vsnprintf(nullptr, 0, fmt, args);
    va_end(args);

    if (len < 0) {
        // Formatting error
        return;
    }

    // Temporary buffer. +1 for null terminator
    std::vector<char> buffer(len + 1);

    // Format the string into the buffer
    va_start(args, fmt);
    vsnprintf(buffer.data(), buffer.size(), fmt, args);
    va_end(args);

    os << buffer.data();
}

const vector<bool> bit_array_from_string(const string& s) {
    vector<bool> bits(s.size());
    for (size_t i = 0; i < s.size(); i++) {
        if (s.at(i) == '1') {
            bits.at(s.size() -1 - i) = true;
        } else if (s.at(i) == '0') {
            bits.at(s.size() -1 - i) = false;
        } else {
            cerr << "Invalid bitstring!" << endl;
            exit(1);
        }
    }
    return bits;
}

const string string_from_bit_array(const vector<bool> bit_arr) {
    string str = "";
    for (int i = 0; i < bit_arr.size(); i++) {
        if (bit_arr.at(bit_arr.size()-1 - i)) {
            str += "q" + to_string(bit_arr.size()-1 - i) + "=1";
        } else {
            str += "q" + to_string(bit_arr.size()-1 - i) + "=0";
        }
    }
    return str;
}

const vector<bool> bit_array_from_int(TypeLongInt value, int n) {
    vector<bool> bits(n, false);
    for (int i = 0; i < n; i++) {
        bits[i] = (value >> i) & 1;
    }
    return bits;
}

const complex<float> string_to_complex(const string& s) {
    size_t plus_pos = s.find('+', 1); // start at 1 to avoid leading +
    size_t i_pos = s.find('i', 1);
    if (plus_pos == string::npos || i_pos == string::npos) {
        cerr << "Invalid complex string: " << s << endl;
        exit(1);
    }
    float real_part = std::stof(s.substr(0, plus_pos));
    float imag_part = std::stof(s.substr(plus_pos + 1, i_pos - plus_pos - 1));
    return complex<float>(real_part, imag_part);
}

template<typename Tdata>
string int128_to_string(Tdata value) {
    if (value == 0) return "0";
    
    bool negative = value < 0;
    Tdata temp = negative ? -value : value;

    string result;
    while (temp > 0) {
        int digit = temp % 10;
        result += '0' + digit;
        temp /= 10;
    }

    if (negative) result += '-';
    reverse(result.begin(), result.end());
    return result;
}

TypeLongInt string_to_int128(const string& s) {
    TypeLongInt result = 0;
    size_t start = 0;
    bool negative = false;

    if (s[0] == '-') {
        negative = true;
        start = 1;
    }

    for (size_t i = start; i < s.size(); i++) {
        result = result * 10 + (s[i] - '0');
    }

    return negative ? -result : result;
}

string bitstr_to_hexstring(const bitstr& bits, int nr_qubits = -1) {
    if (nr_qubits == -1) {
        nr_qubits = BITSTRING_SIZE * 8;
    }

    std::ostringstream oss;
    oss << "0x";
    for (int i = (nr_qubits + 3) / 4 - 1; i >= 0; i--) {
        uint8_t nibble = 0;
        for (int j = 0; j < 4; j++) {
            if (bits.test(i * 4 + j)) {
                nibble |= (1 << j);
            }
        }
        oss << std::hex << std::uppercase << (int)nibble;
    }
    return oss.str();
}

bitstr hexstring_to_bitstr(const string& hexstr) {
    string hex = hexstr;
    if (hex.size() >= 2 && hex[0] == '0' && (hex[1] == 'x' || hex[1] == 'X')) {
        hex = hex.substr(2);
    }

    bitstr bits;
    size_t n = hex.size();
    for (size_t i = 0; i < n; i++) {
        char c = hex[n - 1 - i]; // reverse for little-endian
        uint8_t value;
        if (c >= '0' && c <= '9') {
            value = c - '0';
        } else if (c >= 'A' && c <= 'F') {
            value = c - 'A' + 10;
        } else if (c >= 'a' && c <= 'f') {
            value = c - 'a' + 10;
        } else {
            cerr << "Invalid hex character: " << c << endl;
            exit(1);
        }

        for (int j = 0; j < 4; j++) {
            if (value & (1 << j)) {
                bits.set(i * 4 + j);
            }
        }
    }

    return bits;
}

static inline void serialize_bitstr(const bitstr &b, std::vector<uint8_t> &out) {
    // for each byte in b
    for (size_t i = 0; i < b.size(); i += 8) {
        uint8_t byte = 0;
        for (size_t j = 0; j < 8; j++) {
            if (b.test(i + j))
                byte |= (1u << j);
        }
        out.push_back(byte);
    }
}

static inline bitstr deserialize_bitstr(const uint8_t *&ptr) {
    bitstr b;
    for (size_t i = 0; i < b.size(); i += 8) {
        uint8_t byte = *ptr++;
        for (size_t j = 0; j < 8; j++) {
            if (byte & (1u << j))
                b.set(i + j);
        }
    }
    return b;
}

std::vector<uint8_t> serialize_statevector(const unordered_statevector &sv) {
    std::vector<uint8_t> buf;

    uint64_t count = sv.size();
    buf.insert(buf.end(), (uint8_t *)&count, (uint8_t *)&count + sizeof(count));

    for (auto &p : sv) {
        serialize_bitstr(p.first, buf);

        double real = p.second.real();
        double imag = p.second.imag();
        buf.insert(buf.end(), (uint8_t *)&real, (uint8_t *)&real + sizeof(real));
        buf.insert(buf.end(), (uint8_t *)&imag, (uint8_t *)&imag + sizeof(imag));
    }
    return buf;
}

unordered_statevector deserialize_statevector(const uint8_t *buf) {
    const uint8_t *ptr = buf;

    uint64_t count = *(uint64_t *)ptr;
    ptr += sizeof(uint64_t);

    unordered_statevector sv;
    sv.reserve(count);

    for (uint64_t i = 0; i < count; i++) {
        bitstr key = deserialize_bitstr(ptr);

        double real = *(double *)ptr; ptr += sizeof(double);
        double imag = *(double *)ptr; ptr += sizeof(double);

        sv[key] += amplitude(real, imag);  // sum here in case of duplicates
    }
    return sv;
}
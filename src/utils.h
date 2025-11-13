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

string bitvector_to_hexstring(vector<bool> bits) {
    const size_t n = bits.size();
    
    const size_t n_hexchars = (n + 3) / 4; // 4 bits per hex char
    string hexstr(n_hexchars, '0');

    for (size_t i = 0; i < n; i++) {
        if (bits[i]) {
            size_t hex_index = i / 4;
            size_t bit_index = i % 4;
            char& hex_char = hexstr[hex_index];
            if (hex_char >= '0' && hex_char <= '9') {
                hex_char = "0123456789ABCDEF"[hex_char - '0' + (1 << bit_index)];
            } else {
                hex_char = "0123456789ABCDEF"[hex_char - 'A' + 10 + (1 << bit_index)];
            }
        }
    }

    // Reverse for little-endian
    reverse(hexstr.begin(), hexstr.end());
    return "0x" + hexstr;
}

vector<bool> hexstring_to_bitvector(const string& hexstr) {
    string s = hexstr;
    if (s.size() >= 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
        s = s.substr(2); // Remove 0x
    }

    reverse(s.begin(), s.end()); // Reverse for LSB first
    vector<bool> bits;
    bits.reserve(s.size() * 4); // 4 bits per hex char

    for (char c : s) {
        uint8_t nibble;
        //printf("c: %c\n", c);
        if (c >= '0' && c <= '9') {
            nibble = c - '0';
        } else if (c >= 'a' && c <= 'f') {
            nibble = c - 'a' + 10;
        } else if (c >= 'A' && c <= 'F') {
            nibble = c - 'A' + 10;
        } else {
            throw std::runtime_error("Invalid hex character in string: " + hexstr);
        }
        for (int i = 0; i < 4; i++) { // LSB first
            bits.push_back((nibble >> i) & 1);
        }
    }
    return bits;
}
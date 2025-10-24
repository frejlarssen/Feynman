#include <chrono>
#include <iostream>
#include <sstream>
#include <cstdarg>
#include <vector>
#include <cstdio>

using namespace std;
using namespace std::chrono;

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

const vector<bool> bit_array_from_int(u_int64_t value, int n) {
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
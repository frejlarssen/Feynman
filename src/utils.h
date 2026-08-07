#pragma once
#include "typedef.h"
#include <algorithm>
#include <chrono>
#include <complex>
#include <cstdarg>
#include <cstdio>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <limits>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/syscall.h>
#include <unistd.h>
#include <vector>

#ifndef FEYNMAN_ENABLE_LINUX_PERF
#define FEYNMAN_ENABLE_LINUX_PERF 0
#endif

#if FEYNMAN_ENABLE_LINUX_PERF
#if !defined(__linux__)
#error "FEYNMAN_ENABLE_LINUX_PERF requires Linux perf_event support."
#endif
#include <linux/perf_event.h>
#include <sys/ioctl.h>
#endif

using namespace std;
using namespace std::chrono;

#if FEYNMAN_ENABLE_LINUX_PERF
static long int open_leader(pid_t pid, int cpu, uint64_t type,
                            uint64_t config) {
  struct perf_event_attr attr;
  memset(&attr, 0, sizeof(attr));
  attr.type = type;     // e.g., PERF_TYPE_HARDWARE
  attr.config = config; // e.g., PERF_COUNT_HW_CPU_CYCLES
  attr.size = sizeof(attr);
  attr.disabled = 1;       // start disabled
  attr.inherit = 1;        // include child threads
  attr.exclude_kernel = 1; // user-space only (optional)

  return syscall(__NR_perf_event_open, &attr, pid, cpu, -1, 0);
}
#endif

std::string replace_filename(const std::string &path_str,
                             const std::string &new_filename) {
  const auto pos = path_str.find_last_of("/\\");
  if (pos == std::string::npos)
    return new_filename;
  return path_str.substr(0, pos + 1) + new_filename;
}

inline duration<double> zero_duration() { return duration<double>::zero(); }

inline steady_clock::time_point get_time() { return steady_clock::now(); }

inline duration<double> get_duration(const steady_clock::time_point &start,
                                     const steady_clock::time_point &end) {
  return end - start;
}

inline double duration_to_double(duration<double> duration) {
  return duration.count();
}

inline double duration_to_double(const steady_clock::time_point &start,
                                 const steady_clock::time_point &end) {
  duration<double> dur = end - start;
  return dur.count();
}

inline TypeLongInt type_long_int_max() {
  return std::numeric_limits<TypeLongInt>::max();
}

inline constexpr int type_long_int_value_bits() {
  return static_cast<int>(sizeof(TypeLongInt) * 8) - 1;
}

inline constexpr int max_exact_pow2_exponent() {
  return type_long_int_value_bits() - 1;
}

inline TypeLongInt pow2_saturated(int exponent) {
  if (exponent < 0) {
    return 0;
  }
  if (exponent > max_exact_pow2_exponent()) {
    return type_long_int_max();
  }
  return TypeLongInt(1) << exponent;
}

inline TypeLongInt mul_saturated(TypeLongInt a, TypeLongInt b) {
  if (a == 0 || b == 0) {
    return 0;
  }
  const TypeLongInt max_value = type_long_int_max();
  if (a > max_value / b) {
    return max_value;
  }
  return a * b;
}

inline TypeLongInt add_checked(TypeLongInt a, TypeLongInt b,
                               const std::string &context) {
  const TypeLongInt max_value = type_long_int_max();
  if (a > max_value - b) {
    throw std::runtime_error(context + " exceeds TypeLongInt capacity.");
  }
  return a + b;
}

inline TypeLongInt mul_checked(TypeLongInt a, TypeLongInt b,
                               const std::string &context) {
  if (a == 0 || b == 0) {
    return 0;
  }
  const TypeLongInt max_value = type_long_int_max();
  if (a > max_value / b) {
    throw std::runtime_error(context + " exceeds TypeLongInt capacity.");
  }
  return a * b;
}

// printf-style function that writes to any std::ostream safely
// Let's you write to a buffer and then output when desired.
void fprintf_stream(std::ostream &os, const char *fmt, ...) {
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

const vector<bool> bit_array_from_string(const string &s) {
  vector<bool> bits(s.size());
  for (size_t i = 0; i < s.size(); i++) {
    if (s.at(i) == '1') {
      bits.at(s.size() - 1 - i) = true;
    } else if (s.at(i) == '0') {
      bits.at(s.size() - 1 - i) = false;
    } else {
      cerr << "Invalid bitstring!" << '\n';
      exit(1);
    }
  }
  return bits;
}

const string string_from_bit_array(const vector<bool> bit_arr) {
  string str = "";
  for (int i = 0; i < bit_arr.size(); i++) {
    if (bit_arr.at(bit_arr.size() - 1 - i)) {
      str += "q" + to_string(bit_arr.size() - 1 - i) + "=1";
    } else {
      str += "q" + to_string(bit_arr.size() - 1 - i) + "=0";
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

inline std::string real_to_string(TypeAmpReal value) {
  std::ostringstream oss;
  oss << std::scientific
      << std::setprecision(std::numeric_limits<TypeAmpReal>::max_digits10)
      << value;
  return oss.str();
}

inline std::string complex_to_string(const TypeAmp &value) {
  return real_to_string(value.real()) + "+" + real_to_string(value.imag()) +
         "i";
}

const TypeAmp string_to_complex(const string &s) {
  const size_t i_pos = s.find_last_of('i');
  if (i_pos == string::npos || i_pos != s.size() - 1) {
    cerr << "Invalid complex string: " << s << '\n';
    exit(1);
  }

  size_t split_pos = string::npos;
  for (size_t pos = 1; pos < i_pos; ++pos) {
    const char ch = s[pos];
    if ((ch == '+' || ch == '-') && s[pos - 1] != 'e' && s[pos - 1] != 'E') {
      split_pos = pos;
    }
  }
  if (split_pos == string::npos) {
    cerr << "Invalid complex string: " << s << '\n';
    exit(1);
  }

  TypeAmpReal real_part = std::stod(s.substr(0, split_pos));
  TypeAmpReal imag_part = std::stod(s.substr(split_pos, i_pos - split_pos));
  return TypeAmp(real_part, imag_part);
}

template <typename Tdata> string int128_to_string(Tdata value) {
  if (value == 0)
    return "0";

  bool negative = value < 0;
  Tdata temp = negative ? -value : value;

  string result;
  while (temp > 0) {
    const char digit = temp % 10;
    result += '0' + digit;
    temp /= 10;
  }

  if (negative)
    result += '-';
  reverse(result.begin(), result.end());
  return result;
}

inline string type_long_int_to_string(TypeLongInt value) {
  return int128_to_string<TypeLongInt>(value);
}

inline TypeLongInt pow2_checked(int exponent, const std::string &context) {
  if (exponent < 0) {
    throw std::runtime_error(context + " must be non-negative.");
  }
  if (exponent > max_exact_pow2_exponent()) {
    throw std::runtime_error(
        context + " requires 2^" + std::to_string(exponent) +
        ", which exceeds scalar TypeLongInt history capacity. "
        "Use a different chunking or a wider history representation.");
  }
  return TypeLongInt(1) << exponent;
}

TypeLongInt string_to_int128(const string &s) {
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
      char &hex_char = hexstr[hex_index];
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

vector<bool> hexstring_to_bitvector(const string &hexstr) {
  string s = hexstr;
  if (s.size() >= 2 && s[0] == '0' && (s[1] == 'x' || s[1] == 'X')) {
    s = s.substr(2); // Remove 0x
  }

  reverse(s.begin(), s.end()); // Reverse for LSB first
  vector<bool> bits;
  bits.reserve(s.size() * 4); // 4 bits per hex char

  for (char c : s) {
    uint8_t nibble;
    // printf("c: %c\n", c);
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

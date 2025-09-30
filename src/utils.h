#include <chrono>
#include <iostream>
#include <sstream>
#include <cstdarg>
#include <vector>
#include <cstdio>

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
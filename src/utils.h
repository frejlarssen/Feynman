#include <chrono>

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
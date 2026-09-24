#pragma once

#include <chrono>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <optional>
#include <sstream>
#include <stdexcept>
#include <string>
#include <sys/resource.h>

namespace memory_profile {

struct Pressure {
  uint64_t some_us;
  uint64_t full_us;
};

inline std::optional<Pressure> parse_pressure(std::istream &input) {
  std::optional<uint64_t> some, full;
  std::string line;
  while (std::getline(input, line)) {
    std::istringstream fields(line);
    std::string kind, token;
    fields >> kind;
    while (fields >> token) {
      if (token.rfind("total=", 0) != 0)
        continue;
      const std::string number = token.substr(6);
      if (number.empty() || number.find_first_not_of("0123456789") != std::string::npos)
        return std::nullopt;
      try {
        const uint64_t value = std::stoull(number);
        if (kind == "some") some = value;
        if (kind == "full") full = value;
      } catch (const std::exception &) {
        return std::nullopt;
      }
    }
  }
  if (!some || !full) return std::nullopt;
  return Pressure{*some, *full};
}

inline std::optional<Pressure> read_pressure(const std::filesystem::path &path) {
  std::ifstream input(path);
  return parse_pressure(input);
}

// mountinfo encodes spaces, tabs, newlines and backslashes as octal escapes.
inline std::string unescape_mount_path(const std::string &value) {
  std::string result;
  for (size_t i = 0; i < value.size(); ++i) {
    if (value[i] == '\\' && i + 3 < value.size() &&
        value.substr(i + 1, 3).find_first_not_of("01234567") == std::string::npos) {
      result += static_cast<char>(std::stoi(value.substr(i + 1, 3), nullptr, 8));
      i += 3;
    } else {
      result += value[i];
    }
  }
  return result;
}

// Resolve the calling process's cgroup, including container cgroup namespaces
// and mounts rooted at a subtree. Never fall back to host-wide PSI.
inline std::filesystem::path pressure_path(std::istream &cgroups,
                                           std::istream &mounts) {
  std::string line, group;
  while (std::getline(cgroups, line)) {
    if (line.rfind("0::", 0) == 0) group = line.substr(3);
  }
  if (group.empty() || group.front() != '/') return {};
  while (std::getline(mounts, line)) {
    const auto separator = line.find(" - cgroup2 ");
    if (separator == std::string::npos) continue;
    std::istringstream fields(line.substr(0, separator));
    std::string id, parent, device, root, mount;
    if (!(fields >> id >> parent >> device >> root >> mount)) continue;
    root = unescape_mount_path(root);
    mount = unescape_mount_path(mount);
    std::string relative;
    if (group == root) {
      relative = "";
    } else if (root == "/") {
      relative = group.substr(1);
    } else if (group.rfind(root + "/", 0) == 0) {
      relative = group.substr(root.size() + 1);
    } else {
      continue;
    }
    // A cgroup outside the visible namespace cannot be resolved safely.
    for (const auto &part : std::filesystem::path(relative)) {
      if (part == "..") return {};
    }
    return std::filesystem::path(mount) / relative / "memory.pressure";
  }
  return {};
}

inline std::string json_string(const std::string &value) {
  std::ostringstream output;
  output << '"';
  for (unsigned char c : value) {
    if (c == '"' || c == '\\') output << '\\' << c;
    else if (c < 32) output << "\\u" << std::hex << std::setw(4) << std::setfill('0') << int(c);
    else output << c;
  }
  output << '"';
  return output.str();
}

class Profile {
  std::filesystem::path psi_path;
  std::optional<Pressure> initial_pressure;
  std::chrono::steady_clock::time_point start;

public:
  Profile(const std::filesystem::path &cgroup_file = "/proc/self/cgroup",
          const std::filesystem::path &mount_file = "/proc/self/mountinfo") {
    std::ifstream cgroups(cgroup_file), mounts(mount_file);
    psi_path = pressure_path(cgroups, mounts);
    initial_pressure = read_pressure(psi_path);
    start = std::chrono::steady_clock::now();
  }

  void write(const std::filesystem::path &output_path) const {
    const auto final_pressure = read_pressure(psi_path);
    const double seconds = std::chrono::duration<double>(
        std::chrono::steady_clock::now() - start).count();
    struct rusage usage {};
    const bool usage_ok = getrusage(RUSAGE_SELF, &usage) == 0;
    std::string psi_status = "available";
    if (!initial_pressure) psi_status = "cgroup_v2_psi_unavailable";
    else if (!final_pressure) psi_status = "psi_end_read_failed";
    else if (final_pressure->some_us < initial_pressure->some_us ||
             final_pressure->full_us < initial_pressure->full_us)
      psi_status = "psi_counter_reset";
    const bool psi_ok = psi_status == "available" && seconds > 0;

    std::ofstream output(output_path);
    if (!output) throw std::runtime_error("Cannot write memory profile: " + output_path.string());
    output << std::setprecision(12)
           << "{\n  \"schema_version\": 1,\n"
           << "  \"process_status\": \"" << (usage_ok ? "available" : "getrusage_failed") << "\",\n"
           << "  \"peak_rss_mib\": ";
#ifdef __APPLE__
    const double rss_divisor = 1024.0 * 1024.0;
#else
    const double rss_divisor = 1024.0;
#endif
    if (usage_ok) output << usage.ru_maxrss / rss_divisor;
    else output << "null";
    output << ",\n  \"major_faults\": ";
    if (usage_ok) output << usage.ru_majflt;
    else output << "null";
    output << ",\n  \"memory_psi_scope\": \"cgroup\",\n"
           << "  \"memory_psi_path\": " << json_string(psi_path.string()) << ",\n"
           << "  \"memory_psi_status\": " << json_string(psi_status) << ",\n"
           << "  \"profile_seconds\": " << seconds;
    for (const bool full : {false, true}) {
      const std::string kind = full ? "full" : "some";
      output << ",\n  \"memory_psi_" << kind << "_start_us\": ";
      if (initial_pressure) output << (full ? initial_pressure->full_us : initial_pressure->some_us);
      else output << "null";
      output << ",\n  \"memory_psi_" << kind << "_end_us\": ";
      if (final_pressure) output << (full ? final_pressure->full_us : final_pressure->some_us);
      else output << "null";
      double stall_seconds = 0;
      if (psi_ok) stall_seconds = (full
          ? final_pressure->full_us - initial_pressure->full_us
          : final_pressure->some_us - initial_pressure->some_us) / 1e6;
      output << ",\n  \"memory_psi_" << kind << "_seconds\": ";
      if (psi_ok) output << stall_seconds;
      else output << "null";
      output << ",\n  \"memory_psi_" << kind << "_percent\": ";
      if (psi_ok) output << 100.0 * stall_seconds / seconds;
      else output << "null";
    }
    output << "\n}\n";
    output.close();
    if (!output) throw std::runtime_error("Failed writing memory profile: " + output_path.string());
    if (usage_ok)
      std::cout << "Peak RSS: " << usage.ru_maxrss / rss_divisor << " MiB\n"
                << "Major page faults: " << usage.ru_majflt << '\n';
    std::cout << "Memory PSI status: " << psi_status << '\n'
              << "Memory profile: " << output_path << '\n';
  }
};

} // namespace memory_profile

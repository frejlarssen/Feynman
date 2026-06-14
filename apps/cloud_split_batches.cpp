// Split a hexstring-set file into smaller batch files for Kubernetes workers.

#include "../src/iofiles.h"
#include <filesystem>
#include <iostream>
#include <string>
#include <vector>

namespace fs = std::filesystem;

struct Options {
  std::string hexstrings_file;
  std::string output_dir;
  std::string xcom_output_file;
  std::size_t batch_size = 0;
  std::string output_prefix = "batch_";
  std::string output_suffix = ".hs";
  int verbosity = 1;
};

Options get_options(int argc, char *argv[]) {
  Options opts;

  const char *helpstr =
      "Usage: ./cloud_split_batches.x -h hexstrings_file -o output_dir "
      "-n batch_size [-x xcom_output_file] [-p output_prefix] "
      "[-s output_suffix] [-v verbosity]\n";

  if (argc < 2) {
    std::cout << helpstr;
    std::exit(1);
  }

  int k;
  while ((k = getopt(argc, argv, "h:o:n:x:p:s:v:")) != -1) {
    switch (k) {
    case 'h':
      opts.hexstrings_file = optarg;
      break;
    case 'o':
      opts.output_dir = optarg;
      break;
    case 'n':
      opts.batch_size = static_cast<std::size_t>(std::stoull(optarg));
      break;
    case 'x':
      opts.xcom_output_file = optarg;
      break;
    case 'p':
      opts.output_prefix = optarg;
      break;
    case 's':
      opts.output_suffix = optarg;
      break;
    case 'v':
      opts.verbosity = std::stoi(optarg);
      break;
    default:
      std::cout << helpstr;
      std::exit(1);
    }
  }

  if (opts.hexstrings_file.empty() || opts.output_dir.empty() || opts.batch_size == 0) {
    std::cout << helpstr;
    std::exit(1);
  }

  return opts;
}

struct ParsedHexstringFile {
  std::size_t count = 0;
  std::string width_line;
  std::vector<std::string> bitstrings;
};

ParsedHexstringFile parse_hexstring_file(const std::string &path) {
  const std::vector<char> buffer = read_file_to_buffer(path);
  std::istringstream in(std::string(buffer.data(), buffer.size() - 1));
  if (!in) {
    throw std::runtime_error("Cannot convert hexstring buffer to stream");
  }

  ParsedHexstringFile parsed;
  std::string line;

  if (!std::getline(in, line)) {
    throw std::runtime_error("Missing bitstring-count header in: " + path);
  }
  parsed.count = std::stoull(line);

  if (!std::getline(in, parsed.width_line)) {
    throw std::runtime_error("Missing bitstring-width header in: " + path);
  }

  parsed.bitstrings.reserve(parsed.count);
  while (std::getline(in, line)) {
    if (line.empty()) {
      continue;
    }
    parsed.bitstrings.push_back(line);
  }

  if (parsed.bitstrings.size() != parsed.count) {
    throw std::runtime_error(
        "Hexstring-count header does not match payload line count in: " + path);
  }

  return parsed;
}

void write_xcom_num_batches(const Options &opts, std::size_t num_batches) {
  if (opts.xcom_output_file.empty()) {
    return;
  }

  const fs::path xcom_path(opts.xcom_output_file);
  if (xcom_path.has_parent_path()) {
    fs::create_directories(xcom_path.parent_path());
  }

  write_string_to_file(opts.xcom_output_file, std::to_string(num_batches) + "\n");
}

std::size_t split_batches(const Options &opts) {
  const ParsedHexstringFile parsed = parse_hexstring_file(opts.hexstrings_file);
  fs::create_directories(opts.output_dir);

  const std::size_t num_batches =
      (parsed.bitstrings.size() + opts.batch_size - 1) / opts.batch_size;

  if (opts.verbosity >= 1) {
    std::cout << "Splitting " << parsed.bitstrings.size() << " bitstrings into "
              << num_batches << " batch files\n";
  }

  for (std::size_t batch_id = 0; batch_id < num_batches; ++batch_id) {
    const std::size_t start = batch_id * opts.batch_size;
    const std::size_t end =
        std::min(start + opts.batch_size, parsed.bitstrings.size());

    std::string output;
    output += std::to_string(end - start) + "\n";
    output += parsed.width_line + "\n";
    for (std::size_t i = start; i < end; ++i) {
      output += parsed.bitstrings[i] + "\n";
    }

    const fs::path batch_path =
        fs::path(opts.output_dir) /
        (opts.output_prefix + std::to_string(batch_id) + opts.output_suffix);
    write_string_to_file(batch_path.string(), output);

    if (opts.verbosity >= 2) {
      std::cout << "Wrote " << batch_path << " with " << (end - start)
                << " bitstrings\n";
    }
  }

  write_xcom_num_batches(opts, num_batches);
  return num_batches;
}

int main(int argc, char *argv[]) {
  const Options opts = get_options(argc, argv);

  try {
    const std::size_t num_batches = split_batches(opts);
    if (opts.verbosity >= 1 && !opts.xcom_output_file.empty()) {
      std::cout << "Reported " << num_batches << " batches via XCom file "
                << opts.xcom_output_file << '\n';
    }
  } catch (const std::exception &e) {
    std::cerr << "Exception in split_batches(): " << e.what() << '\n';
    return 1;
  }

  return 0;
}

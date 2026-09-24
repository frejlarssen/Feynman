// Concatenate batch result files in index order into one output file.

#include "../src/iofiles.h"
#include <algorithm>
#include <filesystem>
#include <iostream>
#include <regex>
#include <string>
#include <vector>

namespace fs = std::filesystem;

struct Options {
  std::string input_dir;
  std::string output_file;
  std::string input_prefix = "qft_n8_k2_batch_";
  std::string input_suffix = ".hsv";
  std::size_t expected_num_batches = 0;
  int verbosity = 1;
};

Options get_options(int argc, char *argv[]) {
  Options opts;

  const char *helpstr =
      "Usage: ./cloud_concat_batches.x -i input_dir -o output_file "
      "[-p input_prefix] [-s input_suffix] [-n expected_num_batches] "
      "[-v verbosity]\n";

  if (argc < 2) {
    std::cout << helpstr;
    std::exit(1);
  }

  int k;
  while ((k = getopt(argc, argv, "i:o:p:s:n:v:")) != -1) {
    switch (k) {
    case 'i':
      opts.input_dir = optarg;
      break;
    case 'o':
      opts.output_file = optarg;
      break;
    case 'p':
      opts.input_prefix = optarg;
      break;
    case 's':
      opts.input_suffix = optarg;
      break;
    case 'n':
      opts.expected_num_batches = static_cast<std::size_t>(std::stoull(optarg));
      break;
    case 'v':
      opts.verbosity = std::stoi(optarg);
      break;
    default:
      std::cout << helpstr;
      std::exit(1);
    }
  }

  if (opts.input_dir.empty() || opts.output_file.empty()) {
    std::cout << helpstr;
    std::exit(1);
  }

  return opts;
}

struct BatchFile {
  std::size_t index = 0;
  fs::path path;
};

std::vector<BatchFile> find_batch_files(const Options &opts) {
  if (!fs::exists(opts.input_dir)) {
    throw std::runtime_error("Input directory does not exist: " + opts.input_dir);
  }

  if (opts.expected_num_batches > 0) {
    std::vector<BatchFile> batch_files;
    batch_files.reserve(opts.expected_num_batches);
    for (std::size_t index = 0; index < opts.expected_num_batches; ++index) {
      const fs::path batch_path =
          fs::path(opts.input_dir) /
          (opts.input_prefix + std::to_string(index) + opts.input_suffix);
      if (!fs::exists(batch_path)) {
        throw std::runtime_error("Missing expected batch result file: " +
                                 batch_path.string());
      }
      batch_files.push_back({index, batch_path});
    }
    return batch_files;
  }

  const std::regex pattern(
      "^" + opts.input_prefix + "([0-9]+)" + opts.input_suffix + "$");

  std::vector<BatchFile> batch_files;
  for (const auto &entry : fs::directory_iterator(opts.input_dir)) {
    if (!entry.is_regular_file()) {
      continue;
    }

    const std::string filename = entry.path().filename().string();
    std::smatch match;
    if (!std::regex_match(filename, match, pattern)) {
      continue;
    }

    batch_files.push_back(
        {static_cast<std::size_t>(std::stoull(match[1].str())), entry.path()});
  }

  std::sort(batch_files.begin(), batch_files.end(),
            [](const BatchFile &lhs, const BatchFile &rhs) {
              return lhs.index < rhs.index;
            });

  return batch_files;
}

void concatenate_batches(const Options &opts) {
  const std::vector<BatchFile> batch_files = find_batch_files(opts);
  if (batch_files.empty()) {
    throw std::runtime_error("No batch result files matched in: " + opts.input_dir);
  }

  std::string output;
  for (const auto &batch_file : batch_files) {
    const std::vector<char> buffer = read_file_to_buffer(batch_file.path.string());
    if (buffer.size() > 1) {
      output.append(buffer.data(), buffer.size() - 1);
    }

    if (opts.verbosity >= 2) {
      std::cout << "Read " << batch_file.path << '\n';
    }
  }

  const fs::path output_path(opts.output_file);
  if (output_path.has_parent_path()) {
    fs::create_directories(output_path.parent_path());
  }
  write_string_to_file(opts.output_file, output);

  if (opts.verbosity >= 1) {
    std::cout << "Concatenated " << batch_files.size()
              << " batch files into " << opts.output_file << '\n';
  }
}

int main(int argc, char *argv[]) {
  const Options opts = get_options(argc, argv);

  try {
    concatenate_batches(opts);
  } catch (const std::exception &e) {
    std::cerr << "Exception in concatenate_batches(): " << e.what() << '\n';
    return 1;
  }

  return 0;
}

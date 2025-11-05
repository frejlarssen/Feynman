// Executable for a Feynman simulation but with statevectors as input and output

#include "../src/typedef.h"
#include "../src/simulator.h"
#include "../src/mpiScheduler.h"
#include <iostream>

#define CLOSE_TO_ZERO 1e-8

using namespace std;

struct Options {
    string circuit_file;
    string input_statevector_file;
    string output_statevector_file;
    int num_chunk1 = -1;
    int num_chunk2 = -1;
    float fraction = 1.0;
    float threshold = CLOSE_TO_ZERO;
    int verbosity = 1;
    bool dense = false;
};

Options get_options(int argc, char* argv[]) {
    Options opts;

    const char* helpstr = "Usage: ./sv(_mpi/omp).x -c circuit_file -i input_sv -o output_sv -p num_chunk1 -r num_chunk2 -f fraction_of_histories -v verbosity (-D [Dense])\n";

    if (argc < 4) {
        cout << helpstr;
        exit(1);
    }

    int k;

    auto to_int = [](const std::string& word) -> unsigned {
        return std::atoi(word.c_str());
    };

    auto to_float = [](const std::string& word) -> float {
        return std::atof(word.c_str());
    };

    for (int i = 0; i < argc; i++) {
        cout << argv[i] << " ";
    }
    cout << endl;

    while ((k = getopt(argc, argv, "c:i:o:p:r:f:t:v:D")) != -1) {
        switch (k) {
          case 'c':
            opts.circuit_file = optarg;
            break;
          case 'i':
            opts.input_statevector_file = optarg;
            break;
          case 'o':
            opts.output_statevector_file = optarg;
            break;
          case 'p':
            opts.num_chunk2 = to_int(optarg);
            break;
          case 'r':
            opts.num_chunk1 = to_int(optarg);
            break;
          case 'f':
            opts.fraction = to_float(optarg);
            break;
          case 't':
            opts.threshold = to_float(optarg);
            break;
          case 'v':
            opts.verbosity = to_int(optarg);
            break;
          case 'D':
            opts.dense = true;
            break;
          default:
            cout << helpstr;
            exit(1);
        }
    }
    return opts;
}

int main(int argc, char* argv[]) {


    MPI_Init(&argc, &argv);
    int world_rank = -1;
    int world_size = 0;
    MPI_Comm_rank(MPI_COMM_WORLD, &world_rank);  // my rank
    MPI_Comm_size(MPI_COMM_WORLD, &world_size);  // total ranks

    auto start_svcc_all = get_time();

    Options opts = get_options(argc, argv);

    // Debugging that should be printed only by one rank.
    bool print_rank0_timings = (opts.verbosity >= 1);

    if (world_rank != 0) {
        print_rank0_timings = false;
    }

    ParsedCircuit::parse_circuit(opts.circuit_file);

    if (opts.num_chunk1 == -1 && opts.num_chunk2 == -1) {
        // Autotune if checkpoints not given. (This takes longer time initially.)
        Circuit::build_autotuned_circuit();
    }
    else if (opts.num_chunk1 > -1 && opts.num_chunk2 > -1) {
        Circuit::build_circuit(opts.num_chunk1, opts.num_chunk2);
    }
    else {
        cerr << "Both -p and -r must be set, or none of them for autotuning." << endl;
        exit(1);
    }

    if (print_rank0_timings && opts.verbosity >= 3)
        printf("After build: %s\n", Circuit::circuit_to_string(-1, 2).c_str());

    if (print_rank0_timings >= 1) {
        const int num_artificial = Circuit::chunks.at(0).num_artificial +
                                        Circuit::chunks.at(1).num_artificial +
                                        Circuit::chunks.at(2).num_artificial;
        printf("Total number of artificial sources: %d. Distributed as:\n", num_artificial);
        printf("  Chunk 0: %d\n", Circuit::chunks.at(0).num_artificial);
        printf("  Chunk 1: %d\n", Circuit::chunks.at(1).num_artificial);
        printf("  Chunk 2: %d\n", Circuit::chunks.at(2).num_artificial);
        
        const TypeLongInt num_histories_total = (TypeLongInt(1) << Circuit::chunks.at(0).num_artificial) *
                                               (TypeLongInt(1) << Circuit::chunks.at(1).num_artificial) *
                                               (TypeLongInt(1) << Circuit::chunks.at(2).num_artificial);
        
        
        
        printf("For each simulate call we simulate over: \n");
        printf("  %lu histories in total.\n", num_histories_total);
        printf("  %lu histories in parallel.\n", (1 << Circuit::chunks.at(2).num_artificial));
    }

    // Loop through all input-output pairs. Start with amplitude depending on input statevector.

    //ofstream out_file(opts.output_statevector_file);

    TypeLongInt total_output_bitstrings = 1ULL << Circuit::n;              // overflow if n >= 128
    TypeLongInt num_batches = ( total_output_bitstrings + world_size - 1) / world_size;
    std::size_t num_workers = world_size;
    std::size_t my_worker = world_rank;
    std::string local_buf;
    local_buf.reserve(1<<20);
    const std::size_t BATCH_SIZE = 64;
    MPI_Barrier(MPI_COMM_WORLD);

    duration<double> total_clocktime_simulate = zero_duration();
    int num_calls_simulate = 0;

    if (print_rank0_timings && opts.verbosity >= 2)
        printf("Starting simulation over all input-output pairs:\n");


    // Loop though all output bitstrings
    std::size_t count_processed_bitstrings = 0;
    auto start_svcc_sim = get_time();
    if (world_rank == 0) {
        // Pure master
        run_master_async(total_output_bitstrings, BATCH_SIZE, MPI_COMM_WORLD);
    }else{
        Prefetcher pf;
        std::size_t start = 0, count = 0;
        if (!pf.first(start, count, MPI_COMM_WORLD)) {
            // nothing to do
        }else{
            for(;;) {
                pf.prefetch_next(MPI_COMM_WORLD);     // overlap comm with compute
                std::size_t end = start + count;
                for(std::size_t output_int = start; output_int < end; ++output_int){
                    ++count_processed_bitstrings;
                    vector<bool> output_bits = bit_array_from_int(output_int, Circuit::n);
                    complex<float> output_amp(0,0);

                    ifstream in_file(opts.input_statevector_file);

                    string in_line;
                    TypeLongInt input_int = 0;
                    // Loop through the input bitstrings specified in input file
                    while (getline(in_file, in_line)) {
                        vector<bool> input_bits;

                        // Parse input bitstring and amplitude
                        complex<float> amp_in;
                        if (opts.dense) {
                            input_bits = bit_array_from_int(input_int++, Circuit::n);
                            amp_in = string_to_complex(in_line);
                        }
                        else { // Sparse is default
                            size_t colon_pos = in_line.find(':');
                            string basis_state_str = in_line.substr(0, colon_pos);
                            input_bits = bit_array_from_int(std::atoi(basis_state_str.c_str()), Circuit::n);
                            amp_in = string_to_complex(in_line.substr(colon_pos + 1));
                        }

                        auto start_simulate = get_time();
                        output_amp += simulate(output_bits, input_bits, amp_in, opts.fraction, opts.threshold, 3);
                        auto end_simulate = get_time();
                        num_calls_simulate++;

                        duration<double> clocktime_simulate = end_simulate - start_simulate;

                        if (opts.verbosity >= 2) {
                            printf("Worker %d - Clocktime to simulate input |", my_worker);
                            for (int i = Circuit::n - 1; i >= 0; i--) {
                                printf("%d", input_bits[i] ? 1 : 0);
                            }
                            printf("> to output |");
                            for (int i = Circuit::n - 1; i >= 0; i--) {
                                printf("%d", output_bits[i] ? 1 : 0);
                            }
                            printf("> : %f seconds\n", clocktime_simulate.count());
                        }

                        total_clocktime_simulate += clocktime_simulate;

                        // Reset all values (for all threads if OpenMP is used)
                        Circuit::reset_values_all();
                    }

                    // Write to output file
                    bool writeFlag = 0;
                    if (opts.dense || (std::abs(output_amp) >  opts.threshold) ) writeFlag = 1;
                    if (writeFlag){
                        local_buf += std::to_string(output_int);
                        local_buf += ":";
                        local_buf += std::to_string(output_amp.real());
                        local_buf += "+";
                        local_buf += std::to_string(output_amp.imag());
                        local_buf += "i\n";
                    }
                }
                if (!pf.finish(start, count)) break;  // next becomes current
            }
        }
    }


    auto end_svcc_simulation = get_time();

    // parallel output to disk
    MPI_File fh;
    if (world_rank == 0)MPI_File_delete(opts.output_statevector_file.c_str(), MPI_INFO_NULL);
    MPI_Barrier(MPI_COMM_WORLD);
    int rc = MPI_File_open(MPI_COMM_WORLD,
                        opts.output_statevector_file.c_str(),
                        MPI_MODE_CREATE | MPI_MODE_WRONLY,
                        MPI_INFO_NULL,
                        &fh);
    MPI_Offset my_bytes  = static_cast<MPI_Offset>(local_buf.size());
    MPI_Offset my_offset = 0;
    MPI_Exscan(&my_bytes, &my_offset, 1, MPI_OFFSET, MPI_SUM, MPI_COMM_WORLD);
    if (world_rank == 0) my_offset = 0;
    MPI_Status st;
    MPI_File_write_at_all(fh, my_offset, (void*)local_buf.data(), (int)my_bytes, MPI_BYTE, &st);
    MPI_File_close(&fh);


    int tot_num_calls_simulate = 0;
    MPI_Reduce(&num_calls_simulate, &tot_num_calls_simulate, 1, MPI_INT, MPI_SUM, 0, MPI_COMM_WORLD);
    if (print_rank0_timings) {
        printf("Number of simulate calls: %d\n", tot_num_calls_simulate);
        printf("Total clocktime for all simulate calls: %f seconds\n", total_clocktime_simulate.count());
        printf("Average clocktime per simulate call: %f seconds\n", total_clocktime_simulate.count() / tot_num_calls_simulate);
    }
    if(opts.verbosity >= 1){
        fflush(stdin);
        MPI_Barrier(MPI_COMM_WORLD);
        printf("Worker %d - processed %d / %d bitstrings\n", my_worker, count_processed_bitstrings, total_output_bitstrings);
    }

    //out_file.close();
    fflush(stdin);
    MPI_Barrier(MPI_COMM_WORLD);

    auto end_svcc_full = get_time();

    duration<double> total_clocktime_svcc_sim = end_svcc_simulation - start_svcc_sim;
    duration<double> total_clocktime_svcc_full = end_svcc_full - start_svcc_all;
    duration<double> total_clocktime_svcc_writing = end_svcc_full - end_svcc_simulation;

    if (print_rank0_timings){
        printf("Total clocktime sim for sv.cc: %f seconds\n", total_clocktime_svcc_sim.count());
        printf("Total clocktime writing to disk for sv.cc: %f seconds\n", total_clocktime_svcc_writing.count());
        printf("Total clocktime (including I/O) for sv.cc: %f seconds\n", total_clocktime_svcc_full.count());
    }

    MPI_Finalize();

    return 0;
}

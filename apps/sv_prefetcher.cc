// Executable for a Feynman simulation but with statevectors as input and output

#include "../src/typedef.h"
#include "../src/simulator.h"
#include "../src/mpiScheduler.h"
#include "../src/iofiles.h"
#include "../src/utils.h"
#include <iostream>
#ifdef USE_OPENMP
    #include <omp.h>
#endif

#define EXECUTE_RUN 1
#define PERF_INSTRUMENT 0
#define CLOSE_TO_ZERO 1e-8

using namespace std;

struct Options {
    string circuit_file;
    string input_statevector_file;
    string output_bitstring_subset;
    string output_statevector_file;
    int num_chunk1 = -1;
    int num_chunk2 = -1;
    std::size_t batch_size = 32;
    float fraction = 1.0;
    float threshold = CLOSE_TO_ZERO;
    int verbosity = 1;
    bool dense = false;
};

Options get_options(int argc, char* argv[]) {
    Options opts;

    const char* helpstr = "Usage: ./sv(_mpi/omp).x -c circuit_file -i input_sv -b output_bitstring_subset -o output_sv -p num_chunk1 -r num_chunk2 -f fraction_of_histories -v verbosity (-D [Dense]) -s batch_size\n";

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

    while ((k = getopt(argc, argv, "c:i:b:o:p:r:s:f:t:v:D")) != -1) {
        switch (k) {
          case 'c':
            opts.circuit_file = optarg;
            break;
          case 'i':
            opts.input_statevector_file = optarg;
            break;
          case 'b':
            opts.output_bitstring_subset = optarg;
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
          case 's':
            opts.batch_size = to_int(optarg);
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

#ifdef USE_OPENMP
    const int t_omp = omp_get_max_threads();
#else
    const int t_omp = 0;
#endif


    //prctl(PR_TASK_PERF_EVENTS_DISABLE, 0, 0, 0, 0);
#if PERF_INSTRUMENT
    int fd = open_leader(getpid(), -1, PERF_TYPE_HARDWARE, PERF_COUNT_HW_CPU_CYCLES);
#endif
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
        const int num_gates = ParsedCircuit::nr_gates;
        printf("Circuit has %d gates. Distributed as:\n", num_gates, Circuit::n);
        printf("  Chunk 0: %d gates\n", Circuit::chunks.at(0).gates.size());
        printf("  Chunk 1: %d gates\n", Circuit::chunks.at(1).gates.size());
        printf("  Chunk 2: %d gates\n", Circuit::chunks.at(2).gates.size());
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

    // Load input bitstrings
    vector<InputBitstrings> input_bitstrings = load_input_bitvectors_from_master(opts.input_statevector_file, opts.dense, world_rank, MPI_COMM_WORLD);

    // Load output bitstrings to simulate (if the option is ON)
//#ifdef USE_SUBSET_OUTBITSTRINGS
    vector<vector<bool>> output_bitstrings = load_output_bitvectors_from_master(opts.output_bitstring_subset, world_rank, MPI_COMM_WORLD);
    const TypeLongInt total_output_bitstrings = output_bitstrings.size();
//#else
//    const TypeLongInt total_output_bitstrings = 1ULL << Circuit::n;              // overflow if n >= 128
//#endif
    if(print_rank0_timings)
    std::cout << "Total output bitstrings to simulate: " << static_cast<std::size_t>(total_output_bitstrings) <<std::endl;

    // Loop through all input-output pairs. Start with amplitude depending on input statevector.
    const std::size_t num_workers = (opts.batch_size > 0) ? std::max(1,world_size - 1) : world_size;
    const std::size_t my_worker = world_rank;
    std::string local_buf;
    local_buf.reserve(1<<20);
    std::string local_buf_timing;
    local_buf_timing.reserve(1<<16);

    const std::size_t batch_size = (opts.batch_size > 0) ? opts.batch_size : ( (total_output_bitstrings + num_workers - 1)/ num_workers) ;

    if (print_rank0_timings && opts.verbosity >= 1){
        printf("Starting simulation over all input-output pairs:\n -- Total output bitstrings = %d -- active workers = %d - OMP_THREADS per worker = %d - batch_size = %d --:\n", total_output_bitstrings, num_workers, t_omp, batch_size);
    }
    MPI_Barrier(MPI_COMM_WORLD);

    duration<double> total_clocktime_simulate = zero_duration();
    int num_calls_simulate = 0;

    // Loop though all output bitstrings
    std::size_t count_processed_bitstrings = 0;
    auto start_svcc_sim = get_time();

    // Worker body
    auto process_outputs = [&](std::size_t start, std::size_t end){
        for (std::size_t output_int = start; output_int < end; ++output_int) {
            if(output_int >= total_output_bitstrings)break;
//    #ifdef USE_SUBSET_OUTBITSTRINGS
            const vector<bool> output_bits = output_bitstrings[output_int];
//    #else
//            const TypeLongInt bitstringDecimal = output_int;
//            std::vector<bool> output_bits = bit_array_from_int(bitstringDecimal, Circuit::n);
//    #endif
            auto start_simulate_bitstring = get_time();
            ++count_processed_bitstrings;

            std::complex<float> output_amp(0, 0);

            // Loop through the input bitstrings specified in input file
            for (const auto& input : input_bitstrings) {
                std::vector<bool> input_bits = input.index;
                
                std::complex<float> amp_in = input.amp;

                auto start_simulate = get_time();
                output_amp += simulate(output_bits, input_bits, amp_in, opts.fraction, opts.threshold, 3);
                auto end_simulate = get_time();
                num_calls_simulate++;

                const duration<double> clocktime_simulate = end_simulate - start_simulate;

                if (opts.verbosity >= 2) {
                    printf("Worker %d - Clocktime to simulate input |", my_worker);
                    for (int i = Circuit::n - 1; i >= 0; --i) printf("%d", input_bits[i] ? 1 : 0);
                    printf("> to output |");
                    for (int i = Circuit::n - 1; i >= 0; --i) printf("%d", output_bits[i] ? 1 : 0);
                    printf("> : %f seconds\n", clocktime_simulate.count());
                }

                total_clocktime_simulate += clocktime_simulate;
                // Reset all values (for all threads if OpenMP is used)
                Circuit::reset_values_all();
            }

            auto end_simulate_bitstring = get_time();
            const duration<double> clocktime_bitstring = end_simulate_bitstring - start_simulate_bitstring;
            local_buf_timing += bitvector_to_hexstring(output_bits) + ":" +
                                std::to_string(clocktime_bitstring.count()) + "\n";

            // Write to output file
            bool writeFlag = (opts.dense || (std::abs(output_amp) > opts.threshold));
            if (writeFlag) {
                local_buf += bitvector_to_hexstring(output_bits) + ":" +
                            std::to_string(output_amp.real()) + "+" +
                            std::to_string(output_amp.imag()) + "i\n";
            }
        }
    };
    //prctl(PR_TASK_PERF_EVENTS_ENABLE, 0, 0, 0, 0);
#if PERF_INSTRUMENT
    ioctl(fd, PERF_EVENT_IOC_RESET, PERF_IOC_FLAG_GROUP);   // zero all
    ioctl(fd, PERF_EVENT_IOC_ENABLE, PERF_IOC_FLAG_GROUP);  // begin region
#endif

#if EXECUTE_RUN
    // Run the simulation
    if (opts.batch_size > 0){ // run with asyncronous server - worker implementation
        if (world_size == 1){
            if (world_rank == 0){
                process_outputs(0, total_output_bitstrings);
            }
        }else{
            // Multi-rank: server/worker structure
            if (world_rank == 0){
                run_master_async(total_output_bitstrings, batch_size, MPI_COMM_WORLD);
            }else{
                Prefetcher pf;
                run_worker_with(pf, MPI_COMM_WORLD, process_outputs);
            }
        }
    }else{ // run with fixed batch size, no server - worker
        process_outputs(my_worker * batch_size, batch_size * (my_worker + 1) );
    }
#endif
#if PERF_INSTRUMENT
    ioctl(fd, PERF_EVENT_IOC_DISABLE, PERF_IOC_FLAG_GROUP);
    //prctl(PR_TASK_PERF_EVENTS_DISABLE, 0, 0, 0, 0);
#endif

    MPI_Barrier(MPI_COMM_WORLD);
    auto end_svcc_simulation = get_time();

    // parallel output to disk
    int err = write_output_to_disk(opts.output_statevector_file, local_buf, world_rank, MPI_COMM_WORLD);
    auto timing_file_path = replace_filename(opts.output_statevector_file, "timeBitstrings.tm");
    int err1 = write_output_to_disk(timing_file_path, local_buf_timing, world_rank, MPI_COMM_WORLD);


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
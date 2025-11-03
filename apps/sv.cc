// Executable for a Feynman simulation but with statevectors as input and output

#include "../src/simulator.h"

#define SPARSE_LIMIT 1e-6

using namespace std;

struct Options {
    string circuit_file;
    string input_statevector_file;
    string output_statevector_file;
    int num_chunk1 = -1;
    int num_chunk2 = -1;
    float fraction = 1.0;
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

    //cout << "Parsing options" << endl;
    //cout << "argc: " << argc << endl;
    //cout << "argv: ";
    for (int i = 0; i < argc; i++) {
        cout << argv[i] << " ";
    }
    cout << endl;

    while ((k = getopt(argc, argv, "c:i:o:p:r:f:v:D")) != -1) {
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

#ifdef USE_MPI
    MPI_Init(&argc, &argv);
    int world_rank; // For debugging
    MPI_Comm_rank(MPI_COMM_WORLD, &world_rank);
#endif

    auto start_svcc = get_time();

    Options opts = get_options(argc, argv);

    // Debugging that should be printed only by one rank.
    bool print_rank0_timings = (opts.verbosity >= 1);
#ifdef USE_MPI
    if (world_rank != 0) {
        print_rank0_timings = false;
    }
#endif

    ParsedCircuit::parse_circuit(opts.circuit_file);

    //printf("Parsed circuit:\n");
    //printf("  %s\n", ParsedCircuit::parsed_circuit_to_string().c_str());


    //TODO: Autotuning: Build circuit many times with different cp-params, save the best params and build once more for those.

    if (opts.num_chunk1 == -1 && opts.num_chunk2 == -1) {
        Circuit::build_autotuned_circuit();
    }
    else if (opts.num_chunk1 > -1 && opts.num_chunk2 > -1) {
        Circuit::build_circuit(opts.num_chunk1, opts.num_chunk2);
    }
    else {
        cerr << "Both -p and -r must be set, or none of them for autotuning." << endl;
        exit(1);
    }

    //printf("After build:\n");
    //for (int i = 0; i < NUM_CHUNKS; i++) {
    //    printf("Chunk %d with %zu gates and %d artificial sources:\n", i, Circuit::chunks.at(i).gates.size(), Circuit::chunks.at(i).num_artificial);
    //    for (const shared_ptr<Gate>& gate: Circuit::chunks.at(i).gates) {
    //        printf("  %s\n", gate_to_string(*gate, -1, 2).c_str());
    //    }
    //}

    //printf("Output wires after build:\n");
    //for (shared_ptr<InternalWire>& iw : Circuit::output_sources) {
    //    printf("%s\n", internal_wire_to_string(iw, 2).c_str());
    //}

//    printf("Chunks internal wires after build (to reset): \n");
//    for (int i = 0; i < NUM_CHUNKS; i++) {
//        printf("Chunk %d with %ld internal wires:\n", i, Circuit::chunks.at(i).internal_wires.size());
//        for (const shared_ptr<InternalWire>& iw : Circuit::chunks.at(i).internal_wires) {
//            printf("  %s\n", internal_wire_to_string(iw, -1, 2).c_str());
//        }
//    }


    
    // Loop through all input-output pairs. Start with amplitude depending on input statevector.
    
    ofstream out_file(opts.output_statevector_file);

    duration<double> total_clocktime_simulate = zero_duration();
    int num_calls_simulate = 0;

    for (int output_int = 0; output_int < (1ULL << Circuit::n); output_int++) {
        vector<bool> output_bits = bit_array_from_int(output_int, Circuit::n);
        complex<float> output_amp(0,0);

        ifstream in_file(opts.input_statevector_file);

        string in_line;
        u_int64_t input_int = 0;
        std::ostringstream buf;
        while (getline(in_file, in_line)) {
            vector<bool> input_bits;
            complex<float> amp_in;
            if (opts.dense) {
                input_bits = bit_array_from_int(input_int++, Circuit::n);
                amp_in = string_to_complex(in_line);
            }
            else {
                size_t colon_pos = in_line.find(':');
                string basis_state_str = in_line.substr(0, colon_pos);
                input_bits = bit_array_from_int(std::atoi(basis_state_str.c_str()), Circuit::n);
                amp_in = string_to_complex(in_line.substr(colon_pos + 1));
            }

            auto start_simulate = get_time();
            complex<float> amp = simulate(output_bits, input_bits, opts.fraction, buf, 3);
            auto end_simulate = get_time();
            num_calls_simulate++;

            duration<double> clocktime_simulate = end_simulate - start_simulate;

            if (print_rank0_timings && opts.verbosity >= 2) {
                printf("  Clocktime to simulate input |");
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

            //printf("  Amplitude: %f + i%f\n", amp.real(), amp.imag());
            output_amp += amp_in * amp;

            // Reset all values for all threads
            Circuit::reset_values_all();
        }


        //cout << "Total amplitude to output state |";
        //for (int i = Circuit::n - 1; i >= 0; i--) {
        //    cout << (output_bits[i] ? "1" : "0");
        //}
        //cout << "> : " << output_amp.real() << " + i" << output_amp.imag() << "\n";

        if (opts.dense) {
            string out_line = to_string(output_amp.real()) + "+" + to_string(output_amp.imag()) + "i\n";
            out_file << out_line;
        }
        else {
            if (abs(output_amp) > SPARSE_LIMIT) {
                string out_line = to_string(output_int) + ":" + to_string(output_amp.real()) + "+" + to_string(output_amp.imag()) + "i\n";
                out_file << out_line;
            }
        }

        in_file.close();
    }

    if (print_rank0_timings) {
        printf("Number of simulate calls: %d\n", num_calls_simulate);
        printf("Total clocktime for all simulate calls: %f seconds\n", total_clocktime_simulate.count());

        printf("Average clocktime per simulate call: %f seconds\n", total_clocktime_simulate.count() / num_calls_simulate);
    }

    out_file.close();

    auto end_svcc = get_time();
    duration<double> total_clocktime_svcc = end_svcc - start_svcc;

    if (print_rank0_timings)
        printf("Total clocktime for sv.cc: %f seconds\n", total_clocktime_svcc.count());

#ifdef USE_MPI
    MPI_Finalize();
#endif

    return 0;
}

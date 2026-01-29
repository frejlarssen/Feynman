// Lightweight executable to calculate amplitude for certain input and output bitstring

#include "../src/simulator.h"

struct Options {
    string circuit_file;
    vector<bool> input_bits;
    vector<bool> output_bits;
    int num_chunk1 = -1;
    int num_chunk2 = -1;
    float fraction = 1.0;
    bool only_build = false;
};

Options get_options(int argc, char* argv[]) {
    Options opts;

    const char* helpstr = "Usage: ./bitstr(_mpi/omp).x -c circuit_file -i input_bitstring -o output_bitstring -p num_chunk1 -r num_chunk2 (-B)\n";

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

    while ((k = getopt(argc, argv, "c:i:o:p:r:f:B")) != -1) {
        switch (k) {
          case 'c':
            opts.circuit_file = optarg;
            break;
          case 'i': //Not necessary. We could leave to the user to initialize in circuit_file and always start at state |0>.
            opts.input_bits = bit_array_from_string(optarg);
            break;
          case 'o':
            opts.output_bits = bit_array_from_string(optarg);
            break;
          case 'p':
            opts.num_chunk2 = to_int(optarg);
            break;
          case 'r':
            opts.num_chunk1 = to_int(optarg);
            break;
          case 'f':
            cout << "f optarg: " << optarg << endl;
            opts.fraction = to_float(optarg);
            printf("opts.fraction: %f\n", opts.fraction);
            cout << "opts.fraction: " << opts.fraction << endl;
            break;
          case 'B':
            opts.only_build = true;
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
#endif

    Options opts = get_options(argc, argv);

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

    printf("After build:\n");
    for (int i = 0; i < NUM_CHUNKS; i++) {
        printf("Chunk %d with %zu gates and %d artificial sources:\n", i, Circuit::chunks.at(i).gates.size(), Circuit::chunks.at(i).num_artificial);
        for (const shared_ptr<Gate>& gate: Circuit::chunks.at(i).gates) {
            printf("  %s\n", gate_to_string(*gate, -1, 2).c_str());
        }
    }

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

    if (opts.only_build) {
        size_t total_gates = 0;
        int total_artificial_sources = 0;
        for (int i = 0; i < NUM_CHUNKS; i++) {
            total_gates += Circuit::chunks.at(i).gates.size();
            total_artificial_sources += Circuit::chunks.at(i).num_artificial;
            printf("Chunk %d: %ld gates, %d artificial sources.\n", i, Circuit::chunks.at(i).gates.size(), Circuit::chunks.at(i).num_artificial);
        }
        printf("Total gates: %ld\n", total_gates);
        printf("Artificial sources: %d\n", total_artificial_sources);
    }
    else {
        std::ostringstream buf;

        // TODO: For benchmarking: Run this many times with different input/output pairs.
        complex<float> amp = simulate(opts.output_bits, opts.input_bits, opts.fraction, buf, 3);
//        int a = simulate();
        printf("Total amplitude: %f + i%f\n", amp.real(), amp.imag());
    }

#ifdef USE_MPI
    MPI_Finalize();
#endif

    return 0;
}

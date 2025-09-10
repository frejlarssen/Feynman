#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include <sstream>
#include <algorithm>
#include <functional>

#define PI 3.141592653589793

using namespace std;

enum GateType {
    HADAMARD,
    CPHASE,
    SWAP,
    CNOT
};

GateType gate_type_from_string(const string& s) {
    if (s == "h" || s == "H") {
        return HADAMARD;
    } else if (s == "cp" || s == "CP" || s == "cz" || s == "CZ") {
        return CPHASE;
    } else if (s == "swap" || s == "SWAP") {
        return SWAP;
    } else if (s == "cx") {
        return CNOT;
    } else {
        cerr << "Unknown gate type: " << s << endl;
        exit(1);
    }
}

std::string gate_type_to_string(GateType type) {
    switch (type) {
        case HADAMARD: return "HADAMARD";
        case CPHASE: return "CPHASE";
        case SWAP: return "SWAP";
        case CNOT: return "CNOT";
        default: return "UNKNOWN";
    }
}

struct GateTypeInfo {
    GateType type;
    int num_qubits;
    int num_controls; // The first num_controls parameters are controls, the rest are targets
    bool breaks_internal_wire; // Does the target bits of it break the internal wire?

    // Constructor
    GateTypeInfo(GateType t, int n, int c, bool b) : type(t), num_qubits(n), num_controls(c), breaks_internal_wire(b) {}
};

//Must be defined in the same way as in the enum GateType (if we don't remove that one and use only this).
const array<GateTypeInfo,4> gate_type_infos = {
    GateTypeInfo(HADAMARD, 1, 0, true),
    GateTypeInfo(CPHASE, 1, 1, false),
    GateTypeInfo(SWAP, 2, 0, true),
    GateTypeInfo(CNOT, 2, 1, true)
};

//int global_index(int wire, int internal_index) {
//    // TODO: Generalize for non-QFT circuits
//    // Loop through all wires before this one and count their internal wires
//
//
//    return wire * (2*NUM_QUBITS - wire + 1 ) / 2 + internal_index;
//}


// Stored on each wire it takes as argument.
struct ParsedGate {
    const int id; // ID from line in circuit file.
    const GateType type;
    const vector<int> args; // Argument list. wires[0] is the argument to the first parameter etc.
    const int param; // The parameter of which argument-wire this struct is stored.
    // Constructor
    ParsedGate(int i, GateType t, vector<int> a, int p) : id(i), type(t), args(a), param(p) {}
};

string parsed_gate_to_string(const ParsedGate& pg) {
    string s = "ParsedGate(id=" + to_string(pg.id) + ", type=" + gate_type_to_string(pg.type) + ", wires=[";
    for (size_t i = 0; i < pg.args.size(); i++) {
        s += to_string(pg.args[i]);
        if (i < pg.args.size() - 1) s += ", ";
    }
    s += "])";
    return s;
}

string wire_to_string(const vector<ParsedGate>& wire) {
    string s = "[";
    for (size_t i = 0; i < wire.size(); i++) {
        s += parsed_gate_to_string(wire[i]);
        if (i < wire.size() - 1) s += ", ";
    }
    s += "]";
    return s;
}

struct GateQubit {
    int wire;
    int internal_index_out; // Global indexing of internal wire out if target, and both in and out if control.
    bool is_control; // Might not be necessary. Given from which index this GateQubit have in Gate.qubits and type.
    bool at_input;
    bool at_output;

    // Constructor
    GateQubit(int w, int idx, bool ctrl, bool in=false, bool out=false)
        : wire(w), internal_index_out(idx), is_control(ctrl), at_input(in), at_output(out) {}
    
    // Default constructor
    GateQubit()
        : wire(-1), internal_index_out(0), is_control(false), at_input(false), at_output(false) {} // wire -1 is means not set yet.
};

string gate_qubit_to_string(const GateQubit& gq) {
    return "(wire: " + to_string(gq.wire) +
           ", index_out: " + to_string(gq.internal_index_out) +
           ", control: " + (gq.is_control ? "true" : "false") +
           ", at_input: " + (gq.at_input ? "true" : "false") +
           ", at_output: " + (gq.at_output ? "true" : "false") + ")";
}

struct Gate {
    int id;
    GateType type;
    vector<GateQubit> qubits; //Argument list. Order matters!
    //const float parameter; // TODO: For gates that need parameters (e.g., general CPHASE)

    // Constructor
    Gate(int id, GateType t, vector<GateQubit> qs)
        : id (id), type(t), qubits(std::move(qs)) {}
};

string gate_to_string(const Gate& g) {
    string str = "Gate(id="+to_string(g.id) +
    ", type="+gate_type_to_string(g.type) +
    ", qubits=[";
    for (int qi = 0; qi < g.qubits.size(); qi++) {
        str += gate_qubit_to_string(g.qubits[qi]);
        if (qi < g.qubits.size() - 1) str += ", ";
    }
    str += "])";
    return str;
}

//TODO: Fix internal indexing to be consistent with history indexing
struct Circuit {
    static int n;
    static vector<Gate> gates; //TODO: Fix const
    static vector<vector<ParsedGate>> wires;
    static int num_internal_wires;

    // Generate the QFT gates
    static void parse_circuit(string filename) {

        cout << "Parsing circuit from file: " << filename << endl;
        ifstream file(filename);

        // String to store each line of the file.
        string line;

        if (file.is_open()) {

            if (getline(file, line) && line != "OPENQASM 2.0;" && line != "OPENQASM 3.0;") {
                cerr << "Only OPENQASM (v2.0 and v3.0) supported" << endl;
                exit(1);
            }

            if (getline(file, line) && line != "include \"qelib1.inc\";") { //TODO: Fix support for standard library.
                cerr << "Only qelib1.inc supported" << endl;
                exit(1);
            }

            if (getline(file, line) && line.substr(0, 4) != "qreg") { // TODO: Change to qubit. qreg is soon deprecated: https://openqasm.com/language/types.html
                cerr << "Only qreg supported" << endl;
                exit(1);
            }

            line = line.substr(5); // Remove "qreg "
            size_t bracket_pos = line.find('[');
            size_t end_bracket_pos = line.find(']');
            if (bracket_pos == string::npos || end_bracket_pos == string::npos || end_bracket_pos <= bracket_pos) {
                cerr << "Invalid qreg declaration" << endl;
                exit(1);
            }

            string qreg_name = line.substr(0, bracket_pos);
            n = stoi(line.substr(bracket_pos + 1, end_bracket_pos - bracket_pos - 1));
            wires.resize(n);

            printf("Qreg name: %s, size: %d\n", qreg_name.c_str(), n);
            
            int gate_index = 0;
            // Read each line from the file and store it in the
            // 'line' variable.
            while (getline(file, line)) {
                cout << "Index: " << gate_index << ": " << line << endl;
                size_t space = line.find(' ');
                string type_str = line.substr(0, space);
                string qubits_str = line.substr(space + 1);
                cout << "Qubit string: " << qubits_str << "\n";
                std::stringstream qubit_stream(qubits_str);
                std::string qubit_str;
                vector<int> arg_indices;
                int param = 0;
                while (getline(qubit_stream, qubit_str, ',')) {
                    printf("Qubit: %s\n", qubit_str.c_str());
                    printf("Qreg name given: %s\n", qubit_str.substr(0, qreg_name.size() + 1).c_str());
                    if (qubit_str.substr(0, qreg_name.size() + 1) != qreg_name + "[") {
                        cerr << "Invalid qubit name" << endl;
                        exit(1);
                    }
                    printf("Extracted index string: %s\n", qubit_str.substr(qubit_str.find('[') + 1, qubit_str.find(']') - qubit_str.find('[') - 1).c_str());
                    int qubit_index = stoi(qubit_str.substr(qubit_str.find('[') + 1, qubit_str.find(']') - qubit_str.find('[') - 1));
                    arg_indices.push_back(qubit_index);
                }

                for (int param = 0; param < arg_indices.size(); param++) {
                    int arg_index = arg_indices[param];
                    if (arg_index < 0 || arg_index >= n) {
                        cerr << "Qubit index out of range" << endl;
                        exit(1);
                    }
                    wires[arg_index].emplace_back(gate_index, gate_type_from_string(type_str), arg_indices, param);
                }
                gate_index++;
            }

            // Close the file stream once all lines have been
            // read.
            file.close();
        }
        else {
            // Print an error message to the standard error
            // stream if the file cannot be opened.
            cerr << "Unable to open file!" << endl;
        }

        for (size_t i = wires.size() - 1; i >= 0 && i < wires.size(); i--) {
            cout << "Wire " << i << ": " << wire_to_string(wires[i]) << "\n";
        }

//        bool target_at_output = false;
//        // Step 1: Hadamards and controlled phases
//        for (int group = 0; group < n; group++) {
//            g.emplace_back(HADAMARD, vector<GateQubit>{GateQubit(group, n - group, false, true, false)});
//            for (int i = 1; i < n - group; i++) {
//                // Edge case: target happens to be at output (no switch in the middle)
//                if (n%2 == 1 && group == n/2 && i == n - group - 1) {
//                    bool phase_target_at_output = true;
//                }
//                g.emplace_back(CPHASE, vector<GateQubit>{
//                    GateQubit(group + i, n - group - i, true, true, false),         // control
//                    GateQubit(group, n - group - i, false, false, target_at_output) // target
//                }, -PI / (1 << i) );
//            }
//        }

        return;
    }

    // -1 if not added yet. Otherwise idx such that gate[idx].id = id
    static int vector_idx_of_gate(int id) {
        for (int i = 0; i < gates.size(); i++) {
            if (gates[i].id == id) {
                return i;
            }
        }
        return -1;
    }

    // Build the global gate list from parsed gates on each wire.
    // Counts internal wires.
    // Adds only the qubit on that wire.
    // Sort based on idx.
    static void build_gate_list() {
        int internal_index = -1; // -1 is output of wire 0
        for (int wire = 0; wire < n; wire++) {
            for (int pgi = wires[wire].size() - 1; pgi >= 0; pgi--) {
                ParsedGate& pg = wires[wire][pgi];
                printf("Processing parsed gate: %s at wire %d\n", parsed_gate_to_string(pg).c_str(), wire);
                
                // Check if gate is already added. Two ways:
                // 1. check if it has a wire w lower than wire.
                // 2. Check if id exists in gates.

                // If it already exists, we need to fetch the gate using the id.
                // We can try to fetch using id, that will solve both.

                int idx = vector_idx_of_gate(pg.id);

                // We need to know which parameter (index in pg.wires) that has this wire as arugment,
                // that is pg.args[parameter_idx] = wire
                // This, we could have stored directly.

                // Build/modify gate
                bool is_control = (pg.param < gate_type_infos[pg.type].num_controls);
                bool at_input = (pgi == 0);
                GateQubit q = GateQubit(wire, internal_index, is_control, (pgi == 0), (pgi == int(wires[wire].size()) - 1));
                if (idx == -1) { // Add new
                    int numq = gate_type_infos[pg.type].num_qubits;
                    vector<GateQubit> args(numq);
                    args.at(pg.param) = q;
                    gates.emplace_back(pg.id, pg.type, args);
                } else { // Update existing
                    gates[idx].qubits.at(pg.param) = q;
                }

                // Maybe add internal wire
                if (is_control) {
                    // Control qubit. No new internal wire.
                } else if (!gate_type_infos[pg.type].breaks_internal_wire) {
                    // Target produces no new internal wire
                } else if (at_input) {
                    // No new internal wire either (since circuit input doesn't come from histories)
                } else {
                    printf("Internal wire found\n");
                    internal_index++;
                }
            }
        }

        num_internal_wires = internal_index + 1;

        auto itbegin = gates.begin();
        auto itend = gates.end();
        auto cmp = [](Gate a, Gate b) {
                         return a.id < b.id;
                     };

        //Sort
        std::sort(itbegin, itend, cmp);
        return;
    }
};

int Circuit::n;
vector<Gate> Circuit::gates;
vector<vector<ParsedGate>> Circuit::wires;
int Circuit::num_internal_wires;
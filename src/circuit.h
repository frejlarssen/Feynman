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
    PHASE,
    SWAP,
    NOT,
    PAULIZ
};

GateType gate_type_from_string(const string& s) { //TODO: Confirm it's according to QASM 3.0
    if (s == "h" || s == "H") {
        return HADAMARD;
    } else if (s == "p") {
        return PHASE;
    } else if (s == "swap" || s == "SWAP") {
        return SWAP;
    } else if (s == "x" || s == "X" || s == "not") {
        return NOT;
    } else if (s == "z") {
        return PAULIZ;
    } else {
        cerr << "Unknown gate type: " << s << endl;
        exit(1);
    }
}

std::string gate_type_to_string(GateType type) {
    switch (type) {
        case HADAMARD: return "HADAMARD";
        case PHASE: return "PHASE";
        case SWAP: return "SWAP";
        case NOT: return "NOT";
        case PAULIZ: return "PAULIZ";
        default: return "UNKNOWN";
    }
}

struct GateTypeInfo {
    GateType type;
    int num_targets;
    bool breaks_internal_wire; // Does it change 0/1?
    bool deterministic; // True for all except H-gate. Could maybe optimize/simplify by using this fact.
    int num_params; // How many parameters? (angle etc)

    // Constructor
    GateTypeInfo(GateType t, int nt, bool b, bool d, int np) : type(t), num_targets(nt), breaks_internal_wire(b), deterministic(d), num_params(np) {}
};

//Must be defined in the same way as in the enum GateType (if we don't remove that one and use only this).
const array<GateTypeInfo,5> gate_type_infos = {
    GateTypeInfo(HADAMARD, 1, true, false, 0),
    GateTypeInfo(PHASE, 1, false, true, 1),
    GateTypeInfo(SWAP, 2, true, true, 0),
    GateTypeInfo(NOT, 1, true, true, 0),
    GateTypeInfo(PAULIZ, 1, false, true, 0)
};

// Stored on each wire it takes as argument.
struct ParsedGate {
    const int id; // ID from line in circuit file.
    const GateType type;
    const int num_controls; // The first num_controls arguments are controls, the rest are targets.
    const vector<int> args; // Of size type.num_targets + this.num_controls. wires[0] is the argument to the first parameter etc.
    const int qparam; // The qubit parameter of which argument-wire this struct is stored.
    const vector<float> params; // The parameters, for example the angle of a phase.
    // Constructor
    ParsedGate(int i, GateType t, int nc, vector<int> a, int qp, vector<float> p) : id(i), type(t), num_controls(nc), args(a), qparam(qp), params(p) {}
};

string parsed_gate_to_string(const ParsedGate& pg) {
    string s = "ParsedGate(id=" + to_string(pg.id) + ", type=" + gate_type_to_string(pg.type) + ", num_controls=" + to_string(pg.num_controls) + ", args=[";
    for (size_t i = 0; i < pg.args.size(); i++) {
        s += to_string(pg.args[i]);
        if (i < pg.args.size() - 1) s += ", ";
    }
    s += "]";
    s += ", qparam=" + to_string(pg.qparam) + ", param=[";
    for (int i = 0; i < pg.params.size(); i++) {
        s += to_string(pg.params[i]);
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

//TODO: What can we call this? A GateQubit has two of these.
// This info is needed over all histories, which is why SET is not here.
enum InternalWireStatus {
    NOT_REACHED,
    INPUT,
    OUTPUT,
    ARTIFICIAL,
    REACHED
};

std::string gate_qubit_status_to_string(InternalWireStatus status) {
    switch (status) {
        case NOT_REACHED: return "NOT_REACHED";
        case INPUT: return "INPUT";
        case OUTPUT: return "OUTPUT";
        case ARTIFICIAL: return "ARTIFICIAL";
        case REACHED: return "REACHED";
        default: return "UNKNOWN";
    }
}


// TODO: Could make another struct InternalWire that this one references.
//       This and the next GateQubit would share InternalWire.
//       This would remove duplicates.
//       What about performance? We would dereference the internal wire
//       instead of dereferencing prev and next.
struct GateQubit {

    // Consistent after analysis
    int wire;
    bool is_control;
    InternalWireStatus input_status; // Should be the same as next->output_status
    InternalWireStatus output_status;
    GateQubit* prev; //Constitutes a double linked list, one for each wire.
    GateQubit* next;

    // Global indexing of artificial source in/out.
    // Only relevant if corresponding status = artificial.
    // Used to set val from given history.
    int artificial_in;
    int artificial_out;

    // Decides weather val_{in/out} is valid
    bool val_in_set;
    bool val_out_set;

    // The acctual values. Set in analysis for NATURAL, and for each history for the others.
    bool val_in;
    bool val_out;

    // Constructor
    GateQubit(int w, bool ctrl,
              InternalWireStatus instat=NOT_REACHED,
              InternalWireStatus outstat=NOT_REACHED,
              GateQubit* prev = nullptr,
              GateQubit* next = nullptr,
              int art_in = -1,
              int art_out = -1,
              bool val_in_set = false,
              bool val_out_set = false,
              bool val_in = false,
              bool val_out = false)
        : wire(w), is_control(ctrl),
          input_status(instat), output_status(outstat),
          prev(prev), next(next),
          artificial_in(art_in),
          artificial_out(art_out),
          val_in_set(val_in_set),
          val_out_set(val_out_set),
          val_in(val_in), val_out(val_out) {}
    
    // Default constructor
    GateQubit()
        : wire(-1), is_control(false),
          input_status(NOT_REACHED), output_status(NOT_REACHED) {} // wire -1 is means not set yet.
};

string gate_qubit_to_string(const GateQubit& gq) {
    return "(wire: " + to_string(gq.wire) +
           ", control: " + (gq.is_control ? "true" : "false") +
           ", input_status: " + (gate_qubit_status_to_string(gq.input_status)) +
           ", output_status: " + (gate_qubit_status_to_string(gq.output_status)) +
           //", prev: " + (gq.prev == nullptr ? "nullptr" : to_string((*gq.prev).id))
           ", artificial_in: " + to_string(gq.artificial_in) +
           ", artificial_out: " + to_string(gq.artificial_out) +
           ", val_in_set: " + (gq.val_in_set ? "true" : "false") +
           ", val_out_set: " + (gq.val_out_set ? "true" : "false") +
           ", val_in: " + (gq.val_in ? "true" : "false") +
           ", val_out: " + (gq.val_out ? "true" : "false") + ")";
}

struct Gate {
    int id;
    GateType type;
    int num_controls;
    vector<GateQubit> qubits; //Argument list. Order is same as in QASM.
    vector<float> params;

    // Constructor
    Gate(int id, GateType t, int nc, vector<GateQubit> qs, vector<float> p)
        : id (id), type(t), num_controls(nc), qubits(std::move(qs)), params(p) {}
};

string gate_to_string(const Gate& g) {
    string str = "Gate(id="+to_string(g.id) +
    ", type="+gate_type_to_string(g.type) +
    ", num_controls="+to_string(g.num_controls) +
    ", qubits=[";
    for (int qi = 0; qi < g.qubits.size(); qi++) {
        str += gate_qubit_to_string(g.qubits[qi]);
        if (qi < g.qubits.size() - 1) str += ", ";
    }
    str += "]";
    str += ", param=[";
    for (int i = 0; i < g.params.size(); i++) {
        str += to_string(g.params[i]);
    }
    str += "])";
    return str;
}

//TODO: Fix internal indexing to be consistent with history indexing
struct Circuit {
    static int n;
    static vector<Gate> gates; //TODO: Fix const
    static vector<vector<ParsedGate>> wires;
    static int num_artificial; // Number of artificial sources

    // Generate the QFT gates
    static void parse_circuit(string filename) {

        cout << "Parsing circuit from file: " << filename << endl;
        ifstream file(filename);

        // String to store each line of the file.
        string line;

        // TODO: Maybe use a real parser instead. Or maybe none is very up to date.
        if (file.is_open()) {

            if (getline(file, line) && line != "OPENQASM 3.0;") {
                cerr << "Only OPENQASM 3.0 supported" << endl;
                exit(1);
            }

            if (getline(file, line) && line != "include \"stdgates.inc\";") { //TODO: Fix support for standard library.
                cerr << "Only stdgates.inc supported" << endl;
                exit(1);
            }

            string qreg_name;
            size_t bracket_pos;
            size_t end_bracket_pos;
            getline(file, line);
            // Support for both qreg (qiskit) and qubit (v3). qreg is soon deprecated: https://openqasm.com/language/types.html

            string stripped_line = line.substr(5); // Remove "qubit" or "qreg "
            bracket_pos = stripped_line.find('[');
            end_bracket_pos = stripped_line.find(']');
            if (bracket_pos == string::npos || end_bracket_pos == string::npos || end_bracket_pos <= bracket_pos) {
                cerr << "Invalid qubit register declaration" << endl;
                exit(1);
            }
            if (line.substr(0, 5) == "qubit") {
                qreg_name = stripped_line.substr(end_bracket_pos + 2, stripped_line.size() - end_bracket_pos - 3);
            }
            else if (line.substr(0, 4) == "qreg") {
                qreg_name = stripped_line.substr(0, bracket_pos);
            }
            else {
                cerr << "Expected qubit or qreg keyword" << endl;
                exit(1);
            }

            n = stoi(stripped_line.substr(bracket_pos + 1, end_bracket_pos - bracket_pos - 1));
            wires.resize(n);

            int gate_index = 0;
            // Read each line from the file and store it in the
            // 'line' variable.
            while (getline(file, line)) {
                size_t space = line.find(' ');
                string type_param_str = line.substr(0, space);
                string qubits_str = line.substr(space + 1);

                size_t left_par = type_param_str.find('(');
                size_t right_par = type_param_str.find(')');
                
                string type_str;
                string params_str;
                if (left_par != string::npos && right_par != string::npos) {
                    type_str = type_param_str.substr(0, left_par);
                    params_str = type_param_str.substr(left_par + 1, right_par - left_par - 1);
                } else {
                    type_str = type_param_str;
                    params_str = "";
                }

                int num_controls = 0;
                for (int i = 0; i < type_str.length(); i++) {
                    if (type_str.at(i) == 'c') {
                        num_controls ++;
                    }
                    else {
                        break;
                    }
                }

                string basic_type_str = type_str.substr(num_controls);

                //TODO: Store parsed gate with a certain number of control bits and with a basic target type.

                std::stringstream param_stream(params_str);
                std::string param_str;
                vector<float> params;
                int param = 0;
                while (getline(param_stream, param_str, ',')) {
                    float param = stof(param_str);
                    params.push_back(param);
                }

                std::stringstream qubit_stream(qubits_str);
                std::string qubit_str;
                vector<int> arg_indices;
                while (getline(qubit_stream, qubit_str, ',')) {
                    if (qubit_str.substr(0, qreg_name.size() + 1) != qreg_name + "[") {
                        cerr << "Invalid qubit name" << endl;
                        exit(1);
                    }
                    int qubit_index = stoi(qubit_str.substr(qubit_str.find('[') + 1, qubit_str.find(']') - qubit_str.find('[') - 1));
                    arg_indices.push_back(qubit_index);
                }

                for (int qparam = 0; qparam < arg_indices.size(); qparam++) {
                    int arg_index = arg_indices[qparam];
                    if (arg_index < 0 || arg_index >= n) {
                        cerr << "Qubit index out of range" << endl;
                        exit(1);
                    }
                    wires[arg_index].emplace_back(gate_index, gate_type_from_string(basic_type_str), num_controls, arg_indices, qparam, params);
                }
                gate_index++;
            }

            file.close();
        }
        else {
            cerr << "Unable to open file!" << endl;
            exit(1);
        }

        for (size_t i = wires.size() - 1; i >= 0 && i < wires.size(); i--) {
            cout << "Wire " << i << ": " << wire_to_string(wires[i]) << "\n";
        }

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

    // An implementation of FakeRun, which is one way to select artificial sources.
    static int right_to_left() {
        int artificial_index = -1; // -1 is output of wire 0
        
        // Iterate gate list backwards.
        for (int i = Circuit::gates.size() - 1; i >= 0; i--) {
            Gate& gate = Circuit::gates[i];
            for (int q = 0; q < gate.qubits.size(); q++) {
                GateQubit& gq = gate.qubits[q];
                if (gate_type_infos[gate.type].deterministic || gq.is_control) {
                    // All to right should already be reached.
                    // Propagate determinism
                
                    // Check to not overwrite source
                    if (gq.input_status == NOT_REACHED) {
                        gq.input_status = REACHED;   
                    }
                    if (gq.prev != nullptr &&
                        gq.prev->output_status == NOT_REACHED) {
                        gq.prev->output_status = REACHED;
                    }
                } else { // Nondeterministic target
                    if (gq.input_status == NOT_REACHED) {
                        gq.input_status = ARTIFICIAL;
                        artificial_index ++;
                        gq.artificial_in = artificial_index;
                    }
                    if (gq.prev != nullptr &&
                        // We store the same info about the wire no the other end
                        gq.prev->output_status == NOT_REACHED) {
                        gq.prev->output_status = ARTIFICIAL;
                        gq.prev->artificial_out = artificial_index;
                    }
                }
            }

            // Iterate list
                //// Maybe add internal wire
                //if (is_control) {
                //    // Control qubit. No new internal wire.
                //} else if (!gate_type_infos[pg.type].breaks_internal_wire) {
                //    // Target produces no new internal wire
                //} else if (at_input || prev_over_output) {
                //    // No new internal wire either (since circuit input/output doesn't come from histories)
                //} else {
                //    //printf("Internal wire found\n");
                //    artificial_index++;
                //}
            //}
        }
        return artificial_index + 1;
    }

    // Build the global gate list from parsed gates on each wire.
    // Counts internal wires.
    // Adds only the qubit on that wire.
    // Sort based on idx.
    static void build_gate_list() {
        for (int wire = 0; wire < n; wire++) {

            int nr_pgs_on_input = 0;
            for (int pgi = 0; pgi < wires[wire].size(); pgi++) {
                ParsedGate& pg = wires[wire][pgi];
                if (!(pg.qparam < pg.num_controls) && gate_type_infos[pg.type].breaks_internal_wire) {
                    // Not control and target breaks wire.
                    nr_pgs_on_input = pgi + 1;
                    break;
                }
            }

            cout << "wire: " << wire << ": nr_pgs_on_input=" << nr_pgs_on_input << endl;

            GateQubit* next = nullptr;
            bool prev_over_output = true;
            for (int pgi = wires[wire].size() - 1; pgi >= 0; pgi--) {
                ParsedGate& pg = wires[wire][pgi];
                //printf("Processing parsed gate: %s at wire %d\n", parsed_gate_to_string(pg).c_str(), wire);
                
                // Check if gate is already added. Two ways:
                // 1. check if it has a wire w lower than wire.
                // 2. Check if id exists in gates.

                // If it already exists, we need to fetch the gate using the id.
                // We can try to fetch using id, that will solve both.

                int idx = vector_idx_of_gate(pg.id);

                //cout << "idx: " << idx << "\n";

                // We need to know which parameter (index in pg.wires) that has this wire as arugment,
                // that is pg.args[parameter_idx] = wire
                // This, we could have stored directly.

                // Build/modify gate
                bool is_control = (pg.qparam < pg.num_controls);
                
                // Input bitstring propagates to inputs...
                InternalWireStatus stat_input = pgi < nr_pgs_on_input ? INPUT : NOT_REACHED;
                
                // ...and outputs of gates
                InternalWireStatus stat_output = NOT_REACHED;
                if (is_control || !gate_type_infos[pg.type].breaks_internal_wire) {
                    stat_output = pgi < nr_pgs_on_input ? INPUT : NOT_REACHED;
                } else {
                    stat_output = pgi < nr_pgs_on_input-1 ? INPUT : NOT_REACHED;
                }

                // Output bitstring propagates to...
                if (prev_over_output) {
                    // ...output
                    stat_output = OUTPUT;
                    if (!is_control && gate_type_infos[pg.type].breaks_internal_wire) {
                        // Not control and target breaks wire.
                        prev_over_output = false;
                        stat_input = INPUT;
                    }
                }

                // Decide if they are natural sources, add Gate's.
                // Fix linked list: Point to previous one, and make previous one point to this one.
                // When all are added, FakeRun forward to set artificial and reached.
                // Update using linked list.
                GateQubit q = GateQubit(wire, is_control, stat_input, stat_output, nullptr, next);
                //cout << "q: " << gate_qubit_to_string(q) << endl;
                if (next != nullptr) {
                    //cout << "*prev: " << gate_qubit_to_string(*prev) << endl;
                    (*next).prev = &q;
                }

                //cout << "q: " << gate_qubit_to_string(q) << "\n";

                if (idx == -1) { // Add new
                    int numq = pg.num_controls + gate_type_infos[pg.type].num_targets;

                    vector<GateQubit> args(numq);
                    args.at(pg.qparam) = q;
                    gates.emplace_back(pg.id, pg.type, pg.num_controls, args, pg.params);
                } else { // Update existing
                    gates[idx].qubits.at(pg.qparam) = q;
                }

                next = &q;
            }
        }

        auto itbegin = gates.begin();
        auto itend = gates.end();
        auto cmp = [](Gate a, Gate b) {
                         return a.id < b.id;
                     };

        //Sort
        std::sort(itbegin, itend, cmp);

        printf("Gates before fake run:\n");
        for (int i = 0; i < Circuit::gates.size(); i++){
            printf("\t%s\n", gate_to_string(Circuit::gates[i]).c_str());
        }

        // Do fake run to check how sources reach,
        // set artificial sources, and report back number of artificial sources.
        // Begin with implementing R->L since it is optimal for QFT.
        //Circuit::num_artificial = right_to_left();

        
        return;
    }
};

int Circuit::n;
vector<Gate> Circuit::gates;
vector<vector<ParsedGate>> Circuit::wires;
int Circuit::num_artificial;
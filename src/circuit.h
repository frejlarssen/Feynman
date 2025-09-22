#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include <sstream>
#include <algorithm>
#include <functional>
#include <memory>

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

// This info is needed over all histories, which is why SET is not here.
enum InternalWireStatus {
    NOT_REACHED,
    INPUT,
    OUTPUT,
    ARTIFICIAL,
    REACHED
};

std::string internal_wire_status_to_string(InternalWireStatus status) {
    switch (status) {
        case NOT_REACHED: return "NOT_REACHED";
        case INPUT: return "INPUT";
        case OUTPUT: return "OUTPUT";
        case ARTIFICIAL: return "ARTIFICIAL";
        case REACHED: return "REACHED";
        default: return "UNKNOWN";
    }
}

struct GateQubit;

// A wire where the value doesn't change.
// Allows us to set an artificial source, and the value is propagated accross PHASE-gates etc instantly.
// Multiple gates can be connected to the same InternalWire.
struct InternalWire {
    int wire;
    InternalWireStatus status;
    GateQubit* start; //Constitutes a double linked list, one for each wire.
    GateQubit* end;

    // Global indexing of artificial source.
    // Only relevant if corresponding status = artificial.
    // Used to set val from given history.
    int artificial;

    // Decides weather val is valid
    bool val_set;

    // The acctual values. Set in analysis for NATURAL, and for each history for the others.
    bool val;

    // Constructor
    InternalWire(int w,
              InternalWireStatus stat=NOT_REACHED,
              GateQubit* start = nullptr,
              GateQubit* end = nullptr,
              int artif = -1,
              bool val_set = false,
              bool val = false)
        : wire(w),
          status(stat),
          start(start), end(end),
          artificial(artif),
          val_set(val_set),
          val(val) {}

    // Default constructor
    InternalWire()
        : wire(-1) {} // wire -1 is means not set yet.
};

string internal_wire_to_string(const InternalWire& iw) {
    return "(wire: " + to_string(iw.wire) +
           ", status: " + (internal_wire_status_to_string(iw.status)) +
           //", prev: " + (gq.prev == nullptr ? "nullptr" : to_string((*gq.prev).id))
           ", artificial: " + to_string(iw.artificial) +
           ", val_set: " + (iw.val_set ? "true" : "false") +
           ", val: " + (iw.val ? "true" : "false") + ")";
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
    std::shared_ptr<InternalWire> wire_left;
    std::shared_ptr<InternalWire> wire_right; // In and out could be the same! But wire_right->end can be used to iterate list.
    GateQubit* prev; // Constitutes a double linked list, one for each wire.
    GateQubit* next; // Necessary?

    // Constructor
    GateQubit(int w, bool ctrl,
              std::shared_ptr<InternalWire> in=nullptr,
              std::shared_ptr<InternalWire> out=nullptr,
              GateQubit* prev = nullptr,
              GateQubit* next = nullptr)
        : wire(w), is_control(ctrl),
          wire_left(in), wire_right(out),
          prev(prev), next(next) {}
    
    // Default constructor
    GateQubit()
        : wire(-1), is_control(false) {} // wire -1 is means not set yet.
};

string gate_qubit_to_string(const GateQubit& gq) {
    return "(wire: " + to_string(gq.wire) +
           ", control: " + (gq.is_control ? "true" : "false") + 
           ", wire_left: " + (internal_wire_to_string(*gq.wire_left)) +
           ", wire_right: " + (internal_wire_to_string(*gq.wire_right))
           //", prev: " + (gq.prev == nullptr ? "nullptr" : to_string((*gq.prev).id))
           + ")";
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
    ", qubits=[\n";
    for (int qi = 0; qi < g.qubits.size(); qi++) {
        str += "    " + gate_qubit_to_string(g.qubits[qi]);
        if (qi < g.qubits.size() - 1) str += ", \n";
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
    static vector<std::shared_ptr<InternalWire>> input_sources;
    static vector<std::shared_ptr<InternalWire>> output_sources;
    static vector<std::shared_ptr<InternalWire>> artificial_sources;
    static vector<Gate*> deterministically_breaking;

    // Parse circuit from QASM-file
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
    static int right_to_left_fake() {
        int artificial_index = 0;
        
        // Iterate gate list right to left.
        for (int i = Circuit::gates.size() - 1; i >= 0; i--) {
            Gate& gate = Circuit::gates[i];
            for (int q = 0; q < gate.qubits.size(); q++) {
                // All to right should already be reached because we have already visited them.
                GateQubit& gq = gate.qubits[q];
                if (gq.is_control || !gate_type_infos[gate.type].breaks_internal_wire) {
                    // Same internal wire left and right => determinism have already propagated
                    continue;
                }
                if (gate_type_infos[gate.type].deterministic) {
                    // Propagate determinism
                    // Check to not overwrite source
                    if (gq.wire_left->status == NOT_REACHED) {
                        gq.wire_left->status = REACHED;   
                    }
                } else { // Nondeterministic target
                    if (gq.wire_left->status == NOT_REACHED) {
                        gq.wire_left->status = ARTIFICIAL;
                        gq.wire_left->artificial = artificial_index;
                        Circuit::artificial_sources.push_back(gq.wire_left);
                        artificial_index ++;
                    }
                }
            }
        }
        return artificial_index;
    }

    // Sets values from R->L to mimic fake run
    static void right_to_left_natural(vector<bool> input_bits, vector<bool> output_bits) {
        int artificial_index = 0;

        for (const std::shared_ptr<InternalWire>& w : Circuit::output_sources) {
            w->val = output_bits[w->wire];
            w->val_set = true;
        }

        for (const std::shared_ptr<InternalWire>& w : Circuit::input_sources) {
            w->val = input_bits[w->wire];
            w->val_set = true;
        }

        // Iterate gate list right to left.
        for (int i = Circuit::gates.size() - 1; i >= 0; i--) {
            Gate& gate = Circuit::gates[i];

            cout << "In natural pass for gate " << gate.id << endl;

            // Check if all to right are set
            bool all_set = true;
            for (int q = 0; q < gate.qubits.size(); q++) {
                if (!gate.qubits[q].wire_right->val_set) {
                    all_set = false;
                    break;
                }
            }

            cout << "all_set: " << all_set << endl;

            if (all_set && gate_type_infos[gate.type].deterministic) {
                // Set all to the left.
                cout << "all_set and deterministic" << endl;

                // Check if activated
                bool activate = true;
                for (int c = 0; c < gate.num_controls; c++) {
                    if (!gate.qubits[c].wire_right->val) {
                        activate = false;
                        break;
                    }
                }

                if (!activate) {
                    for (int t = gate.num_controls; t < gate.num_controls + gate_type_infos[gate.type].num_targets; t++) {
                        gate.qubits[t].wire_left->val = gate.qubits[t].wire_right->val;
                    }
                }
                else {
                    switch (gate.type) {
                    case NOT:
                        gate.qubits[gate.num_controls].wire_left->val = !gate.qubits[gate.num_controls].wire_right->val;
                        gate.qubits[gate.num_controls].wire_left->val_set = true;
                        break;
                    case SWAP:
                        gate.qubits[gate.num_controls].wire_left->val = gate.qubits[gate.num_controls + 1].wire_right->val;
                        gate.qubits[gate.num_controls].wire_left->val_set = true;
                        gate.qubits[gate.num_controls + 1].wire_left->val = gate.qubits[gate.num_controls].wire_right->val;
                        gate.qubits[gate.num_controls + 1].wire_left->val_set = true;
                        break;
                    default:
                        cerr << "Gate not implemented in right to left real pass" << endl;
                    }
                }
            }
        }
        return;
    }

    // Build the global gate list from parsed gates on each wire.
    // Counts internal wires.
    // Adds only the qubit on that wire.
    // Sort based on idx.
    static void build_gate_list() {
        for (int wire = 0; wire < n; wire++) {

            std::shared_ptr<InternalWire> output_wire = std::make_shared<InternalWire>(wire, OUTPUT);
            Circuit::output_sources.push_back(output_wire);
            GateQubit* next = nullptr;
            bool prev_over_output = true;

            // TODO: Build Gate list of GateQubit, and InternalWire's. Reference accordingly. 
            // TODO: Set first internal wire to input

            // We iterate backwards in case we want to number the internal wires,
            // and to keep it consistent with internal-wire-based version.
            for (int pgi = wires[wire].size()-1; pgi >= 0; pgi--) {
                ParsedGate& pg = wires[wire][pgi];
                //printf("Processing parsed gate: %s at wire %d\n", parsed_gate_to_string(pg).c_str(), wire);

                int idx = vector_idx_of_gate(pg.id);

                // Build/modify gate
                bool is_control = (pg.qparam < pg.num_controls);

                std::shared_ptr<InternalWire> input_wire;
                if (!is_control && gate_type_infos[pg.type].breaks_internal_wire) {
                    input_wire = std::make_shared<InternalWire>(wire);
                }
                else {
                    input_wire = output_wire;
                }

                // Decide if they are natural sources, add Gate's.
                // Fix linked list: Point to previous one, and make previous one point to this one.
                // When all are added, FakeRun forward to set artificial and reached.
                // Update using linked list.
                GateQubit q = GateQubit(wire, is_control, input_wire, output_wire, nullptr, next);

                if (!is_control && gate_type_infos[pg.type].breaks_internal_wire) {
                    output_wire = input_wire;
                }

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
                    Gate gate = Gate(pg.id, pg.type, pg.num_controls, args, pg.params);
                    gates.emplace_back(gate);
                    if (gate_type_infos[gate.type].deterministic && gate_type_infos[gate.type].breaks_internal_wire) {
                        deterministically_breaking.push_back(&gate);
                        // TODO: Compare push_back and emplace_back
                    }
                } else { // Update existing
                    gates[idx].qubits.at(pg.qparam) = q;
                }

                next = &q;
            }

            // Set the leftmost InternalWire to INPUT
            next->wire_left->status = INPUT;
            Circuit::input_sources.push_back(next->wire_left);
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
            printf("  %s\n", gate_to_string(Circuit::gates[i]).c_str());
        }

        // Do fake run to check how sources reach,
        // set artificial sources, and report back number of artificial sources.
        // Begin with implementing R->L since it is optimal for QFT.
        Circuit::num_artificial = right_to_left_fake();

        printf("Gates after fake run:\n");
        for (int i = 0; i < Circuit::gates.size(); i++){
            printf("  %s\n", gate_to_string(Circuit::gates[i]).c_str());
        }

        return;
    }
};

int Circuit::n;
vector<Gate> Circuit::gates;
vector<vector<ParsedGate>> Circuit::wires;
int Circuit::num_artificial;
vector<std::shared_ptr<InternalWire>> Circuit::input_sources;
vector<std::shared_ptr<InternalWire>> Circuit::output_sources;
vector<std::shared_ptr<InternalWire>> Circuit::artificial_sources;
vector<Gate*> Circuit::deterministically_breaking;
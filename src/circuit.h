#include <iostream>
#include <vector>
#include <string>
#include <fstream>
#include <sstream>
#include <algorithm>
#include <functional>
#include <memory>
#include <optional>
#include <unordered_map>
#include "utils.h"
#include "parsed_circuit.h"

#define PI 3.141592653589793

using namespace std;

// This info is needed over all histories, which is why SET is not here.
enum InternalWireStatus {
    NOT_REACHED,
    INPUT,
    OUTPUT,
    ARTIFICIAL,
    REACHED
};

std::string internal_wire_status_to_string(InternalWireStatus status) {
    //cout << "in internal_wire_status_to_string" << endl;
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
    int id; //For debugging
    int wire;
    InternalWireStatus status;
    //GateQubit* start; //Constitutes a double linked list, one for each wire.
    //GateQubit* end;

    // Global indexing of artificial source.
    // Only relevant if corresponding status = artificial.
    // Used to set val from given history.
    int artificial;

    // Decides weather val is valid
    vector<uint8_t> val_set;

    // The acctual values. Set in analysis for NATURAL, and for each history for the others.
    vector<uint8_t> val;

    // Constructor
    InternalWire(int id, int w,
              InternalWireStatus stat=NOT_REACHED,
              //GateQubit* start = nullptr,
              //GateQubit* end = nullptr,
              int artif = -1,
              // Init to empty vectors
              int nr_hists = 0)
        : id(id),
          wire(w),
          status(stat),
          //start(start), end(end),
          artificial(artif),
          val_set(nr_hists, false),
          val(nr_hists, false) {}

    bool set_safe(int history, bool new_val) {
        if (val_set.at(history) && (val.at(history) != new_val)) {
            return false;
        }
        val.at(history) = new_val;
        val_set.at(history) = true;
        return true;
    }

    bool set_safe_all(int num_artificial, bool new_val) {
        for (int h = 0; h < 1 << num_artificial; h++) {
            if (!set_safe(h, new_val)) {
                return false;
            }
        }
        return true;
    }
};

string internal_wire_to_string(const InternalWire& iw, int verbosity=0) {
    //cout << "in internal_wire_to_string" << endl;

    string str = "(id: " + to_string(iw.id) + ", wire: " + to_string(iw.wire) +
           ", status: " + (internal_wire_status_to_string(iw.status)) +
           //", prev: " + (gq.prev == nullptr ? "nullptr" : to_string((*gq.prev).id))
           ", artificial: " + to_string(iw.artificial) +
           ", nr_histories: " + to_string(iw.val_set.size());
    //cout << "verbosity in internal_wire_to_string: " << verbosity << endl;
    if (iw.val_set.size() <= 20 && verbosity > 0) {
        str += ", histories: [";
        for (size_t i = 0; i < iw.val_set.size(); i++) {
            str += "h" + to_string(i);
            if (iw.val_set.at(i)) {
                str += " set:";
                str += (iw.val.at(i) ? "1" : "0");
            } else {
                str += " not set";
            }
            if (i < iw.val_set.size() - 1) str += ", ";
        }
        str += "]";
    } else {
        str += ", (not showing histories)";
    }
    return str;
}

string internal_wire_to_string(const std::shared_ptr<InternalWire>& iw, int verbosity=0) {
    if (!iw) {
        return "no iw";
    }
    return internal_wire_to_string(*iw, verbosity);  // delegate to the reference overload
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
    std::shared_ptr<GateQubit> prev; // Constitutes a double linked list, one for each wire.
    std::shared_ptr<GateQubit> next; // Necessary?

    // Constructor
    GateQubit(int w, bool ctrl,
              std::shared_ptr<InternalWire> wl=nullptr,
              std::shared_ptr<InternalWire> wr=nullptr,
              std::shared_ptr<GateQubit> prev = nullptr,
              std::shared_ptr<GateQubit> next = nullptr)
        : wire(w), is_control(ctrl),
          wire_left(wl), wire_right(wr),
          prev(prev), next(next) {}
};

string gate_qubit_to_string(GateQubit& gq, int verbosity=0) {
    string str = "(wire: " + to_string(gq.wire);
    string ctrlbool = (gq.is_control ? "true" : "false");
    str += ", control: " + ctrlbool +
           ", wire_left: " + (internal_wire_to_string(gq.wire_left, verbosity)) +
           ", wire_right: " + (internal_wire_to_string(gq.wire_right, verbosity)) +
           //", prev: " + (gq.prev == nullptr ? "nullptr" : to_string((*gq.prev).id))
            ")";
    return str;
}

std::string gate_qubit_to_string(const std::shared_ptr<GateQubit>& gq, int verbosity=0) {
    if (!gq) {
        return "no GateQubit yet";
    }
    return gate_qubit_to_string(*gq, verbosity);  // delegate to the reference overload
}

struct Gate {
    int id;
    GateType type;
    int num_controls;
    vector<shared_ptr<GateQubit>> qubits; //Argument list. Order is same as in QASM.
    vector<float> params;

    // Constructor
    Gate(int id, GateType t, int nc, vector<shared_ptr<GateQubit>> qs, vector<float> p)
        : id (id), type(t), num_controls(nc), qubits(std::move(qs)), params(p) {}
};

string gate_to_string(const Gate& g, int verbosity=0) {
    //cout << "verbosity in gate_to_string: " << verbosity << endl;
    string str = "Gate(verbosity=" + to_string(verbosity) +
    ", id="+to_string(g.id) +
    ", type="+gate_type_to_string(g.type) +
    ", num_controls="+to_string(g.num_controls) +
    ", qubits=[\n";
    for (int qi = 0; qi < g.qubits.size(); qi++) {
        str += "    " + gate_qubit_to_string(g.qubits[qi], verbosity);
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

struct Chunk {
    int num_artificial = 0;
    vector<std::shared_ptr<Gate>> gates = vector<std::shared_ptr<Gate>>(0); // In order of application.
    vector<std::shared_ptr<Gate>> deterministically_breaking = vector<std::shared_ptr<Gate>>(0);
    vector<std::shared_ptr<InternalWire>> input_sources = vector<std::shared_ptr<InternalWire>>(0);
    vector<std::shared_ptr<InternalWire>> output_sources = vector<std::shared_ptr<InternalWire>>(0);
    vector<std::shared_ptr<InternalWire>> artificial_sources = vector<std::shared_ptr<InternalWire>>(0);

    // An implementation of FakeRun, which is one way to select artificial sources.
    int right_to_left_fake() {
        int artificial_index = 0;
        
        // Iterate gate list right to left.
        for (int i = gates.size() - 1; i >= 0; i--) {
            Gate& gate = *gates[i];
            for (int q = 0; q < gate.qubits.size(); q++) {
                // All to right should already be reached because we have already visited them.
                GateQubit& gq = *gate.qubits[q];
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
                        artificial_sources.push_back(gq.wire_left);
                        artificial_index ++;
                    }
                }
            }
        }
        return artificial_index;
    }

    // Sets values from R->L to mimic fake run
    // Returns true if successful, false if propagated values from output and input conflicts.
    bool right_to_left_natural(vector<bool> input_bits, vector<bool> output_bits) {
        int artificial_index = 0;

        for (const std::shared_ptr<InternalWire>& w : output_sources) {
            w->set_safe_all(num_artificial, output_bits[w->wire]);
        }

        for (const std::shared_ptr<InternalWire>& w : input_sources) {
            if (!w->set_safe_all(num_artificial, input_bits[w->wire])) { return false; }
        }

        // Iterate gate list right to left.
        for (int i = gates.size() - 1; i >= 0; i--) {
            Gate& gate = *gates.at(i);

            //cout << "In natural pass for gate " << gate.id << endl;

            // Check if all to right are set (we arbitrarily use history 0)
            bool all_set = true;
            for (int q = 0; q < gate.qubits.size(); q++) {
                if (!gate.qubits[q]->wire_right->val_set.at(0)) {
                    all_set = false;
                    break;
                }
            }

            //cout << "all_set: " << all_set << endl;

            if (all_set && gate_type_infos[gate.type].deterministic) {
                // Set all to the left.
                //cout << "all_set and deterministic" << endl;

                // Check if activated
                bool activate = true;
                for (int c = 0; c < gate.num_controls; c++) {
                    if (!gate.qubits[c]->wire_right->val.at(0)) {
                        activate = false;
                        break;
                    }
                }

                if (!activate) {
                    for (int t = gate.num_controls; t < gate.num_controls + gate_type_infos[gate.type].num_targets; t++) {
                        if (!gate.qubits[t]->wire_left->set_safe_all(num_artificial, gate.qubits[t]->wire_right->val.at(0))) { return false; }
                    }
                }
                else {
                    switch (gate.type) {
                    case NOT:
                        if (!gate.qubits[gate.num_controls]->wire_left->set_safe_all(num_artificial, !gate.qubits[gate.num_controls]->wire_right->val.at(0))) { return false; }
                        break;
                    case SWAP:
                        if (!gate.qubits[gate.num_controls]->wire_left->set_safe_all(num_artificial, gate.qubits[gate.num_controls + 1]->wire_right->val.at(0))) { return false; }
                        if (!gate.qubits[gate.num_controls + 1]->wire_left->set_safe_all(num_artificial, gate.qubits[gate.num_controls]->wire_right->val.at(0))) { return false;}
                        break;
                    default:
                        cerr << "Gate not implemented in right to left real pass" << endl;
                    }
                }
            }
        }
        return true;
    }

    // Sets values from R->L to mimic fake run
    bool right_to_left_artificial(int history/*, std::ostringstream& buf_history*/) {
        int artificial_index = 0;

        for (const std::shared_ptr<InternalWire>& w : artificial_sources) {
            w->set_safe(history, history >> (w->artificial) & 1);
        }

        // Iterate gate list right to left.
        for (int i = deterministically_breaking.size() - 1; i >= 0; i--) {
            Gate& gate = *deterministically_breaking[i];

            //cout << "In artificial pass for gate with id " << gate.id << endl;

            //cout << "  the gate: " << gate_to_string(gate) << endl;

            // Check if activated
            bool activate = true;
            for (int c = 0; c < gate.num_controls; c++) {
                GateQubit& the_qubit = *gate.qubits.at(c);
                if (!gate.qubits.at(c)->wire_right->val.at(history)) {
                    activate = false;
                    break;
                }
            }

            if (!activate) {
                for (int t = gate.num_controls; t < gate.num_controls + gate_type_infos[gate.type].num_targets; t++) {
                    if (!gate.qubits[t]->wire_left->set_safe(history, gate.qubits[t]->wire_right->val.at(history))) { return false;}
                }
            }
            else {
                switch (gate.type) {
                case NOT:
                    //fprintf_stream(buf_history, "  NOT gate %d activated on wire %d\n", gate.id, gate.qubits[gate.num_controls]->wire);
                    if (!gate.qubits[gate.num_controls]->wire_left->set_safe(history, !gate.qubits[gate.num_controls]->wire_right->val.at(history))) { return false; }
                    break;
                case SWAP:
                    if (!gate.qubits[gate.num_controls]->wire_left->set_safe(history, gate.qubits[gate.num_controls + 1]->wire_right->val.at(history))) { return false; }
                    if (!gate.qubits[gate.num_controls + 1]->wire_left->set_safe(history, gate.qubits[gate.num_controls]->wire_right->val.at(history))) { return false; }
                    break;
                default:
                    cerr << "  Gate not implemented in right to left real pass" << endl;
                }
            }
        }
        return true;
    }
};

//TODO: Put everything in const datastructures after build, to optimize.
// One instance for each history.
struct Circuit {
    static int n;
    static vector<std::shared_ptr<Gate>> all_gates;
    static vector<std::shared_ptr<InternalWire>> all_internal_wires;
    static array<Chunk, 1> chunks;

    // -1 if not added yet. Otherwise idx such that gate[idx].id = id
    static int vector_idx_of_gate(int id) {
        for (int i = 0; i < all_gates.size(); i++) {
            if (all_gates[i]->id == id) {
                return i;
            }
        }
        return -1;
    }

    // Reset all values to not set. For testing.
    static void reset_values() {
        for (const std::shared_ptr<InternalWire>& w : Circuit::all_internal_wires) {
            std::fill(w->val_set.begin(), w->val_set.end(), false);
            std::fill(w->val.begin(), w->val.end(), false);
        }
    }

    // Build the global gate list from parsed gates on each wire.
    // Counts internal wires.
    // Adds only the qubit on that wire.
    // Sort based on idx.
    static void build_circuit() {
        //cout << "Building circuit from parsed circuit" << endl;
        //printf("Parsed circuit in build:\n");
        //printf("  %s\n", ParsedCircuit::parsed_circuit_to_string().c_str());

        Chunk& chunk = chunks.at(0);

        int iw_id = 0;
        for (int wire = 0; wire < ParsedCircuit::n; wire++) {

            std::shared_ptr<InternalWire> wire_right = std::make_shared<InternalWire>(iw_id++, wire, OUTPUT);
            all_internal_wires.emplace_back(wire_right);
            chunk.output_sources.emplace_back(wire_right);
            std::shared_ptr<GateQubit> next = nullptr;
            bool prev_over_output = true;

            // TODO: Build Gate list of GateQubit, and InternalWire's. Reference accordingly. 
            // TODO: Set first internal wire to input

            // We iterate backwards in case we want to number the internal wires,
            // and to keep it consistent with internal-wire-based version.
            for (int pgi = ParsedCircuit::wires[wire].size()-1; pgi >= 0; pgi--) {
                ParsedGate& pg = ParsedCircuit::wires[wire][pgi];
                //printf("Processing parsed gate: %s at wire %d\n", parsed_gate_to_string(pg).c_str(), wire);

                int idx = vector_idx_of_gate(pg.id);

                // Build/modify gate
                bool is_control = (pg.qparam < pg.num_controls);

                std::shared_ptr<InternalWire> wire_left;
                if (!is_control && gate_type_infos[pg.type].breaks_internal_wire) {
                    wire_left = std::make_shared<InternalWire>(iw_id++, wire);
                    all_internal_wires.emplace_back(wire_left);
                }
                else {
                    wire_left = wire_right;
                }

                // Decide if they are natural sources, add Gate's.
                // Fix linked list: Point to previous one, and make previous one point to this one.
                // When all are added, FakeRun forward to set artificial and reached.
                // Update using linked list.
                std::shared_ptr<GateQubit> q = make_shared<GateQubit>(wire, is_control, wire_left, wire_right, nullptr, next);

                if (!is_control && gate_type_infos[pg.type].breaks_internal_wire) {
                    wire_right = wire_left;
                }

                if (next != nullptr) {
                    (*next).prev = q;
                }

                if (idx == -1) { // Add new
                    int numq = pg.num_controls + gate_type_infos[pg.type].num_targets;

                    vector<shared_ptr<GateQubit>> args(numq);
                    args.at(pg.qparam) = q;
                    shared_ptr<Gate> gate = make_shared<Gate>(pg.id, pg.type, pg.num_controls, args, pg.params);
                    all_gates.emplace_back(gate);
                    chunk.gates.emplace_back(gate);
                    //printf("Added gate: %s\n", gate_to_string(*gate).c_str());
                    if (gate_type_infos[gate->type].deterministic && gate_type_infos[gate->type].breaks_internal_wire) {
                        chunk.deterministically_breaking.emplace_back(gate);
                    }
                } else { // Update existing
                    all_gates[idx]->qubits.at(pg.qparam) = q;
                }
                next = q;
            }

            // Set the leftmost InternalWire to INPUT
            next->wire_left->status = INPUT;
            chunk.input_sources.push_back(next->wire_left);
        }

        auto itbegin = all_gates.begin();
        auto itend = all_gates.end();
        auto cmp = [](shared_ptr<Gate> a, shared_ptr<Gate> b) {
                         return a->id < b->id;
                     };

        //Sort
        std::sort(itbegin, itend, cmp);

        auto itbegin2 = chunk.deterministically_breaking.begin();
        auto itend2 = chunk.deterministically_breaking.end();
        std::sort(itbegin2, itend2, cmp);

//        printf("Gates before fake run:\n");
//        for (int i = 0; i < Circuit::gates.size(); i++){
//            printf("  %s\n", gate_to_string(*Circuit::gates[i]).c_str());
//        }
//
        // Do fake run to check how sources reach,
        // set artificial sources, and report back number of artificial sources.
        // Begin with implementing R->L since it is optimal for QFT.
        chunk.num_artificial = chunk.right_to_left_fake();

        for (const std::shared_ptr<InternalWire>& w : all_internal_wires) {
            w->val_set.resize(1 << chunk.num_artificial, false);
            w->val.resize(1 << chunk.num_artificial, false);
        }

        return;
    }
};

int Circuit::n;
vector<std::shared_ptr<Gate>> Circuit::all_gates;
vector<std::shared_ptr<InternalWire>> Circuit::all_internal_wires;
std::array<Chunk, 1> Circuit::chunks;

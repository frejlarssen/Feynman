#include <iostream>
#include <vector>
#include <string>
#include <fstream>

#define NUM_QUBITS 4

using namespace std;

enum GateType {
    HADAMARD,
    CPHASE,
    SWAP
};

struct GateQubit {
    const int wire;
    const int internal_index;
    const bool is_control;

    // Constructor
    GateQubit(int w, int idx, bool ctrl)
        : wire(w), internal_index(idx), is_control(ctrl) {}
};

struct Gate {
    const GateType type;
    const vector<GateQubit> qubits;

    // Constructor
    Gate(GateType t, vector<GateQubit> qs)
        : type(t), qubits(std::move(qs)) {}
};

//TODO: Fix internal indexing to be consistent with history indexing
struct Circuit {
    static constexpr int num_qubits = NUM_QUBITS;
    static constexpr int num_gates = num_qubits * (num_qubits + 2) / 2;
    static const vector<Gate> gates;

    // Generate the QFT gates
    static vector<Gate> build_qft() {
        vector<Gate> g;

        // Step 1: Hadamards and controlled phases
        for (int group = 0; group < num_qubits; group++) {
            g.emplace_back(HADAMARD, vector<GateQubit>{GateQubit(group, 0, false)});
            for (int i = 1; i < num_qubits - group; i++) {
                g.emplace_back(CPHASE, vector<GateQubit>{
                    GateQubit(group + i, 0, true),   // control
                    GateQubit(group, i, false)      // target
                });
            }
        }

        // Step 2: Swaps
        for (int i = 0; i < num_qubits / 2; i++) {
            g.emplace_back(SWAP, vector<GateQubit>{
                GateQubit(i, num_qubits - i, false),
                GateQubit(num_qubits - i - 1, 1 + i, false)
            });
        }

        return g;
    }
};

const vector<Gate> Circuit::gates = Circuit::build_qft();
#include <string>
#include <vector>

#define NUM_QUBITS 6
#define PI 3.141592653589793

using namespace std;

enum GateType { HADAMARD, CPHASE, SWAP };

std::string gate_type_to_string(GateType type) {
  switch (type) {
  case HADAMARD:
    return "HADAMARD";
  case CPHASE:
    return "CPHASE";
  case SWAP:
    return "SWAP";
  default:
    return "UNKNOWN";
  }
}

struct GateQubit {
  const int wire; // Might not be necessary
  const int
      internal_index_in; // Might not be necessary. Should maybe be out instead.
  const int global_index;
  const bool is_control;
  const bool at_input;
  const bool at_output;

  // Constructor
  GateQubit(int w, int idx, bool ctrl, bool in = false, bool out = false)
      : wire(w), internal_index_in(idx),
        global_index(w * (2 * NUM_QUBITS - w + 1) / 2 + idx), is_control(ctrl),
        at_input(in), at_output(out) {}
};

// TODO: Add parameters (for phase)
struct Gate {
  const GateType type;
  const vector<GateQubit> qubits;
  const float parameter; // For gates that need parameters (e.g., CPHASE)

  // Constructor
  Gate(GateType t, vector<GateQubit> qs, float p = 0.0)
      : type(t), qubits(std::move(qs)), parameter(p) {}
};

// TODO: Fix internal indexing to be consistent with history indexing
struct Circuit {
  static constexpr int n = NUM_QUBITS;
  static constexpr int num_gates = n * (n + 2) / 2;
  static const vector<Gate> gates;

  // Generate the QFT gates
  static vector<Gate> build_qft() {
    vector<Gate> g;

    bool target_at_output = false;
    // Step 1: Hadamards and controlled phases
    for (int group = 0; group < n; group++) {
      g.emplace_back(HADAMARD, vector<GateQubit>{GateQubit(
                                   group, n - group, false, true, false)});
      for (int i = 1; i < n - group; i++) {
        // Edge case: target happens to be at output (no switch in the middle)
        if (n % 2 == 1 && group == n / 2 && i == n - group - 1) {
          bool phase_target_at_output = true;
        }
        g.emplace_back(CPHASE,
                       vector<GateQubit>{
                           GateQubit(group + i, n - group - i, true, true,
                                     false), // control
                           GateQubit(group, n - group - i, false, false,
                                     target_at_output) // target
                       },
                       -PI / (1 << i));
      }
    }

    // Step 2: Swaps
    for (int i = 0; i < n / 2; i++) {
      g.emplace_back(
          SWAP, vector<GateQubit>{GateQubit(n - i - 1, 0, false, false, true),
                                  GateQubit(i, 0, false, false, true)});
    }

    return g;
  }
};

const vector<Gate> Circuit::gates = Circuit::build_qft();
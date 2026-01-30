#include <array>
#include <iostream>
#include <string>

using namespace std;

enum GateType { HADAMARD, PHASE, SWAP, NOT, PAULIZ };

GateType gate_type_from_string(
    const string &s) { // TODO: Confirm it's according to QASM 3.0
  if (s == "h" || s == "H") {
    return GateType::HADAMARD;
  } else if (s == "p") {
    return GateType::PHASE;
  } else if (s == "swap" || s == "SWAP") {
    return GateType::SWAP;
  } else if (s == "x" || s == "X" || s == "not") {
    return GateType::NOT;
  } else if (s == "z") {
    return GateType::PAULIZ;
  } else {
    cerr << "Unknown gate type: " << s << endl;
    exit(1);
  }
}

std::string gate_type_to_string(GateType type) {
  switch (type) {
  case HADAMARD:
    return "HADAMARD";
  case PHASE:
    return "PHASE";
  case SWAP:
    return "SWAP";
  case NOT:
    return "NOT";
  case PAULIZ:
    return "PAULIZ";
  default:
    return "UNKNOWN";
  }
}

struct GateTypeInfo {
  GateType type;
  int num_targets;
  bool breaks_internal_wire; // Does it change 0/1?
  bool deterministic;        // True for all except H-gate. Could maybe
                             // optimize/simplify by using this fact.
  int num_params;            // How many parameters? (angle etc)

  // Constructor
  GateTypeInfo(GateType t, int nt, bool b, bool d, int np)
      : type(t), num_targets(nt), breaks_internal_wire(b), deterministic(d),
        num_params(np) {}
};

// Must be defined in the same way as in the enum GateType (if we don't remove
// that one and use only this).
const array<GateTypeInfo, 5> gate_type_infos = {
    GateTypeInfo(GateType::HADAMARD, 1, true, false, 0),
    GateTypeInfo(GateType::PHASE, 1, false, true, 1),
    GateTypeInfo(GateType::SWAP, 2, true, true, 0),
    GateTypeInfo(GateType::NOT, 1, true, true, 0),
    GateTypeInfo(GateType::PAULIZ, 1, false, true, 0)};
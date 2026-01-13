#include <iostream>
#include <vector>
#include <string>
#include <array>

using namespace std;

enum GateType {
    HADAMARD,
    PHASE,
    SWAP,
    NOT,
    PAULIZ,
    RX,
    RY,
    RZ, // Wrong in OpenQASM Standard library.
    // As defined in the supplementrary material of the supremacy paper VII.E
    SX,
    SY,
    SW
};

GateType gate_type_from_string(const string& s) { //TODO: Confirm it's according to QASM 3.0
    if (s == "h" || s == "H") {
        return GateType::HADAMARD;
    } else if (s == "p" || s == "P" || s == "phase") {
        return GateType::PHASE;
    } else if (s == "swap" || s == "SWAP") {
        return GateType::SWAP;
    } else if (s == "x" || s == "X" || s == "not") {
        return GateType::NOT;
    } else if (s == "z" || s == "Z") {
        return GateType::PAULIZ;
    } else if (s == "rx" || s == "RX") {
        return GateType::RX;
    } else if (s == "ry" || s == "RY") {
        return GateType::RY;
    } else if (s == "rz" || s == "RZ") {
        return GateType::RZ;
    } else if (s == "sx" || s == "SX") {
        return GateType::SX;
    } else if (s == "sy" || s == "SY") {
        return GateType::SY;
    } else if (s == "sw" || s == "SW" || s == "hz_1_2") {
        return GateType::SW;
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
        case RX: return "RX";
        case RY: return "RY";
        case RZ: return "RZ";
        case SX: return "SX";
        case SY: return "SY";
        case SW: return "SW";
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
    GateTypeInfo(GateType t, int nt, bool b, bool d, int np)
        : type(t), num_targets(nt), breaks_internal_wire(b), deterministic(d), num_params(np) {}
};

//Must be defined in the same way as in the enum GateType (if we don't remove that one and use only this).
const array<GateTypeInfo,11> gate_type_infos = {
    GateTypeInfo(GateType::HADAMARD, 1, true, false, 0),
    GateTypeInfo(GateType::PHASE, 1, false, true, 1),
    GateTypeInfo(GateType::SWAP, 2, true, true, 0),
    GateTypeInfo(GateType::NOT, 1, true, true, 0),
    GateTypeInfo(GateType::PAULIZ, 1, false, true, 0),
    GateTypeInfo(GateType::RX, 1, true, false, 1),
    GateTypeInfo(GateType::RY, 1, true, false, 1),
    GateTypeInfo(GateType::RZ, 1, false, true, 1),
    GateTypeInfo(GateType::SX, 1, true, false, 0),
    GateTypeInfo(GateType::SY, 1, true, false, 0),
    GateTypeInfo(GateType::SW, 2, true, false, 0)
};
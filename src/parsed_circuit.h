#include "gate_types.h"
#include <fstream>
#include <sstream>
#include <string>
#include <vector>

// Stored on each wire it takes as argument.
struct ParsedGate {
  const int id; // ID from line in circuit file.
  const GateType type;
  const int num_controls; // The first num_controls arguments are controls, the
                          // rest are targets.
  const vector<int>
      args; // Of size type.num_targets + this.num_controls. wires[0] is the
            // argument to the first parameter etc.
  const int qparam; // The qubit parameter of which argument-wire this struct is
                    // stored.
  const vector<float>
      params; // The parameters, for example the angle of a phase.
  // Constructor
  ParsedGate(int i, GateType t, int nc, vector<int> a, int qp, vector<float> p)
      : id(i), type(t), num_controls(nc), args(a), qparam(qp), params(p) {}
};

string parsed_gate_to_string(const ParsedGate &pg) {
  string s = "ParsedGate(id=" + to_string(pg.id) +
             ", type=" + gate_type_to_string(pg.type) +
             ", num_controls=" + to_string(pg.num_controls) + ", args=[";
  for (size_t i = 0; i < pg.args.size(); i++) {
    s += to_string(pg.args[i]);
    if (i < pg.args.size() - 1)
      s += ", ";
  }
  s += "]";
  s += ", qparam=" + to_string(pg.qparam) + ", param=[";
  for (int i = 0; i < pg.params.size(); i++) {
    s += to_string(pg.params[i]);
  }
  s += "])";
  return s;
}

string wire_to_string(const vector<ParsedGate> &wire) {
  string s = "[";
  for (size_t i = 0; i < wire.size(); i++) {
    s += parsed_gate_to_string(wire[i]);
    if (i < wire.size() - 1)
      s += ", ";
  }
  s += "]";
  return s;
}

struct ParsedCircuit {
  static int n; // Number of qubits
  static int nr_gates;
  static vector<vector<ParsedGate>>
      wires; // wires[i] is the list of gates on qubit i, in order.

  // Parse circuit from QASM-file // Make constructor?
  static void parse_circuit(string filename) {

    ifstream file(filename);

    // String to store each line of the file.
    string line;

    // TODO: Maybe use a real parser instead. Or maybe none is very up to date.
    if (file.is_open()) {

      if (getline(file, line) &&
          line != "OPENQASM 3.0;") { // TODO: Check logic here...
        cerr << "Only OPENQASM 3.0 supported" << endl;
        exit(1);
      }

      if (getline(file, line) &&
          line != "include \"stdgates.inc\";") { // TODO: Fix support for
                                                 // standard library.
        cerr << "Only stdgates.inc supported" << endl;
        exit(1);
      }

      string qreg_name;
      size_t bracket_pos;
      size_t end_bracket_pos;
      getline(file, line);
      // Support for both qreg (qiskit) and qubit (v3). qreg is soon deprecated:
      // https://openqasm.com/language/types.html

      string stripped_line = line.substr(5); // Remove "qubit" or "qreg "
      bracket_pos = stripped_line.find('[');
      end_bracket_pos = stripped_line.find(']');
      if (bracket_pos == string::npos || end_bracket_pos == string::npos ||
          end_bracket_pos <= bracket_pos) {
        cerr << "Invalid qubit register declaration" << endl;
        exit(1);
      }
      if (line.substr(0, 5) == "qubit") {
        qreg_name = stripped_line.substr(
            end_bracket_pos + 2, stripped_line.size() - end_bracket_pos - 3);
      } else if (line.substr(0, 4) == "qreg") {
        qreg_name = stripped_line.substr(0, bracket_pos);
      } else {
        cerr << "Expected qubit or qreg keyword" << endl;
        exit(1);
      }

      n = stoi(stripped_line.substr(bracket_pos + 1,
                                    end_bracket_pos - bracket_pos - 1));
      n = ((n + 7) / 8) *
          8; // Round up to next byte for compatibility with I/O format.
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
          params_str =
              type_param_str.substr(left_par + 1, right_par - left_par - 1);
        } else {
          type_str = type_param_str;
          params_str = "";
        }

        int num_controls = 0;
        for (int i = 0; i < type_str.length(); i++) {
          if (type_str.at(i) == 'c') {
            num_controls++;
          } else {
            break;
          }
        }

        string basic_type_str = type_str.substr(num_controls);

        // TODO: Store parsed gate with a certain number of control bits and
        // with a basic target type.

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
          int qubit_index = stoi(
              qubit_str.substr(qubit_str.find('[') + 1,
                               qubit_str.find(']') - qubit_str.find('[') - 1));
          arg_indices.push_back(qubit_index);
        }

        for (int qparam = 0; qparam < arg_indices.size(); qparam++) {
          int arg_index = arg_indices[qparam];
          if (arg_index < 0 || arg_index >= n) {
            cerr << "Qubit index out of range" << endl;
            exit(1);
          }
          wires[arg_index].emplace_back(
              gate_index, gate_type_from_string(basic_type_str), num_controls,
              arg_indices, qparam, params);
        }
        gate_index++;
      }
      ParsedCircuit::nr_gates = gate_index;

      file.close();
    } else {
      cerr << "Unable to open circuit file!" << endl;
      exit(1);
    }

    //        for (size_t i = wires.size() - 1; i >= 0 && i < wires.size(); i--)
    //        {
    //            cout << "Wire " << i << ": " << wire_to_string(wires[i]) <<
    //            "\n";
    //        }

    return;
  }

  static string parsed_circuit_to_string() {
    string s = "ParsedCircuit(n=" + to_string(n) + ", wires=[\n";
    for (size_t i = 0; i < wires.size(); i++) {
      s += "  Wire " + to_string(i) + ": " + wire_to_string(wires[i]) + "\n";
    }
    s += "])";
    return s;
  }
};

int ParsedCircuit::n;
int ParsedCircuit::nr_gates;
vector<vector<ParsedGate>> ParsedCircuit::wires;
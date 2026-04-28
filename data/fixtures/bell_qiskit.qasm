OPENQASM 3.0;
include "stdgates.inc";
qreg q[2];
h q[0];
cx q[0],q[1];

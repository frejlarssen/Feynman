OPENQASM 3.0;
include "stdgates.inc";
qreg q[3];
h q[2];
x q[0];
ccz q[0],q[1],q[2];

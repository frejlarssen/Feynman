size = 1024 * 4 #nr qubytes

n = 8 * size #nr qubits

if (n < 1024):
    filename = f"ghz_n{n}.qasm"
else:
    filename = f"ghz_size{size}.qasm"

with open(filename, "w", encoding="utf-8") as f:
    f.write("OPENQASM 3.0;\n")
    f.write("include \"stdgates.inc\";\n")
    f.write(f"qreg q[{n}];\n")
    
    f.write(f"h q[0];\n")

    for i in range(n-1):
        f.write(f"cx q[{i}],q[{i+1}];\n")
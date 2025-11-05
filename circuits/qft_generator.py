import math
n=102

# Same convention as https://oreilly-qc.github.io/#
with open(f"qft_{n}.qasm", "w", encoding="utf-8") as f:
    f.write("OPENQASM 3.0;\n")
    f.write("include \"stdgates.inc\";\n")
    f.write(f"qreg q[{n}];\n")

    for group in range(n):
        f.write(f"h q[{n-1-group}];\n")
        for c in range (1, n-group):
            f.write(f"cp({-math.pi/(2**c)}) q[{n-1-group-c}],q[{n-1-group}];\n")

    for i in range(int(n/2)):
        f.write(f"swap q[{i}],q[{n-1-i}];\n")

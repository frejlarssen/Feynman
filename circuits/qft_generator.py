import math
n=16
with open(f"qft_{n}.qasm", "w", encoding="utf-8") as f:
    f.write("OPENQASM 3.0;\n")
    f.write("include \"stdgates.inc\";\n")
    f.write(f"qreg q[{n}];\n")

    for group in range(n):
        f.write(f"h q[{group}];\n")
        for c in range (1, n-group):
            f.write(f"cp({-math.pi/(2**c)}) q[{group + c}],q[{group}];\n")

    for i in range(int(n/2)):
        f.write(f"swap q[{i}],q[{n-1-i}];\n")

n = 8

with open(f"qrng_n{n}.qasm", "w", encoding="utf-8") as f:
    f.write("OPENQASM 3.0;\n")
    f.write("include \"stdgates.inc\";\n")
    f.write(f"qreg q[{n}];\n")

    for q in range(n):
        f.write(f"h q[{q}];\n")
n = 1024
# 1024 in ~3 sec with all ones as input.

with open(f"increment_n{n}.qasm", "w", encoding="utf-8") as f:
    f.write("OPENQASM 3.0;\n")
    f.write("include \"stdgates.inc\";\n")
    f.write(f"qreg q[{n}];\n")

    for i in range(n):
        gate = 'c' * (n-1-i) + 'x '

        for a in range(n-i):
            gate += f'q[{a}]'
            if a != n-i-1:
                gate += ','

        f.write(f"{gate};\n")
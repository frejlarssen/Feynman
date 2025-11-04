n = 4
it = 20
# n=4 and it=2 is fast. it=3 (23 internal wires) takes long time with breaking over deterministic gates.
# n=4 fast when joining over deterministic gates.

def cinc(n):
    for i in range(n-1):
        gate = 'c' * (n-i-1) + 'x '

        for a in range(0, n-i):
            gate += f'q[{a}]'
            if a != n-i-1:
                gate += ','

        f.write(f"{gate};\n")

def cdec(n):
    for i in range(1, n):
        gate = 'c' * (i) + 'x '

        for a in range(0, i+1):
            gate += f'q[{a}]'
            if a != i-1+1:
                gate += ','

        f.write(f"{gate};\n")

with open(f"qwalk_n{n}_it{it}.qasm", "w", encoding="utf-8") as f:
    f.write("OPENQASM 3.0;\n")
    f.write("include \"stdgates.inc\";\n")
    f.write(f"qreg q[{n}];\n")

    for i in range(it):
        # Coin flip
        f.write(f"h q[0];\n")
        cinc(n)
        f.write(f"x q[0];\n")
        cdec(n)
        f.write(f"x q[0];\n")
import math
n=2
it = 1
mark = 1

def aa(n, mark_list):
    # Mark
    for i in range(n):
        if mark_list[i] == 0:
            f.write(f"x q[{i}];\n")

    multi_c = 'c' * (n-1) + "z "
    for i in range (n):
        multi_c += f"q[{i}]"
        if i < n-1:
            multi_c += ","
    f.write(f"{multi_c};\n")

    for i in range(n):
        if mark_list[i] == 0:
            f.write(f"x q[{i}];\n")

    # Mirror
    for i in range(n):
        f.write(f"h q[{i}];\n")

    for i in range(n):
        f.write(f"x q[{i}];\n")

    f.write(f"{multi_c};\n")

    for i in range(n):
        f.write(f"x q[{i}];\n")

    for i in range(n):
        f.write(f"h q[{i}];\n")


mark_list = [int(b) for b in bin(mark)[2:].zfill(n)]
mark_list.reverse()

with open(f"aa_n{n}_it{it}_mark{mark}.qasm", "w", encoding="utf-8") as f:
    f.write("OPENQASM 3.0;\n")
    f.write("include \"stdgates.inc\";\n")
    f.write(f"qreg q[{n}];\n")

    # Prep
    for i in range(n):
        f.write(f"h q[{i}];\n")
    
    for a in range(it):
        aa(n, mark_list)


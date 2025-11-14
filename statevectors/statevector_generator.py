size = 1024 * 8 #Size of QC in qubytes


filename = f"ket0_size{size}.hsv"

nr_nibbles = size * 2

hex = "0" * nr_nibbles

with open(filename, "w", encoding="utf-8") as f:
    f.write(f"0x{hex}:1+0i\n")
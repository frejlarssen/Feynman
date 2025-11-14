nr_hexstrings = 10
size = 1024 * 2 #Size of QC in qubytes

start = 2**(size*8) - int(nr_hexstrings/2)
end =   int(nr_hexstrings/2) #Exclusive

if size < 10:
    filename = f"nrhex{nr_hexstrings}_size{size}_from{start:X}_to{end:X}.hs"
else:
    filename = f"nrhex{nr_hexstrings}_size{size}.hs"

nr_nibbles = size * 2

with open(filename, "w", encoding="utf-8") as f:
    f.write(f"{nr_hexstrings}\n")
    f.write(f"{size}\n")
    
    
    if start < end:
        for hex in range(start, end):
            f.write(f"0x{hex:0{nr_nibbles}X}\n")
    
    else:
        for hex in range(start, 2**(size * 8)):
            f.write(f"0x{hex:0{nr_nibbles}X}\n")
        
        for hex in range(0, end):
            f.write(f"0x{hex:0{nr_nibbles}X}\n")
size = 8 #Size of QC in qubytes

# Uncomment below the selected setting

def one_interval():
    # Symmetric around 0
    #nr_hexstrings = 10
    #start = 2**(size*8) - int(nr_hexstrings/2)
    #end =   int(nr_hexstrings/2) #Exclusive
    
    # All
    #nr_hexstrings = 2**(size*8)
    #start = 0
    #end = nr_hexstrings #Exclusive
    
    
    # Custom
    nr_hexstrings = 10
    start = 0
    end = nr_hexstrings
    
    
    if size < 10:
        filename = f"nrhex{nr_hexstrings}_size{size}_from0x{start:X}_to0x{end:X}.hs"
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


def two_intervals(interval1, interval2):
    nr_hexstrings = len(interval1) + len(interval2)

    if size < 2:
        filename = f"size{size}_from{interval1[0]}_to{interval1[-1]}_and_from{interval2[0]}_to{interval2[-1]}.hs"
    elif size < 10:
        filename = f"size{size}_from0x{interval1[0]:X}_to0x{interval1[-1]:X}_and_from0x{interval2[0]:X}_to0x{interval2[-1]:X}.hs"
    else:
        filename = f"size{size}.hs"
    
    nr_nibbles = size * 2
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"{nr_hexstrings}\n")
        f.write(f"{size}\n")

        for hex in interval1:
            f.write(f"0x{hex:0{nr_nibbles}X}\n")
        
        for hex in interval2:
            f.write(f"0x{hex:0{nr_nibbles}X}\n")




range2middle = int(2**(size*8) / 4) # For example: size=1QB = 8 qubit => N=256 => middle = 64

two_intervals(list(range(10)), list(range(range2middle - 5, range2middle + 5)))
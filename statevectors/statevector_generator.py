import numpy as np

size = 1 #Size of QC in qubytes


def ket0():
    filename = f"ket0_size{size}.hsv"
    
    nr_nibbles = size * 2
    
    hex = "0" * nr_nibbles
    
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"0x{hex}:1+0i\n")



def amplitude_encoded(f = 1, threshold=0.0):
    nr_nibbles = size * 2
    N = 2 ** (size*8)
    delta_theta = f * 2*np.pi / N
    filename = f"amplitude_signal_size{size}QB_f{f}_t{threshold}.hsv"
    with open(filename, "w", encoding="utf-8") as file:
        for i in range(N): #Infeasible for more than size = 3QB = 24qubit
            real_part = np.cos(i*delta_theta)
            if real_part > threshold or real_part < -threshold:
                file.write(f"0x{i:0{nr_nibbles}X}:{real_part}+0i\n")


def amplitude_encoded_v2(f = 1, threshold=0.0):
    nr_nibbles = size * 2
    N = 2 ** (size*8)
    delta_theta = f * 2*np.pi / N

    margin = -1
    for i in range(N):
        real_part = np.cos(i*delta_theta)
        if real_part < threshold:
            margin = i - 1
            break
    
    if margin < 0:
        print("Too small threshold to use margin version.")
        exit(1)
        
    print("margin: ", margin)

    filename = f"amplitude_signal_size{size}QB_f{f}_t{threshold}_v2.hsv"
    with open(filename, "w", encoding="utf-8") as file:
        #for i in range(N): #Infeasible for more than size = 3QB = 24qubit
        for half_period in range(2*f):
            middle = int(half_period * N/(2*f))
            
            print("real at middle: ", np.cos(middle*delta_theta))
            
            for i in range(max(middle - margin, 0), min(middle + margin + 1, N)):
                real_part = np.cos(i*delta_theta)
                file.write(f"0x{i:0{nr_nibbles}X}:{real_part}+0i\n")


# Takes a low frequency f1 and one high frequency f2
# f2_amp is relative amplitude of f2
# NB: Not normalized
def amplitude_encoded_2_freq(f1 = 1, f2 = 64, f2_amp = 0.2, margin=-1, threshold=0.0):
    nr_nibbles = size * 2
    N = 2 ** (size*8)
    delta_theta1 = f1 * 2*np.pi / N
    delta_theta2 = f2 * 2*np.pi / N

    if margin == -1:
        for i in range(N): #Margin is set based on low frequency f1
            real_part = np.cos(i*delta_theta1)
            if real_part < threshold:
                margin = i - 1
                break
        if margin < 0:
            print("Too small threshold to use this version.")
            exit(1)
            
        print("margin: ", margin)

        filename = f"amplitude_signal_size{size}QB_f{f1}_f{f2}_relamp{f2_amp}_t{threshold}.hsv"
    else:
        filename = f"amplitude_signal_size{size}QB_f{f1}_f{f2}_relamp{f2_amp}_m{margin}.hsv"

    with open(filename, "w", encoding="utf-8") as file:
        #for i in range(N): #Infeasible for more than size = 3QB = 24qubit
        for half_period in range(2*f1):
            middle = int(half_period * N/(2*f1))
            
            print("real at middle: ", np.cos(middle*delta_theta1))
            
            for i in range(max(middle - margin, 0), min(middle + margin + 1, N)):
                real_part = np.cos(i*delta_theta1) + f2_amp * np.cos(i*delta_theta2)
                file.write(f"0x{i:0{nr_nibbles}X}:{real_part}+0i\n")

ket0()

#amplitude_encoded_v2(6, 0.999999999999999)

#amplitude_encoded_2_freq(f1=6, f2=2**(size*8) / 4, f2_amp=0.2, threshold=0.999999999999999999999999999) # For example: 1QB = 8 qubits => N=256 => f2=64

#amplitude_encoded_2_freq(f1=6, f2=2**(size*8) / 4, f2_amp=0.2, margin=50) # For example: 1QB = 8 qubits => N=256 => f2=64
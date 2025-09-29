## Testing deep copy in `[join-deterministic a1d9dd4] Time measurements`
### Amplitude amplification
```
(base) frej@boko:~/code/qft/FeynQFT$ ./simulator -c ./circuits/aa_n3_it3_mark1.qasm -i 000 -o 000
Number of artificial sources: 18
Total core time deep_copy: 276.014 s
Total core time after deep_copy: 9.484e-06 s
Total clock time simulate: 37.3753 s
Total amplitude: 0.309358 + i0.000000
```

### Qwalk
```
(base) frej@boko:~/code/qft/FeynQFT$ ./simulator -c ./circuits/qwalk_n4_it10.qasm -i 0000 -o 0000
Number of artificial sources: 9
Total core time deep_copy: 1.53042 s
Total core time after deep_copy: 2.5516e-05 s
Total clock time simulate: 0.254952 s
Total amplitude: 0.500000 + i0.000000
```

```
(base) frej@boko:~/code/qft/FeynQFT$ ./simulator -c ./circuits/qwalk_n4_it15.qasm -i 0000 -o 0000
Number of artificial sources: 14
Total core time deep_copy: 68.9035 s
Total core time after deep_copy: 0 s
Total clock time simulate: 9.24208 s
Total amplitude: 0.000000 + i0.000000
```

### QFT
```
(base) frej@boko:~/code/qft/FeynQFT$ ./simulator -c ./circuits/qft_100.qasm -i 0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000 -o 0000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000
Number of artificial sources: 0
Total core time deep_copy: 0.0912172 s
Total core time after deep_copy: 0.000609737 s
Total clock time simulate: 0.0944181 s
Total amplitude: 0.000000 + i0.000000
```



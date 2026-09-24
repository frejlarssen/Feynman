# Formats

Hexadecimal output states `.hs`:

```text
num_hexstrings
size_in_bytes
...
hexstrings
...
```

Circuit format: subset of QASM with extensions (for example `ccccx` and
`fsim(theta,phi)`).
Circuit size is rounded up automatically to the closest multiple of 8.

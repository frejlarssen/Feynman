#!/usr/bin/env python
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# All generators
TASKS = [
    "circuits/qft_generator.py",
    "circuits/quantum_walk_generator.py",
    "circuits/qaoa_maxcut_generator.py",
    "circuits/ghz_generator.py",
    "circuits/increment_generator.py",
    "circuits/aa_iter_generator.py",
    "circuits/qrng_generator.py",
    "hexstrings/hexstring_set_generator.py",
    "statevectors/statevector_generator.py",
]


def main() -> int:
    # Run all
    for rel_script in TASKS:
        script_path = Path(__file__).resolve().parent / rel_script
        cmd = [sys.executable, str(script_path)]
        print(f"[bulk] {' '.join(cmd)}", flush=True)
        subprocess.run(cmd, check=True, cwd=ROOT)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# PauliPropagation comparison

This directory contains the Julia-side adapter for PauliPropagation comparison
runs. The repository's Python pipeline handles orchestration, comparison, and
plotting. Julia scripts run PauliPropagation and write artifacts consumed by
the Python pipeline.

Commands below assume they are run from the repository root.

First-time setup:

```bash
julia --project=pauli-comparison -e 'using Pkg; Pkg.instantiate()'
```

`Project.toml` declares the Julia dependencies. `Manifest.toml` records the
resolved package versions used for reproducible benchmark runs.

Smoke benchmark:

```bash
julia --project=pauli-comparison pauli-comparison/run_pauli_smoke.jl \
  --nqubits 32 \
  --pauli Z \
  --index 16 \
  --repeat 1000 \
  --output data/outputs/pauli-comparison/smoke.json
```

The JSON output contains metadata, resolved package versions, arguments,
timing, and a string form of the constructed observable.

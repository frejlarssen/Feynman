# Paper Configs

This directory contains configs that are tied directly to manuscript figures or
tables.

Rules:

- Paper config inputs must be generator-based (`circuit`, `input_statevector`,
  `output_bitstrings`) so a fresh clone can regenerate inputs.
- Keep run commands deterministic and clone-safe. Use explicit artifact paths
  only for plot/replot commands after a run has produced outputs.
- If a config changes scientific intent, create a new config instead of
  silently mutating a paper-bound one.
- Promotion is one-way: copy from exploratory to paper when frozen for paper
  use.

# Paper Experiments

This file tracks the subset of runs tied to manuscript figures/results in
`untracked/main.tex`.

Use explicit config paths and explicit artifact paths for paper reproducibility.
Avoid relying on `--latest` in paper scripts.

## Current Mapping

- QFT validation figure (`fig:qft_validation`)
  - Run:
    - `python scripts/run_pipeline.py validation qft-demo --config scripts/experiments/paper/validation/qft_demo.json`
  - Expected artifacts:
    - `summary.json`
    - `output_population.csv`
    - `demo_plot.pdf`

- Quantum walk artificial-source scaling (`fig:artificial_sources_time_qw`)
  - Run:
    - `python scripts/run_pipeline.py perf-sweep --config scripts/experiments/paper/perf/qwalk_iteration_checkpoint_sources.json`
  - Expected artifacts:
    - `summary.csv`
    - `qwalk_iteration_checkpoint_sources_ttot_vs_a_by_case.pdf`

- Checkpointing ablation figure (`fig:checkpointing_ablation`)
  - Run:
    - `python scripts/run_pipeline.py perf-sweep --config scripts/experiments/paper/perf/aa_checkpoint_ablation.json`
  - Expected artifacts:
    - `summary.csv`
    - `plot_total_full_s_vs_batch_size.pdf`
    - `plot_total_full_s_by_case.pdf`

- QAOA pruning figure (`fig:qaoa_pruning_sweep`)
  - Run:
    - `python scripts/run_pipeline.py qaoa-pruning --config scripts/experiments/paper/perf/qaoa_pruning_sweep_cycle_n8_p2.json`
  - Expected artifacts:
    - `summary.csv`
    - `summary_time_fidelity.pdf`

- Quantum walk tensor comparison figure
  - Run:
    - `python scripts/run_pipeline.py qwalk-quimb-sweep --config scripts/experiments/paper/perf/qwalk_quimb_qubit_sweep.json`
  - Expected artifacts:
    - `summary.csv`
    - `summary_by_n.csv`
    - `qwalk_quimb_time.pdf`
    - `qwalk_quimb_memory.pdf`
    - `qwalk_quimb_transpiled_ops.pdf`

## Suggested Workflow for New Paper Figures

1. Add or update a config in `scripts/experiments/paper/`.
2. Add one entry here with:
   - manuscript label
   - exact run command
   - exact artifact filenames
3. Generate figure assets into a dedicated external archive directory.
4. Reference those exported figure files from the paper source.

## Notes

- If a figure has multiple variants (for example parameter sweeps), list each
  config explicitly instead of encoding logic in prose.
- Keep this file short and strict: only paper-bound experiments belong here.

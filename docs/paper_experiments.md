# Paper Experiments

This file tracks the subset of runs tied to manuscript figures/results in
`untracked/main.tex`.

Use explicit config paths and explicit artifact paths for paper reproducibility.
Avoid relying on `--latest` in paper scripts.

## Resource Policy

Paper configs state the Feynman resource split explicitly. Feynman uses two
levels of parallelism: MPI distributes batches of requested output bitstrings,
while OpenMP parallelizes work inside each worker over artificial-source
histories in chunk 2 and over the final amplitude reduction.

The relevant MPI work count is therefore:

```text
number_of_batches = ceil(output_count / batch_size)
```

For the 32-hardware-thread paper runs, configs are chosen so that:

```text
ranks <= number_of_batches
ranks * OMP_NUM_THREADS = 32
```

The `batch_size` is chosen from the experiment's purpose. Experiments that
isolate one amplitude or intentionally avoid distributed-output effects use
one MPI rank and place the thread budget inside the worker. Experiments with
many requested outputs use MPI ranks only when there are enough output batches
to feed them.

The quimb comparison is treated as a single-node, shared-memory method
comparison rather than a Feynman distributed-output scaling result. There,
Feynman uses one MPI rank so that MPI scheduling over independent output
amplitudes is not mixed into the comparison with single-process quimb.

## Reference Environment

The final paper reruns used a module-based Linux environment with:

- GCC `13.2.0`
- Python `3.11.7`
- Open MPI `4.1.6`
- Python dependencies installed from `requirements.txt`

Equivalent setup:

```bash
module purge
module load gcc/13.2.0-gcc-12.2.0-a63szea
module load python/3.11.7-gcc-13.2.0-3zbbpkg
module load openmpi/4.1.6-gcc-13.2.0-4x5z7ie

python3 -m venv ~/feynman-venv
source ~/feynman-venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Build:

```bash
cmake -S . -B build-release -DCMAKE_BUILD_TYPE=Release
cmake --build build-release -j 4
```

Set the parent Python/quimb thread-pool environment before running paper
experiments:

```bash
export OMP_NUM_THREADS=32
export OPENBLAS_NUM_THREADS=32
export MKL_NUM_THREADS=32
export NUMEXPR_NUM_THREADS=32
```

Feynman subprocesses do not inherit this `OMP_NUM_THREADS=32` setting blindly:
each paper config sets `feynman_env.OMP_NUM_THREADS` explicitly according to the
resource split above. The global `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS`, and
`NUMEXPR_NUM_THREADS` settings are mainly relevant to Python/quimb runs.

## Current Mapping

- QFT validation figure (`fig:qft_validation`)
  - Run:
    - `python scripts/run_pipeline.py validation qft-demo --config scripts/experiments/paper/validation/qft_demo.json`
  - Expected artifacts:
    - `summary.json`
    - `output_population.csv`
    - `qft_demo.pdf`

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
    - `aa_checkpoint_ablation_ttot_vs_batch.pdf`
    - `aa_checkpoint_ablation_ttot_by_case.pdf`

- QAOA pruning figure (`fig:qaoa_pruning_sweep`)
  - Run:
    - `python scripts/run_pipeline.py qaoa-pruning --config scripts/experiments/paper/perf/qaoa_pruning_sweep_cycle_n8_p2.json`
  - Expected artifacts:
    - `summary.csv`
    - `qaoa_pruning_sweep_cycle_n8_p2.pdf`

- Quantum walk tensor comparison figure
  - Run:
    - `python scripts/run_pipeline.py qwalk-quimb-sweep --config scripts/experiments/paper/perf/qwalk_quimb_qubit_sweep.json`
  - Expected artifacts:
    - `summary.csv`
    - `summary_by_n.csv`
    - `qwalk_quimb_time.pdf`
    - `qwalk_quimb_memory.pdf`
    - `qwalk_quimb_transpiled_ops.pdf`

## Regenerate Plots From Saved Runs

After copying the paper run directories into `data/outputs/experiments/`,
regenerate all plots without rerunning any benchmark:

```bash
python scripts/regenerate_all_plots.py --dry-run
python scripts/regenerate_all_plots.py --fail-fast
```

Regenerate one experiment family by selecting any unique part of its saved
run-directory name:

```bash
python scripts/regenerate_all_plots.py --only qft_demo --fail-fast
python scripts/regenerate_all_plots.py --only checkpoint_ablation --fail-fast
python scripts/regenerate_all_plots.py --only qaoa_pruning --fail-fast
python scripts/regenerate_all_plots.py --only qwalk_iteration --fail-fast
python scripts/regenerate_all_plots.py --only qwalk_quimb --fail-fast
```

The dry run should list the five paper experiment families: checkpoint
ablation, QAOA pruning, quantum-walk artificial-source scaling, quantum-walk
quimb comparison, and QFT validation. Multi-case performance summaries may
also produce generic auxiliary plots alongside the paper-bound figure; these
are regenerated from the same saved `summary.csv` and do not rerun a benchmark.

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

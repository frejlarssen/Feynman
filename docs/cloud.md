# Cloud workflow

## Setup

### Cloud task

To build a simpler executable without MPI, for example to be used as a cloud task:

```bash
cmake --preset cloud
cmake --build --preset cloud --target cloud_task -j
```

Run for one batch:

```bash
mkdir -p data/outputs/tmp
./build-cloud/cloud_task.x \
  -c data/generated/circuits/qft/qft_n8_k2.qasm \
  -i data/generated/statevectors/ket0_size1.hsv \
  -b data/generated/hexstring_sets/nrhex10_size1_from0x0_to0xA.hs \
  -o data/outputs/tmp/qft_n8_k2_run_cloud.hsv \
  -t 0.0 -v 1
```

### Using docker

```bash
docker build --target simulate --tag feynman-simulate:latest .
```

```bash
docker run --mount type=bind,src=./data,dst=/data feynman-simulate:latest \
  -c data/generated/circuits/qft/qft_n8_k2.qasm \
  -i data/generated/statevectors/ket0_size1.hsv \
  -b data/generated/hexstring_sets/nrhex10_size1_from0x0_to0xA.hs \
  -o data/outputs/tmp/qft_n8_k2_run_docker.hsv \
  -t 0.0 -v 1
```

Build the helper images used by the Airflow pipeline:

```bash
docker build --target split --tag feynman-split:latest .
docker build --target concat --tag feynman-concat:latest .
```

### k3d

```bash
k3d cluster create feynman-cluster
kubectl apply -f storage.yaml
sh scripts/build_and_import_cloud_images.sh feynman-cluster
```

### Airflow

We use a seperate venv environment for running airflow:

```bash
source ~/venvs/airflow/bin/activate
```

When airflow is installed:

```bash
pip install apache-airflow-providers-cncf-kubernetes
sh scripts/prepare_airflow_local.sh
airflow standalone
```

Use `scripts/prepare_airflow_local.sh` when you want the full local sync: DAG
files plus the three task images imported into the `feynman-cluster` k3d node.

Be aware that the k3d node shares the host filesystem usage. On July 22, 2026
we observed kubelet image garbage collection removing unused `feynman-*` images
once node usage rose above the default 85% image-GC high threshold.

### After reboot

If the machine was powered off and you want to resume using the cloud workflow:

```bash
source ~/venvs/airflow/bin/activate
docker ps
k3d cluster list
k3d cluster start feynman-cluster
kubectl get pods
sh scripts/prepare_airflow_local.sh
airflow standalone
```

Notes:

- `docker ps` is just a quick sanity check that Docker is running.
- `k3d cluster start feynman-cluster` is for the common case where the cluster
  already exists and only needs to be resumed.
- `kubectl get pods` may print `No resources found in default namespace.` when no
  DAG run is active. That is expected: the DAG uses `on_finish_action="delete_pod"`
  for the task pods, so they disappear after the run completes.
- If the cluster no longer exists, recreate it with the `k3d cluster create ...`
  commands above, then rerun `sh scripts/prepare_airflow_local.sh`.

If you only changed DAG Python, use:

```bash
sh scripts/copy_dags.sh
```

Choose the `feynman` DAG and trigger it.

## Benchmark

For benchmarking a fixed problem at different pod counts, keep the circuit and
hexstring file fixed and vary the target pod count at trigger time. While running airflow standalone, trigger from another terminal:

```bash
airflow dags trigger feynman --conf '{"target_num_pods": 4}'
```

The split stage will derive an appropriate batch size from the input hexstring
count and emit approximately that many `simulate_batch` pods. You can also
override the batch size directly:

```bash
airflow dags trigger feynman --conf '{"max_hexstrings_per_batch": 125}'
```

The DAG uses one shared Airflow pool, `simulate_pool`, by default. All
stages belong to that pool, but the lightweight orchestration stages use one
slot each, and `simulate_batch` also uses one slot each by default. That gives
a clean way to overdecompose the run into many batches while still capping the
total concurrent work shown in the Gantt chart.

Before using the DAG with the default pool-based throttling, create the pool in
your Airflow environment:

```bash
source "$HOME/micromamba/bin/activate" airflow
sh scripts/setup_airflow_pool.sh simulate_pool 4
```

Or equivalently, run the Airflow CLI directly:

```bash
source "$HOME/micromamba/bin/activate" airflow
airflow pools set simulate_pool 4 "Limit concurrent simulate_batch Kubernetes pods"
airflow pools list | grep simulate_pool
```

If you want a different pool name or per-task slot cost, set these before
starting or refreshing Airflow:

```bash
export FEYNMAN_SHARED_POOL=simulate_pool
export FEYNMAN_LIGHT_TASK_POOL_SLOTS=1
export FEYNMAN_SIMULATE_TASK_POOL_SLOTS=1
```

Then copy the updated DAG into the local Airflow DAG directory:

```bash
sh scripts/copy_dags.sh
```

With that in place, a run can have, for example, about 12 batches total while
only 4 pooled tasks run concurrently.

To keep laptop runs safer by default, `simulate_batch` now runs with
`OMP_NUM_THREADS=1`. For config-driven runs, put the fixed thread count directly
in the benchmark JSON:

```json
{
  "experiment_name": "qwalk_n64_it4",
  "simulate_omp_num_threads": 2
}
```

Cloud benchmark configs may also set the simulator pruning threshold passed as
`-t` to `cloud_task.x`:

```json
{
  "experiment_name": "qwalk_n64_it4",
  "threshold": 1e-8
}
```

If omitted, the cloud workflow keeps the historical default of `0.0`.

Cloud benchmark configs may also set the chunk-2 sampling fraction passed as
`-f` to `cloud_task.x`:

```json
{
  "experiment_name": "qwalk_n64_it4",
  "fraction": 0.1
}
```

If omitted, the cloud workflow keeps the historical default of `1.0`.

You can still override it explicitly in `dag_run.conf` for ad hoc manual
triggers:

```bash
airflow dags trigger feynman --conf '{"simulate_omp_num_threads": 2}'
```

A simple benchmark sweep is available in:

`sh scripts/benchmark_cloud_pod_sweep.sh`

When `--config` is used, the script now looks for
`target_num_pods_list` and `repeat` in ordinary pod-sweep benchmark JSON, and
uses those pod counts and repeated runs by default.

If the config also sets `max_hexstrings_per_batch`, the sweep script switches
to fixed-batch mode for splitting. In that mode, use
`target_pool_slots_list` in the config to describe the intended shared-pool
concurrency labels. The actual DAG run is rendered with
`max_hexstrings_per_batch`; the pool-slot list is used only as the benchmark
label in `summary.csv`, plots, and helper wrappers. This is useful when you
want more total batches than the intended pool concurrency, for example a
single Gantt-chart run with about 12 batches scheduled onto a shared 4-slot
pool.

Example:

```json
{
  "experiment_name": "qwalk_n64_it4",
  "target_num_pods_list": [1, 2, 4],
  "repeat": 3
}
```

Example fixed-batch Gantt config:

```json
{
  "experiment_name": "qwalk_n64_it15_count1200_batch100_pool4",
  "target_pool_slots_list": [4],
  "max_hexstrings_per_batch": 100,
  "repeat": 1
}
```

This produces roughly 12 batches for 1200 requested output bitstrings, while a
shared Airflow pool of size 4 keeps only four pooled tasks active at once.

Explicit pod counts on the command line still override the JSON list:

`sh scripts/benchmark_cloud_pod_sweep.sh --config scripts/experiments/cloud/qwalk_pod_sweep.json 1 2`

You can also pass an explicit DAG id and pod counts:

`sh scripts/benchmark_cloud_pod_sweep.sh feynman 1 2 4 8`

Cloud benchmark configs live under `scripts/experiments/cloud/` and reuse the
same high-level sections as the non-cloud configs: `circuit`,
`input_statevector`, and `output_bitstrings`.

Example with the quantum-walk benchmark case:

`sh scripts/benchmark_cloud_pod_sweep.sh --config scripts/experiments/cloud/qwalk_pod_sweep.json`

For the single-run Gantt demo:

`sh scripts/benchmark_cloud_pod_sweep.sh --config scripts/experiments/cloud/qwalk_gantt_pool4_batch100.json`

For fixed-batch configs where `target_pool_slots_list` is meant to act as a
shared-pool slot sweep, use:

`sh scripts/benchmark_cloud_fixed_batch_pool_sweep.sh --config scripts/experiments/cloud/qwalk_pod_sweep_opencube.json`

This wrapper updates the Airflow pool size before each labeled run, then calls
`benchmark_cloud_pod_sweep.sh` one label at a time while keeping a single
benchmark output directory.

For longer local runs, consider launching the sweep inside `tmux` so a
terminal-window close does not kill the local polling script.

The script runs pod counts sequentially, repeats each pod count according to the
config's `repeat` value, waits for each DAG run to finish, and prints the
wall-clock time per run. By default it saves a timestamped summary CSV under
`data/outputs/cloud_benchmarks/<timestamp>_<experiment_name>/summary.csv`.

If that directory exists with the wrong owner or mode, fix it before running
the benchmark:

```bash
sudo mkdir -p data/outputs/cloud_benchmarks
sudo chown -R "$USER:$USER" data/outputs/cloud_benchmarks
chmod u+rwx data/outputs/cloud_benchmarks
```

If you prefer not to change the default directory, point the script elsewhere:

```bash
RESULTS_FILE=data/outputs/somewhere_else/summary.csv \
  sh scripts/benchmark_cloud_pod_sweep.sh --config scripts/experiments/cloud/qwalk_pod_sweep.json
```

The benchmark output now follows the repo's experiment-artifact pattern more
closely. By default it creates a directory named
`data/outputs/cloud_benchmarks/<timestamp>_<experiment_name>/` with:

- `summary.csv`
- `benchmark_metadata.json` with git/provenance context
- `git_diff_airflow_scripts_docs.patch`
- one run directory per Airflow run under `runs/<run_id>/`
- the raw simulator batch outputs and merged `.hsv` output for that run stored directly inside `runs/<run_id>/`
- per-benchmark per-bitstring timing histograms from `timeBitstrings.tm`
- per-run `task_states.json`, normalized `task_instances.json`, task/log summaries, and single-run Gantt PDFs
- a sweep-level `gantt_multiexec.pdf`
- the usual cloud benchmark PDFs from `plot_cloud_benchmark.py`

The sweep script captures `task_states.json` from the local Airflow CLI after
each run finishes, then renders the archive/Gantt artifacts from that file.
That keeps benchmark archiving independent of Airflow REST API credentials.
For config-driven sweeps, this also avoids creating a second top-level
`data/outputs/cloud_benchmarks/<experiment_name>/` runtime-output tree.

Each summary row now includes both:

- `repeat_index`: which repeated run this was for the given pod count
- `elapsed_seconds`: full DAG wall-clock time
- `simulate_stage_elapsed_seconds`: the span from the first `simulate_batch`
  task instance start to the last `simulate_batch` task instance end
- `simulate_task_instance_seconds_sum`: the sum of all finished
  `simulate_batch` task-instance durations
- `simulate_autotuning_seconds_*`: autotuning totals/means/maxima extracted from
  the worker logs
- `simulate_worker_simulate_calls_seconds_*`: pure `simulate(...)` totals/means/maxima
  extracted from `Total clocktime for all simulate calls: ...`
- `simulate_worker_full_seconds_*`: full worker totals/means/maxima extracted
  from `Total clocktime (including I/O) for sv.cpp: ...`

That makes it easier to separate orchestration overhead from actual parallel
simulation work.

When `--config` is used, the sweep script renders the Airflow `dag_run.conf`
with the repo's `feynman` development Python by default
(`~/micromamba/envs/feynman/bin/python`). That keeps the Airflow venv lean while
still letting benchmark configs reuse the normal generator/materialization stack.
Override with `CONFIG_RENDER_PYTHON=...` if needed.

While a `simulate_batch` pod is running, its logs now emit periodic heartbeat
lines of the form `processed X / Y output bitstrings ...` at normal verbosity.
Use `kubectl logs -f <simulate-pod-name>` if you want to watch long-running
cloud tasks make progress.

Before triggering anything, it checks that `feynman-simulate`, `feynman-split`,
and `feynman-concat` are present inside the `feynman-cluster` k3d node. If any
are missing, it fails loudly and tells you to rerun:

`sh scripts/build_and_import_cloud_images.sh feynman-cluster`

It warns once node usage reaches 80%, because that is the “start paying
attention” level for this setup.

It also fails loudly if the k3d node root filesystem is already at or above the
default kubelet image-GC high threshold (85%), because in that state kubelet may
garbage-collect unused task images out from under the benchmark.

You can override the destination if you want:

`RESULTS_FILE=data/outputs/cloud_benchmark_results.csv sh scripts/benchmark_cloud_pod_sweep.sh`

If you need to abort a running benchmark:

- Press `Ctrl-C` in the terminal running `sh scripts/benchmark_cloud_pod_sweep.sh`
  to stop the local polling script.
- That does not stop the already-triggered Airflow DAG run.
- To stop the actual running cloud task, find the pod and delete it:

```bash
kubectl get pods
kubectl delete pod <simulate-pod-name>
```

- Deleting the running `simulate_batch` pod should fail that task and therefore
  fail the DAG run.

After the sweep, switch back to the `feynman` development environment and plot:

```bash
python scripts/plot_cloud_benchmark.py \
  --summary-csv data/outputs/cloud_benchmarks/<timestamp>_<experiment_name>/summary.csv
```

To plot the parallel compute stage instead of the full DAG wall-clock time:

```bash
python scripts/plot_cloud_benchmark.py \
  --summary-csv data/outputs/cloud_benchmarks/<timestamp>_<experiment_name>/summary.csv \
  --metric simulate_stage_elapsed_seconds
```

The plot now also overlays a strong-scaling efficiency line by default. It uses
the smallest plotted pod count as the baseline, so efficiency is computed as:

`efficiency(p) = 100 * T_base * pods_base / (T_p * p)`

Disable it with:

```bash
python scripts/plot_cloud_benchmark.py \
  --summary-csv data/outputs/cloud_benchmarks/<timestamp>_<experiment_name>/summary.csv \
  --no-efficiency
```

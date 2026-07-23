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
bash scripts/build_and_import_cloud_images.sh feynman-cluster
```

### Airflow

We use a seperate venv environment for running airflow:

```bash
source ~/venvs/airflow/bin/activate
```

When airflow is installed:

```bash
pip install apache-airflow-providers-cncf-kubernetes
bash scripts/prepare_airflow_local.sh
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
bash scripts/prepare_airflow_local.sh
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
  commands above, then rerun `bash scripts/prepare_airflow_local.sh`.

If you only changed DAG Python, use:

```bash
bash scripts/copy_dags.sh
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

To keep laptop runs safer by default, `simulate_batch` now runs with
`OMP_NUM_THREADS=1` unless you override it explicitly in `dag_run.conf`:

```bash
airflow dags trigger feynman --conf '{"simulate_omp_num_threads": 2}'
```

A simple benchmark sweep is available in:

`bash scripts/benchmark_cloud_pod_sweep.sh`

You can also pass an explicit DAG id and pod counts:

`bash scripts/benchmark_cloud_pod_sweep.sh feynman 1 2 4 8`

Cloud benchmark configs live under `scripts/experiments/cloud/` and reuse the
same high-level sections as the non-cloud configs: `circuit`,
`input_statevector`, and `output_bitstrings`.

Example with the quantum-walk benchmark case:

`bash scripts/benchmark_cloud_pod_sweep.sh --config scripts/experiments/cloud/qwalk_pod_sweep.json`

The script runs pod counts sequentially, waits for each DAG run to finish, and
prints the wall-clock time per run. By default it saves a timestamped summary
CSV under `untracked/cloud_benchmarks/<timestamp>/summary.csv`.

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

`bash scripts/build_and_import_cloud_images.sh feynman-cluster`

It warns once node usage reaches 80%, because that is the “start paying
attention” level for this setup.

It also fails loudly if the k3d node root filesystem is already at or above the
default kubelet image-GC high threshold (85%), because in that state kubelet may
garbage-collect unused task images out from under the benchmark.

You can override the destination if you want:

`RESULTS_FILE=untracked/cloud_benchmark_results.csv bash scripts/benchmark_cloud_pod_sweep.sh`

If you need to abort a running benchmark:

- Press `Ctrl-C` in the terminal running `bash scripts/benchmark_cloud_pod_sweep.sh`
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
  --summary-csv untracked/cloud_benchmarks/<timestamp>/summary.csv
```

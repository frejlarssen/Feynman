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

When airflow is installed:

```bash
pip install apache-airflow-providers-cncf-kubernetes
bash scripts/prepare_airflow_local.sh
airflow standalone
```

Use `scripts/prepare_airflow_local.sh` when you want the full local sync: DAG
files plus the three task images imported into the `feynman-cluster` k3d node.

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

A simple benchmark sweep is available in:

`bash scripts/benchmark_cloud_pod_sweep.sh`

You can also pass an explicit DAG id and pod counts:

`bash scripts/benchmark_cloud_pod_sweep.sh feynman 1 2 4 8`

The script runs pod counts sequentially, waits for each DAG run to finish, and
prints the wall-clock time per run. To also save CSV results:

`RESULTS_FILE=untracked/cloud_benchmark_results.csv bash scripts/benchmark_cloud_pod_sweep.sh`

# Cloud workflow

## Setup

### Cloud task

To build a simpler executable without MPI, for example to be used as a cloud task:

```bash
cmake --preset cloud
cmake --build --preset cloud --target cloud_task -j
```

Use the preset `cloud-make` instead on systems without Ninja.

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

For larger cloud pool sweeps, raise Airflow's global scheduler parallelism
before starting Airflow, for example:

```bash
export AIRFLOW__CORE__PARALLELISM=512
airflow config get-value core parallelism
```

If a fixed-batch benchmark maps many `simulate_batch` tasks, also raise
Airflow's dynamic-task mapping limit before starting Airflow, for example:

```bash
export AIRFLOW__CORE__MAX_MAP_LENGTH=4096
airflow config get-value core max_map_length
```

Use `scripts/prepare_airflow_local.sh` when you want the full local sync: DAG
files plus the three task images imported into the `feynman-cluster` k3d node.

Be aware that the k3d node shares the host filesystem usage. Kubelet may remove
unused `feynman-*` images once node usage rises above the default 85%
image-GC high threshold.

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

The cloud benchmark workflow lives in [cloud_benchmarks.md](./cloud_benchmarks.md).

Use that doc for:

- manual `airflow dags trigger` examples
- `benchmark_cloud_runner.sh` and `benchmark_cloud_pool_sweep.sh`
- benchmark config fields such as `target_num_batches_list` and `target_pool_slots_list`
- output layout, plotting, and benchmark artifact details

The short version is:

- use `target_num_batches` for manual split-count triggers
- use `max_hexstrings_per_batch` for fixed-size batch splitting
- use `benchmark_cloud_runner.sh` for batch sweeps
- use `benchmark_cloud_pool_sweep.sh` for fixed-batch shared-pool sweeps
- use `benchmark_cloud_autoscale.sh` for a target-time adaptive pool run

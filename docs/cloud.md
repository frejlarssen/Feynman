## Cloud task

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

If you only changed DAG Python, use:

```bash
bash scripts/copy_dags.sh
```

Choose the `feynman` DAG and trigger it.

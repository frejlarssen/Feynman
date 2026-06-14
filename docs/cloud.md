## Cloud task

To build a simpler executable without MPI, for example to be used as a cloud task:

```bash
cmake --preset release
cmake --build --preset release --target cloud_task -j
```

Run for one batch:

```bash
mkdir -p data/outputs/tmp
./build-release/cloud_task.x \
  -c data/generated/circuits/qft/qft_n8_k2.qasm \
  -i data/generated/statevectors/ket0_size1.hsv \
  -b data/generated/hexstring_sets/nrhex10_size1_from0x0_to0xA.hs \
  -o data/outputs/tmp/qft_n8_k2_run_cloud.hsv \
  -t 0.0 -v 1
```

### Using docker

```bash
docker build --tag feynman:latest .
```

```bash
docker run --mount type=bind,src=./data,dst=/data feynman:latest /cloud_task.x \
  -c data/generated/circuits/qft/qft_n8_k2.qasm \
  -i data/generated/statevectors/ket0_size1.hsv \
  -b data/generated/hexstring_sets/nrhex10_size1_from0x0_to0xA.hs \
  -o data/outputs/tmp/qft_n8_k2_run_docker.hsv \
  -t 0.0 -v 1
```

### k3d

```bash
k3d cluster create feynman-cluster --volume "$PWD/data:/data@all"
k3d image import feynman:latest -c feynman-cluster
kubectl apply -f job.yaml
```

### Airflow

When airflow is installed:

```bash
pip install apache-airflow-providers-cncf-kubernetes
bash copy_dags.sh
airflow standalone
```

Choose the `feynman_dag` and trigger it.
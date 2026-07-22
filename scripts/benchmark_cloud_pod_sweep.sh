#!/bin/sh

set -eu

DAG_ID="${1:-feynman}"
shift || true
POLL_SECONDS="${POLL_SECONDS:-5}"
K3D_CLUSTER_NAME="${K3D_CLUSTER_NAME:-feynman-cluster}"
K3D_NODE_NAME="${K3D_NODE_NAME:-k3d-${K3D_CLUSTER_NAME}-server-0}"
BENCHMARK_STAMP="${BENCHMARK_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
BENCHMARK_DIR="${BENCHMARK_DIR:-untracked/cloud_benchmarks/${BENCHMARK_STAMP}}"
RESULTS_FILE="${RESULTS_FILE:-${BENCHMARK_DIR}/summary.csv}"

if [ "$#" -eq 0 ]; then
  POD_COUNTS="1 2 4 8"
else
  POD_COUNTS="$*"
fi

RESULTS_DIR=$(dirname "${RESULTS_FILE}")
mkdir -p "${RESULTS_DIR}"

if [ ! -f "${RESULTS_FILE}" ]; then
  printf "dag_id,run_id,target_num_pods,state,elapsed_seconds,start_utc,end_utc\n" > "${RESULTS_FILE}"
fi

require_cluster_image() {
  image_name="$1"
  if ! docker exec "${K3D_NODE_NAME}" crictl images 2>/dev/null | grep -q "docker.io/library/${image_name}[[:space:]]"; then
    echo "Missing required image in k3d node ${K3D_NODE_NAME}: docker.io/library/${image_name}:latest" >&2
    echo "Refusing to run benchmark with a half-prepared cluster." >&2
    echo "Re-import the cloud images first:" >&2
    echo "  bash scripts/build_and_import_cloud_images.sh ${K3D_CLUSTER_NAME}" >&2
    exit 1
  fi
}

echo "Preflight: checking required images inside ${K3D_NODE_NAME}..."
require_cluster_image "feynman-simulate"
require_cluster_image "feynman-split"
require_cluster_image "feynman-concat"

echo "Benchmark results will be written to ${RESULTS_FILE}"

for pods in $POD_COUNTS
do
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  run_id="benchmark_pods_${pods}_${timestamp}"
  start_epoch="$(date +%s)"
  start_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

  echo "Triggering ${DAG_ID} with target_num_pods=${pods} (run_id=${run_id})..."
  airflow dags trigger "${DAG_ID}" \
    --run-id "${run_id}" \
    --conf "{\"target_num_pods\": ${pods}}"

  while true
  do
    state_raw="$(airflow dags state "${DAG_ID}" "${run_id}" 2>/dev/null | tail -n 1 | tr -d '[:space:]')"
    state="${state_raw%%,*}"
    case "${state}" in
      success|failed|canceled)
        end_epoch="$(date +%s)"
        end_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
        elapsed_seconds=$((end_epoch - start_epoch))
        echo "Run ${run_id} finished with state=${state} in ${elapsed_seconds}s."
        printf "%s,%s,%s,%s,%s,%s,%s\n" \
          "${DAG_ID}" "${run_id}" "${pods}" "${state}" "${elapsed_seconds}" "${start_utc}" "${end_utc}" \
          >> "${RESULTS_FILE}"
        if [ "${state}" != "success" ]; then
          echo "Task states for failed run ${run_id}:"
          airflow tasks states-for-dag-run "${DAG_ID}" "${run_id}" || true
          exit 1
        fi
        break
        ;;
      *)
        echo "Run ${run_id} state=${state_raw}; sleeping ${POLL_SECONDS}s..."
        sleep "${POLL_SECONDS}"
        ;;
    esac
  done
done

echo "Benchmark summary saved to ${RESULTS_FILE}"

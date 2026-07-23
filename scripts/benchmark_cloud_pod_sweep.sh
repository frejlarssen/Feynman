#!/bin/sh

set -eu

DAG_ID="feynman"
CONFIG_PATH=""
while [ "$#" -gt 0 ]
do
  case "$1" in
    --config)
      CONFIG_PATH="$2"
      shift 2
      ;;
    --dag-id)
      DAG_ID="$2"
      shift 2
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      break
      ;;
  esac
done

if [ "$#" -gt 0 ]; then
  DAG_ID="$1"
  shift || true
fi

POLL_SECONDS="${POLL_SECONDS:-5}"
K3D_CLUSTER_NAME="${K3D_CLUSTER_NAME:-feynman-cluster}"
K3D_NODE_NAME="${K3D_NODE_NAME:-k3d-${K3D_CLUSTER_NAME}-server-0}"
K3D_NODE_WARNING_THRESHOLD_PERCENT="${K3D_NODE_WARNING_THRESHOLD_PERCENT:-80}"
K3D_NODE_IMAGE_GC_HIGH_THRESHOLD_PERCENT="${K3D_NODE_IMAGE_GC_HIGH_THRESHOLD_PERCENT:-85}"
CONFIG_RENDER_PYTHON="${CONFIG_RENDER_PYTHON:-}"
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
  printf "dag_id,experiment_name,run_id,target_num_pods,state,elapsed_seconds,start_utc,end_utc\n" > "${RESULTS_FILE}"
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

node_root_usage_percent() {
  docker exec "${K3D_NODE_NAME}" sh -lc "df -P / | awk 'NR==2 {gsub(/%/, \"\", \$5); print \$5}'"
}

default_config_render_python() {
  if [ -n "${CONFIG_RENDER_PYTHON}" ]; then
    printf "%s\n" "${CONFIG_RENDER_PYTHON}"
    return 0
  fi

  if [ -x "/home/frej/micromamba/envs/feynman/bin/python" ]; then
    printf "%s\n" "/home/frej/micromamba/envs/feynman/bin/python"
    return 0
  fi

  command -v python3
}

usage_percent="$(node_root_usage_percent)"
if [ "${usage_percent}" -ge "${K3D_NODE_WARNING_THRESHOLD_PERCENT}" ]; then
  echo "WARNING: k3d node ${K3D_NODE_NAME} root filesystem is at ${usage_percent}%." >&2
  echo "This is above the recommended warning threshold of ${K3D_NODE_WARNING_THRESHOLD_PERCENT}%." >&2
  echo "Benchmark stability may degrade as kubelet approaches image garbage collection." >&2
fi

if [ "${usage_percent}" -ge "${K3D_NODE_IMAGE_GC_HIGH_THRESHOLD_PERCENT}" ]; then
  echo "k3d node ${K3D_NODE_NAME} root filesystem is at ${usage_percent}%." >&2
  echo "This is above the kubelet image-GC high threshold of ${K3D_NODE_IMAGE_GC_HIGH_THRESHOLD_PERCENT}%." >&2
  echo "Unused task images may be garbage-collected during or before the benchmark." >&2
  echo "Free disk space before benchmarking, then re-import the cloud images:" >&2
  echo "  bash scripts/build_and_import_cloud_images.sh ${K3D_CLUSTER_NAME}" >&2
  exit 1
fi

echo "Preflight: checking required images inside ${K3D_NODE_NAME}..."
require_cluster_image "feynman-simulate"
require_cluster_image "feynman-split"
require_cluster_image "feynman-concat"

if [ -n "${CONFIG_PATH}" ]; then
  CONFIG_RENDER_PYTHON="$(default_config_render_python)"
  if [ ! -x "${CONFIG_RENDER_PYTHON}" ]; then
    echo "Could not find a usable Python interpreter for config rendering: ${CONFIG_RENDER_PYTHON}" >&2
    echo "Set CONFIG_RENDER_PYTHON to the Python from your feynman environment." >&2
    exit 1
  fi
  if ! "${CONFIG_RENDER_PYTHON}" scripts/render_cloud_benchmark_conf.py --help >/dev/null 2>&1; then
    echo "Config rendering requires the repo's development Python environment." >&2
    echo "Tried: ${CONFIG_RENDER_PYTHON}" >&2
    echo "If needed, rerun with:" >&2
    echo "  CONFIG_RENDER_PYTHON=/home/frej/micromamba/envs/feynman/bin/python bash scripts/benchmark_cloud_pod_sweep.sh --config ${CONFIG_PATH}" >&2
    exit 1
  fi
  echo "Using config-render Python: ${CONFIG_RENDER_PYTHON}"
fi

echo "Benchmark results will be written to ${RESULTS_FILE}"

for pods in $POD_COUNTS
do
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  run_id="benchmark_pods_${pods}_${timestamp}"
  start_epoch="$(date +%s)"
  start_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  conf_json="{\"target_num_pods\": ${pods}}"
  experiment_name="qft_n8_k2"
  if [ -n "${CONFIG_PATH}" ]; then
    conf_json="$("${CONFIG_RENDER_PYTHON}" scripts/render_cloud_benchmark_conf.py --config "${CONFIG_PATH}" --target-num-pods "${pods}")"
    experiment_name="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("benchmark_case", {}).get("experiment_name", "unknown"))' "${conf_json}")"
  fi

  echo "Triggering ${DAG_ID} with target_num_pods=${pods} (run_id=${run_id})..."
  airflow dags trigger "${DAG_ID}" \
    --run-id "${run_id}" \
    --conf "${conf_json}"

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
        printf "%s,%s,%s,%s,%s,%s,%s,%s\n" \
          "${DAG_ID}" "${experiment_name}" "${run_id}" "${pods}" "${state}" "${elapsed_seconds}" "${start_utc}" "${end_utc}" \
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

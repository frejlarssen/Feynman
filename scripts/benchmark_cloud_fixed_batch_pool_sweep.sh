#!/bin/sh

set -eu

DAG_ID="feynman"
CONFIG_PATH=""
POOL_NAME="${FEYNMAN_SHARED_POOL:-simulate_pool}"

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
    --pool-name)
      POOL_NAME="$2"
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

if [ -z "${CONFIG_PATH}" ]; then
  echo "Usage: bash scripts/benchmark_cloud_fixed_batch_pool_sweep.sh --config <path> [--dag-id feynman] [--pool-name simulate_pool] [pool_size ...]" >&2
  exit 1
fi

default_helper_python() {
  if [ -n "${HELPER_PYTHON:-}" ]; then
    printf "%s\n" "${HELPER_PYTHON}"
    return 0
  fi

  if [ -n "${CONFIG_RENDER_PYTHON:-}" ]; then
    printf "%s\n" "${CONFIG_RENDER_PYTHON}"
    return 0
  fi

  if [ -x "/home/frej/micromamba/envs/feynman/bin/python" ]; then
    printf "%s\n" "/home/frej/micromamba/envs/feynman/bin/python"
    return 0
  fi

  command -v python3
}

HELPER_PYTHON="$(default_helper_python)"

if ! "${HELPER_PYTHON}" scripts/render_cloud_benchmark_conf.py --help >/dev/null 2>&1; then
  echo "Config rendering requires the repo's development Python environment." >&2
  echo "Tried: ${HELPER_PYTHON}" >&2
  exit 1
fi

CONFIG_EXPERIMENT_NAME="$("${HELPER_PYTHON}" -c 'import json,sys; from pathlib import Path; print(json.load(open(sys.argv[1], encoding="utf-8")).get("experiment_name", Path(sys.argv[1]).stem or "qft_n8_k2"))' "${CONFIG_PATH}")"
CONFIG_MAX_HEXSTRINGS_PER_BATCH="$("${HELPER_PYTHON}" scripts/render_cloud_benchmark_conf.py --config "${CONFIG_PATH}" --print-max-hexstrings-per-batch)"
if [ -z "${CONFIG_MAX_HEXSTRINGS_PER_BATCH}" ]; then
  echo "This wrapper is only for fixed-batch configs with max_hexstrings_per_batch set." >&2
  exit 1
fi

if [ "$#" -eq 0 ]; then
  POOL_SLOTS_LIST="$("${HELPER_PYTHON}" scripts/render_cloud_benchmark_conf.py --config "${CONFIG_PATH}" --print-target-pool-slots-list)"
else
  POOL_SLOTS_LIST="$*"
fi

if [ -z "${POOL_SLOTS_LIST}" ]; then
  echo "No pool-slot values provided and config did not define target_pool_slots_list." >&2
  exit 1
fi

BENCHMARK_STAMP="${BENCHMARK_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
BENCHMARK_DIR="${BENCHMARK_DIR:-data/outputs/cloud_benchmarks/${BENCHMARK_STAMP}_${CONFIG_EXPERIMENT_NAME}}"
RESULTS_FILE="${RESULTS_FILE:-${BENCHMARK_DIR}/summary.csv}"

mkdir -p "${BENCHMARK_DIR}"

echo "Fixed-batch pool sweep"
echo "  config: ${CONFIG_PATH}"
echo "  dag_id: ${DAG_ID}"
echo "  pool_name: ${POOL_NAME}"
echo "  benchmark_dir: ${BENCHMARK_DIR}"
echo "  results_file: ${RESULTS_FILE}"
echo "  pool slots: ${POOL_SLOTS_LIST}"
echo "  max_hexstrings_per_batch: ${CONFIG_MAX_HEXSTRINGS_PER_BATCH}"

for slots in ${POOL_SLOTS_LIST}
do
  echo "Setting Airflow pool ${POOL_NAME} to ${slots} slots..."
  bash scripts/setup_airflow_pool.sh "${POOL_NAME}" "${slots}" \
    "Limit concurrent simulate_batch Kubernetes pods during fixed-batch pool sweep"

  BENCHMARK_STAMP="${BENCHMARK_STAMP}" \
  BENCHMARK_DIR="${BENCHMARK_DIR}" \
  RESULTS_FILE="${RESULTS_FILE}" \
  HELPER_PYTHON="${HELPER_PYTHON}" \
  CONFIG_RENDER_PYTHON="${HELPER_PYTHON}" \
  bash scripts/benchmark_cloud_pod_sweep.sh \
    --config "${CONFIG_PATH}" \
    --dag-id "${DAG_ID}" \
    "${slots}"
done

"${HELPER_PYTHON}" scripts/write_cloud_benchmark_metadata.py \
  --benchmark-dir "${BENCHMARK_DIR}" \
  --dag-id "${DAG_ID}" \
  --config "${CONFIG_PATH}" \
  --experiment-name "${CONFIG_EXPERIMENT_NAME}" \
  --label-kind "pool_slots" \
  --label-values ${POOL_SLOTS_LIST} \
  --runner-script "scripts/benchmark_cloud_fixed_batch_pool_sweep.sh" \
  --notes "Fixed-batch benchmark sweep. Airflow pool ${POOL_NAME} was resized before each labeled run; summary rows use label_kind=pool_slots." \
  --invocation "bash scripts/benchmark_cloud_fixed_batch_pool_sweep.sh --config ${CONFIG_PATH} --dag-id ${DAG_ID} --pool-name ${POOL_NAME} ${POOL_SLOTS_LIST}" \
  >/dev/null

echo "Pool sweep complete. Results in ${RESULTS_FILE}"

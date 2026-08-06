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
HELPER_PYTHON="${HELPER_PYTHON:-}"
BENCHMARK_STAMP="${BENCHMARK_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
BENCHMARK_DIR="${BENCHMARK_DIR:-}"
RESULTS_FILE="${RESULTS_FILE:-}"
CONFIG_EXPERIMENT_NAME="qft_n8_k2"
REPEAT_COUNT=1

if [ "$#" -eq 0 ]; then
  POD_COUNTS="1 2 4 8"
else
  POD_COUNTS="$*"
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
  if [ -n "${HELPER_PYTHON}" ]; then
    printf "%s\n" "${HELPER_PYTHON}"
    return 0
  fi

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

HELPER_PYTHON="$(default_config_render_python)"

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
  CONFIG_RENDER_PYTHON="${HELPER_PYTHON}"
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
  CONFIG_EXPERIMENT_NAME="$("${CONFIG_RENDER_PYTHON}" -c 'import json,sys; from pathlib import Path; print(json.load(open(sys.argv[1], encoding="utf-8")).get("experiment_name", Path(sys.argv[1]).stem or "qft_n8_k2"))' "${CONFIG_PATH}")"
  REPEAT_COUNT="$("${CONFIG_RENDER_PYTHON}" scripts/render_cloud_benchmark_conf.py --config "${CONFIG_PATH}" --print-repeat-count)"
  if [ "$#" -eq 0 ]; then
    CONFIG_POD_COUNTS="$("${CONFIG_RENDER_PYTHON}" scripts/render_cloud_benchmark_conf.py --config "${CONFIG_PATH}" --print-target-num-pods-list)"
    if [ -n "${CONFIG_POD_COUNTS}" ]; then
      POD_COUNTS="${CONFIG_POD_COUNTS}"
    fi
  fi
fi

if [ -z "${BENCHMARK_DIR}" ]; then
  if [ -n "${RESULTS_FILE}" ]; then
    BENCHMARK_DIR="$(dirname "${RESULTS_FILE}")"
  else
    BENCHMARK_DIR="data/outputs/cloud_benchmarks/${BENCHMARK_STAMP}_${CONFIG_EXPERIMENT_NAME}"
  fi
fi
if [ -z "${RESULTS_FILE}" ]; then
  RESULTS_FILE="${BENCHMARK_DIR}/summary.csv"
fi

RESULTS_DIR=$(dirname "${RESULTS_FILE}")
if ! mkdir -p "${RESULTS_DIR}" 2>/dev/null; then
  echo "Could not create benchmark output directory: ${RESULTS_DIR}" >&2
  echo "Ensure data/outputs/cloud_benchmarks is writable by your user." >&2
  echo "See docs/cloud.md for the recommended permission fix." >&2
  exit 1
fi
if [ ! -w "${RESULTS_DIR}" ]; then
  echo "Benchmark output directory is not writable: ${RESULTS_DIR}" >&2
  echo "Ensure data/outputs/cloud_benchmarks is writable by your user." >&2
  echo "See docs/cloud.md for the recommended permission fix." >&2
  exit 1
fi
mkdir -p "${BENCHMARK_DIR}/runs"

if [ ! -f "${RESULTS_FILE}" ]; then
  printf "dag_id,experiment_name,run_id,target_num_pods,repeat_index,state,elapsed_seconds,simulate_stage_elapsed_seconds,simulate_task_instance_seconds_sum,simulate_task_instance_count,simulate_finished_task_instance_count,simulate_stage_start_utc,simulate_stage_end_utc,simulate_log_file_count,simulate_autotune_match_count,simulate_autotuning_seconds_sum,simulate_autotuning_seconds_mean,simulate_autotuning_seconds_max,simulate_worker_sim_seconds_sum,simulate_worker_sim_seconds_mean,simulate_worker_sim_seconds_max,simulate_worker_simulate_calls_seconds_sum,simulate_worker_simulate_calls_seconds_mean,simulate_worker_simulate_calls_seconds_max,simulate_worker_write_seconds_sum,simulate_worker_write_seconds_mean,simulate_worker_write_seconds_max,simulate_worker_full_seconds_sum,simulate_worker_full_seconds_mean,simulate_worker_full_seconds_max,start_utc,end_utc\n" > "${RESULTS_FILE}"
fi

"${HELPER_PYTHON}" scripts/write_cloud_benchmark_metadata.py \
  --benchmark-dir "${BENCHMARK_DIR}" \
  --dag-id "${DAG_ID}" \
  --config "${CONFIG_PATH}" \
  --experiment-name "${CONFIG_EXPERIMENT_NAME}" \
  --pod-counts ${POD_COUNTS} \
  --invocation "bash scripts/benchmark_cloud_pod_sweep.sh${CONFIG_PATH:+ --config ${CONFIG_PATH}} ${DAG_ID} ${POD_COUNTS}" \
  >/dev/null

echo "Benchmark directory: ${BENCHMARK_DIR}"
echo "Benchmark results will be written to ${RESULTS_FILE}"
echo "Pod counts: ${POD_COUNTS}"
echo "Repeats per pod count: ${REPEAT_COUNT}"

for pods in $POD_COUNTS
do
  repeat_index=1
  while [ "${repeat_index}" -le "${REPEAT_COUNT}" ]
  do
    timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
    run_id="benchmark_pods_${pods}_r${repeat_index}_${timestamp}"
    start_epoch="$(date +%s)"
    start_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    conf_json="{\"target_num_pods\": ${pods}}"
    experiment_name="qft_n8_k2"
    if [ -n "${CONFIG_PATH}" ]; then
      conf_json="$("${CONFIG_RENDER_PYTHON}" scripts/render_cloud_benchmark_conf.py \
        --config "${CONFIG_PATH}" \
        --target-num-pods "${pods}" \
        --run-output-dir "${BENCHMARK_DIR}/runs/${run_id}" \
        --merged-output-file "${BENCHMARK_DIR}/runs/${run_id}/${CONFIG_EXPERIMENT_NAME}_all_batches.hsv")"
      experiment_name="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("benchmark_case", {}).get("experiment_name", "unknown"))' "${conf_json}")"
    fi
    run_dir="${BENCHMARK_DIR}/runs/${run_id}"
    mkdir -p "${run_dir}"
    printf "%s\n" "${conf_json}" > "${run_dir}/dag_run_conf.json"

    echo "Triggering ${DAG_ID} with target_num_pods=${pods} repeat=${repeat_index}/${REPEAT_COUNT} (run_id=${run_id})..."
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
          simulate_task_instance_count=""
          simulate_finished_task_instance_count=""
          simulate_stage_start_utc=""
          simulate_stage_end_utc=""
          simulate_stage_elapsed_seconds=""
          simulate_task_instance_seconds_sum=""
          simulate_log_file_count=""
          simulate_autotune_match_count=""
          simulate_autotuning_seconds_sum=""
          simulate_autotuning_seconds_mean=""
          simulate_autotuning_seconds_max=""
          simulate_worker_sim_seconds_sum=""
          simulate_worker_sim_seconds_mean=""
          simulate_worker_sim_seconds_max=""
          simulate_worker_simulate_calls_seconds_sum=""
          simulate_worker_simulate_calls_seconds_mean=""
          simulate_worker_simulate_calls_seconds_max=""
          simulate_worker_write_seconds_sum=""
          simulate_worker_write_seconds_mean=""
          simulate_worker_write_seconds_max=""
          simulate_worker_full_seconds_sum=""
          simulate_worker_full_seconds_mean=""
          simulate_worker_full_seconds_max=""
          if simulate_metrics_tsv="$("${HELPER_PYTHON}" scripts/summarize_airflow_task_timing.py \
            --dag-id "${DAG_ID}" \
            --run-id "${run_id}" \
            --task-id simulate_batch \
            --output tsv 2>/dev/null)"; then
            if [ -n "${simulate_metrics_tsv}" ]; then
              IFS="$(printf '\t')" read -r \
                simulate_task_instance_count \
                simulate_finished_task_instance_count \
                simulate_stage_start_utc \
                simulate_stage_end_utc \
                simulate_stage_elapsed_seconds \
                simulate_task_instance_seconds_sum <<EOF
${simulate_metrics_tsv}
EOF
              unset IFS
            fi
          fi
          if simulate_log_metrics_tsv="$("${HELPER_PYTHON}" scripts/summarize_cloud_task_logs.py \
            --dag-id "${DAG_ID}" \
            --run-id "${run_id}" \
            --task-id simulate_batch \
            --output tsv 2>/dev/null)"; then
            if [ -n "${simulate_log_metrics_tsv}" ]; then
              IFS="$(printf '\t')" read -r \
                simulate_log_file_count \
                simulate_autotune_match_count \
                simulate_autotuning_seconds_sum \
                simulate_autotuning_seconds_mean \
                simulate_autotuning_seconds_max \
                simulate_worker_sim_seconds_sum \
                simulate_worker_sim_seconds_mean \
                simulate_worker_sim_seconds_max \
                simulate_worker_simulate_calls_seconds_sum \
                simulate_worker_simulate_calls_seconds_mean \
                simulate_worker_simulate_calls_seconds_max \
                simulate_worker_write_seconds_sum \
                simulate_worker_write_seconds_mean \
                simulate_worker_write_seconds_max \
                simulate_worker_full_seconds_sum \
                simulate_worker_full_seconds_mean \
                simulate_worker_full_seconds_max <<EOF
${simulate_log_metrics_tsv}
EOF
              unset IFS
            fi
          fi
          echo "Run ${run_id} finished with state=${state} in ${elapsed_seconds}s."
          if [ -n "${simulate_stage_elapsed_seconds}" ]; then
            echo "  simulate_batch stage span=${simulate_stage_elapsed_seconds}s, summed worker time=${simulate_task_instance_seconds_sum}s across ${simulate_finished_task_instance_count}/${simulate_task_instance_count} task instances."
          fi
          if [ -n "${simulate_autotuning_seconds_sum}" ] || [ -n "${simulate_worker_full_seconds_sum}" ]; then
            echo "  worker logs: autotune sum=${simulate_autotuning_seconds_sum}s, worker full sum=${simulate_worker_full_seconds_sum}s from ${simulate_log_file_count} log files."
          fi
          printf "%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s\n" \
            "${DAG_ID}" "${experiment_name}" "${run_id}" "${pods}" "${repeat_index}" "${state}" "${elapsed_seconds}" "${simulate_stage_elapsed_seconds}" "${simulate_task_instance_seconds_sum}" "${simulate_task_instance_count}" "${simulate_finished_task_instance_count}" "${simulate_stage_start_utc}" "${simulate_stage_end_utc}" "${simulate_log_file_count}" "${simulate_autotune_match_count}" "${simulate_autotuning_seconds_sum}" "${simulate_autotuning_seconds_mean}" "${simulate_autotuning_seconds_max}" "${simulate_worker_sim_seconds_sum}" "${simulate_worker_sim_seconds_mean}" "${simulate_worker_sim_seconds_max}" "${simulate_worker_simulate_calls_seconds_sum}" "${simulate_worker_simulate_calls_seconds_mean}" "${simulate_worker_simulate_calls_seconds_max}" "${simulate_worker_write_seconds_sum}" "${simulate_worker_write_seconds_mean}" "${simulate_worker_write_seconds_max}" "${simulate_worker_full_seconds_sum}" "${simulate_worker_full_seconds_mean}" "${simulate_worker_full_seconds_max}" "${start_utc}" "${end_utc}" \
            >> "${RESULTS_FILE}"
          task_states_json="${run_dir}/task_states.json"
          if airflow tasks states-for-dag-run "${DAG_ID}" "${run_id}" --output json \
            >"${task_states_json}" 2>"${run_dir}/task_states_stderr.log"; then
            if ! "${HELPER_PYTHON}" scripts/archive_cloud_benchmark_run.py \
              --dag-id "${DAG_ID}" \
              --run-id "${run_id}" \
              --output-dir "${run_dir}" \
              --task-states-json "${task_states_json}" \
              >"${run_dir}/archive_stdout.log" 2>"${run_dir}/archive_stderr.log"; then
              echo "WARNING: failed to archive benchmark artifacts for ${run_id}." >&2
              echo "See ${run_dir}/archive_stderr.log" >&2
            fi
          else
            echo "WARNING: failed to capture task-state JSON for ${run_id}." >&2
            echo "See ${run_dir}/task_states_stderr.log" >&2
          fi
          if [ "${state}" != "success" ]; then
            echo "Task states for failed run ${run_id}:"
            airflow tasks states-for-dag-run "${DAG_ID}" "${run_id}" || true
            exit 1
          fi
          break
          ;;
        *)
          echo "Run ${run_id} state=${state}; sleeping ${POLL_SECONDS}s..."
          sleep "${POLL_SECONDS}"
          ;;
      esac
    done
    repeat_index=$((repeat_index + 1))
  done
done

echo "Benchmark summary saved to ${RESULTS_FILE}"
if ! "${HELPER_PYTHON}" scripts/plot_cloud_benchmark.py --summary-csv "${RESULTS_FILE}" >/dev/null; then
  echo "WARNING: failed to generate default cloud benchmark plot." >&2
fi
if ! "${HELPER_PYTHON}" scripts/plot_cloud_benchmark.py --summary-csv "${RESULTS_FILE}" --metric simulate_stage_elapsed_seconds >/dev/null; then
  echo "WARNING: failed to generate simulate-stage cloud benchmark plot." >&2
fi
if ! "${HELPER_PYTHON}" scripts/plot_gantt_multiexec.py \
  --input-glob "${BENCHMARK_DIR}/runs/*/task_instances.json" \
  --output "${BENCHMARK_DIR}/gantt_multiexec.svg" \
  >"${BENCHMARK_DIR}/gantt_multiexec_stdout.log" 2>"${BENCHMARK_DIR}/gantt_multiexec_stderr.log"; then
  echo "WARNING: failed to generate multi-run Gantt plot." >&2
fi

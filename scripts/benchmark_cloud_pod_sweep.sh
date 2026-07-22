#!/bin/sh

set -eu

DAG_ID="${1:-feynman}"
shift || true
POLL_SECONDS="${POLL_SECONDS:-5}"
RESULTS_FILE="${RESULTS_FILE:-}"

if [ "$#" -eq 0 ]; then
  POD_COUNTS="1 2 4 8"
else
  POD_COUNTS="$*"
fi

if [ -n "${RESULTS_FILE}" ]; then
  RESULTS_DIR=$(dirname "${RESULTS_FILE}")
  mkdir -p "${RESULTS_DIR}"
  if [ ! -f "${RESULTS_FILE}" ]; then
    printf "run_id,target_num_pods,state,elapsed_seconds\n" > "${RESULTS_FILE}"
  fi
fi

for pods in $POD_COUNTS
do
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  run_id="benchmark_pods_${pods}_${timestamp}"
  start_epoch="$(date +%s)"

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
        elapsed_seconds=$((end_epoch - start_epoch))
        echo "Run ${run_id} finished with state=${state} in ${elapsed_seconds}s."
        if [ -n "${RESULTS_FILE}" ]; then
          printf "%s,%s,%s,%s\n" \
            "${run_id}" "${pods}" "${state}" "${elapsed_seconds}" >> "${RESULTS_FILE}"
        fi
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

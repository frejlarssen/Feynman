#!/bin/sh

set -eu

DAG_ID="feynman"
POOL_NAME="${FEYNMAN_SHARED_POOL:-simulate_pool}"
SUITE_STAMP="${SUITE_STAMP:-$(date -u +%Y%m%dT%H%M%SZ)}"
SUITE_DIR="${SUITE_DIR:-}"
LIST_ONLY=0

case_config_path() {
  case "$1" in
    contiguous)
      printf "%s\n" "scripts/experiments/cloud/rqc_imbalance_laptop_contiguous.json"
      ;;
    random)
      printf "%s\n" "scripts/experiments/cloud/rqc_imbalance_laptop_random.json"
      ;;
    *)
      return 1
      ;;
  esac
}

usage() {
  cat <<'EOF' >&2
Usage:
  sh scripts/benchmark_rqc_imbalance_laptop_suite.sh [all|contiguous|random ...]
  sh scripts/benchmark_rqc_imbalance_laptop_suite.sh --list
  sh scripts/benchmark_rqc_imbalance_laptop_suite.sh --dag-id feynman --pool-name simulate_pool contiguous

Behavior:
  - With no case arguments, runs: contiguous random
  - With one or more case arguments, runs only those named cases
  - Any argument ending in .json is treated as an explicit config path and run by itself
EOF
  exit 1
}

SELECTED_ITEMS=""
while [ "$#" -gt 0 ]
do
  case "$1" in
    --dag-id)
      DAG_ID="$2"
      shift 2
      ;;
    --pool-name)
      POOL_NAME="$2"
      shift 2
      ;;
    --suite-dir)
      SUITE_DIR="$2"
      shift 2
      ;;
    --suite-stamp)
      SUITE_STAMP="$2"
      shift 2
      ;;
    --list)
      LIST_ONLY=1
      shift
      ;;
    --help|-h)
      usage
      ;;
    --)
      shift
      break
      ;;
    -*)
      echo "Unknown option: $1" >&2
      usage
      ;;
    *)
      if [ -z "${SELECTED_ITEMS}" ]; then
        SELECTED_ITEMS="$1"
      else
        SELECTED_ITEMS="${SELECTED_ITEMS}
$1"
      fi
      shift
      ;;
  esac
done

if [ "$#" -gt 0 ]; then
  for item in "$@"
  do
    if [ -z "${SELECTED_ITEMS}" ]; then
      SELECTED_ITEMS="$item"
    else
      SELECTED_ITEMS="${SELECTED_ITEMS}
$item"
    fi
  done
fi

if [ "${LIST_ONLY}" -eq 1 ]; then
  printf "%s\n" "contiguous"
  printf "%s\n" "random"
  exit 0
fi

if [ -z "${SUITE_DIR}" ]; then
  SUITE_DIR="data/outputs/cloud_benchmarks/${SUITE_STAMP}_rqc_imbalance_laptop_suite"
fi

if [ -z "${SELECTED_ITEMS}" ]; then
  SELECTED_ITEMS="contiguous
random"
elif [ "${SELECTED_ITEMS}" = "all" ]; then
  SELECTED_ITEMS="contiguous
random"
fi

mkdir -p "${SUITE_DIR}"
MANIFEST_PATH="${SUITE_DIR}/suite_manifest.tsv"
printf "label\tconfig\tbenchmark_dir\tresults_file\n" > "${MANIFEST_PATH}"

echo "RQC imbalance laptop suite"
echo "  dag_id: ${DAG_ID}"
echo "  pool_name: ${POOL_NAME}"
echo "  suite_dir: ${SUITE_DIR}"
echo "  manifest: ${MANIFEST_PATH}"

printf "%s\n" "${SELECTED_ITEMS}" | while IFS= read -r item
do
  [ -n "${item}" ] || continue

  label="${item}"
  config_path=""
  if case_config_path "${item}" >/dev/null 2>&1; then
    config_path="$(case_config_path "${item}")"
  elif [ -f "${item}" ]; then
    config_path="${item}"
    label="$(basename "${item}" .json)"
  else
    echo "Unknown suite item: ${item}" >&2
    echo "Use --list to see built-in cases, or pass an explicit .json path." >&2
    exit 1
  fi

  benchmark_dir="${SUITE_DIR}/${label}"
  results_file="${benchmark_dir}/summary.csv"
  echo "Running case ${label}"
  echo "  config: ${config_path}"
  echo "  benchmark_dir: ${benchmark_dir}"

  BENCHMARK_DIR="${benchmark_dir}" \
  RESULTS_FILE="${results_file}" \
  sh scripts/benchmark_cloud_pool_sweep.sh \
    --config "${config_path}" \
    --dag-id "${DAG_ID}" \
    --pool-name "${POOL_NAME}"

  printf "%s\t%s\t%s\t%s\n" "${label}" "${config_path}" "${benchmark_dir}" "${results_file}" >> "${MANIFEST_PATH}"
done

echo "Suite complete. Manifest written to ${MANIFEST_PATH}"

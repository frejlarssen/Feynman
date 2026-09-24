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
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

if [ -z "${CONFIG_PATH}" ]; then
  echo "Usage: sh scripts/benchmark_cloud_autoscale.sh --config <path> [--dag-id feynman]" >&2
  exit 1
fi

if [ -n "${HELPER_PYTHON:-}" ]; then
  AUTOSCALE_PYTHON="${HELPER_PYTHON}"
elif [ -x "${HOME}/micromamba/envs/feynman/bin/python" ]; then
  AUTOSCALE_PYTHON="${HOME}/micromamba/envs/feynman/bin/python"
else
  AUTOSCALE_PYTHON="$(command -v python3)"
fi

"${AUTOSCALE_PYTHON}" scripts/airflow_pool_autoscaler.py \
  --config "${CONFIG_PATH}" \
  --validate-config >/dev/null

HELPER_PYTHON="${AUTOSCALE_PYTHON}" \
CONFIG_RENDER_PYTHON="${AUTOSCALE_PYTHON}" \
sh scripts/benchmark_cloud_runner.sh \
  --config "${CONFIG_PATH}" \
  --dag-id "${DAG_ID}" \
  --label-kind autoscaler

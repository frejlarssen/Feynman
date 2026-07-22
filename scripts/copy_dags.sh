#!/bin/sh

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
AIRFLOW_DAGS_DIR="${AIRFLOW_DAGS_DIR:-$HOME/airflow/dags}"

mkdir -p "${AIRFLOW_DAGS_DIR}"

cp "${REPO_ROOT}/airflow-dags/feynman_dag.py" "${AIRFLOW_DAGS_DIR}/"

echo "Copied DAGs to ${AIRFLOW_DAGS_DIR}."
echo "If task images changed, run bash scripts/prepare_airflow_local.sh."

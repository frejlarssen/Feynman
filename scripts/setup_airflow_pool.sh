#!/bin/sh

set -eu

POOL_NAME="${1:-simulate_pool}"
POOL_SLOTS="${2:-4}"
POOL_DESCRIPTION="${3:-Limit concurrent simulate_batch Kubernetes pods}"

airflow pools set "${POOL_NAME}" "${POOL_SLOTS}" "${POOL_DESCRIPTION}"
airflow pools list | grep "${POOL_NAME}" || true

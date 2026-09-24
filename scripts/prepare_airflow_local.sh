#!/bin/sh

set -eu

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
CLUSTER_NAME="${1:-feynman-cluster}"

sh "${SCRIPT_DIR}/copy_dags.sh"
echo "Syncing task images into k3d cluster ${CLUSTER_NAME}..."
sh "${SCRIPT_DIR}/build_and_import_cloud_images.sh" "${CLUSTER_NAME}"

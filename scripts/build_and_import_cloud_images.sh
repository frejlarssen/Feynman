#!/bin/sh

set -eu

CLUSTER_NAME="${1:-feynman-cluster}"

for image_spec in \
  "simulate:feynman-simulate:latest" \
  "split:feynman-split:latest" \
  "concat:feynman-concat:latest"
do
  target="${image_spec%%:*}"
  tag="${image_spec#*:}"

  echo "Building ${tag} from target ${target}..."
  docker build --target "${target}" -t "${tag}" .
done

echo "Importing images into k3d cluster ${CLUSTER_NAME}..."
k3d image import \
  feynman-simulate:latest \
  feynman-split:latest \
  feynman-concat:latest \
  -c "${CLUSTER_NAME}"

echo "Images available in cluster ${CLUSTER_NAME}:"
docker exec "k3d-${CLUSTER_NAME}-server-0" crictl images | \
  grep -E 'feynman-(simulate|split|concat)'

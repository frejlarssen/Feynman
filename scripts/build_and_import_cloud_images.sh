#!/bin/sh

set -eu

CLUSTER_NAME="${1:-feynman-cluster}"
NODE_NAME="k3d-${CLUSTER_NAME}-server-0"
WARNING_THRESHOLD_PERCENT="${WARNING_THRESHOLD_PERCENT:-80}"
IMAGE_GC_HIGH_THRESHOLD_PERCENT="${IMAGE_GC_HIGH_THRESHOLD_PERCENT:-85}"

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
docker exec "${NODE_NAME}" crictl images | \
  grep -E 'feynman-(simulate|split|concat)'

usage_percent="$(docker exec "${NODE_NAME}" sh -lc "df -P / | awk 'NR==2 {gsub(/%/, \"\", \$5); print \$5}'")"
echo "Node ${NODE_NAME} root filesystem usage: ${usage_percent}%"
if [ "${usage_percent}" -ge "${WARNING_THRESHOLD_PERCENT}" ]; then
  echo "WARNING: node usage is above the recommended warning threshold (${WARNING_THRESHOLD_PERCENT}%)." >&2
  echo "Keep the host below this level for more stable repeated benchmark runs." >&2
fi

if [ "${usage_percent}" -ge "${IMAGE_GC_HIGH_THRESHOLD_PERCENT}" ]; then
  echo "WARNING: node usage is above the kubelet image-GC high threshold (${IMAGE_GC_HIGH_THRESHOLD_PERCENT}%)." >&2
  echo "Unused imported images may be garbage-collected by kubelet." >&2
  echo "Free disk space on the host before relying on these images for repeated benchmark runs." >&2
fi

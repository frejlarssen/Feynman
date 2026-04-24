#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "Usage: scripts/save_output.sh <output_file> [label] [notes...]" >&2
  exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ARCHIVE_DIR="${ROOT_DIR}/outputs/archive"
MANIFEST="${ARCHIVE_DIR}/manifest.tsv"
HEADER="saved_at\tcommit\tbranch\tdirty\tlabel\tfile\tnotes"

src="$1"
shift
label="${1:-run}"
if [[ $# -gt 0 ]]; then
  shift
fi
notes="${*:-}"

if [[ ! -e "${src}" && -e "${ROOT_DIR}/outputs/${src}" ]]; then
  src="${ROOT_DIR}/outputs/${src}"
fi

if [[ ! -f "${src}" ]]; then
  echo "File not found: ${src}" >&2
  exit 1
fi

mkdir -p "${ARCHIVE_DIR}"
if [[ ! -f "${MANIFEST}" ]]; then
  printf "%b\n" "${HEADER}" >"${MANIFEST}"
else
  current_header="$(head -n 1 "${MANIFEST}" || true)"
  if [[ "${current_header}" != "$(printf '%b' "${HEADER}")" ]]; then
    tmp_manifest="$(mktemp)"
    printf "%b\n" "${HEADER}" >"${tmp_manifest}"
    tail -n +2 "${MANIFEST}" >>"${tmp_manifest}" || true
    mv "${tmp_manifest}" "${MANIFEST}"
  fi
fi

stamp="$(date +%Y%m%d_%H%M%S)"
branch="$(git -C "${ROOT_DIR}" rev-parse --abbrev-ref HEAD)"
commit="$(git -C "${ROOT_DIR}" rev-parse --short HEAD)"
dirty="clean"
if [[ -n "$(git -C "${ROOT_DIR}" status --porcelain --untracked-files=no)" ]]; then
  dirty="dirty"
fi

safe_label="$(printf '%s' "${label}" | tr '[:space:]/' '__')"
base="$(basename "${src}")"
dst="${ARCHIVE_DIR}/${stamp}_${safe_label}_${base}"

mv "${src}" "${dst}"

printf "%s\t%s\t%s\t%s\t%s\t%s\t%s\n" \
  "$(date -Iseconds)" \
  "${commit}" \
  "${branch}" \
  "${dirty}" \
  "${label}" \
  "${dst#${ROOT_DIR}/}" \
  "${notes}" >>"${MANIFEST}"

echo "Saved: ${dst#${ROOT_DIR}/}"
echo "Manifest: ${MANIFEST#${ROOT_DIR}/}"

#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../../.." && pwd)"

BACKEND_ROOT="${REPO_ROOT}/backend"
ENTRYPOINT="${APP_DIR}/entrypoints/runtime.py"
OPTIONS_FILE="${SCRIPT_DIR}/common-options.txt"
OUTPUT_DIR="${APP_DIR}/build/nuitka/runtime"
CANONICAL_DIST_DIR="${OUTPUT_DIR}/weave-cbt.dist"
PYTHON_BIN="${PYTHON_BIN:-python}"

export PYTHONPATH="${BACKEND_ROOT}${PYTHONPATH:+:${PYTHONPATH}}"

NUITKA_OPTIONS=()
# Process the final option even when common-options.txt has no trailing newline.
while IFS= read -r option || [[ -n "${option}" ]]; do
    [[ -z "${option}" ]] && continue
    [[ "${option}" =~ ^[[:space:]]*# ]] && continue
    NUITKA_OPTIONS+=("${option}")
done < "${OPTIONS_FILE}"

rm -rf "${OUTPUT_DIR}"
mkdir -p "${OUTPUT_DIR}"

# Compile the full backend once. The resulting executable dispatches between
# API, worker and schema bootstrap modes at runtime.
"${PYTHON_BIN}" -m nuitka \
    "${NUITKA_OPTIONS[@]}" \
    --output-dir="${OUTPUT_DIR}" \
    --output-filename="weave-cbt" \
    "${ENTRYPOINT}"

DIST_DIR="$(find "${OUTPUT_DIR}" \
    -maxdepth 1 \
    -type d \
    -name "*.dist" \
    -print \
    -quit)"

if [[ -z "${DIST_DIR}" ]]; then
    echo "ERROR: Nuitka standalone output directory was not found."
    exit 1
fi

# Give Docker a stable artifact path regardless of Nuitka's entrypoint-derived
# .dist directory name.
if [[ "${DIST_DIR}" != "${CANONICAL_DIST_DIR}" ]]; then
    rm -rf "${CANONICAL_DIST_DIR}"
    mv "${DIST_DIR}" "${CANONICAL_DIST_DIR}"
    DIST_DIR="${CANONICAL_DIST_DIR}"
fi

test -x "${DIST_DIR}/weave-cbt"

# Alembic loads revision modules from disk at runtime.
cp "${BACKEND_ROOT}/alembic.ini" "${DIST_DIR}/alembic.ini"
cp -R "${BACKEND_ROOT}/alembic" "${DIST_DIR}/alembic"

echo "Unified WEAVE CBT runtime build created at:"
echo "${DIST_DIR}"

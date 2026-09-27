#!/usr/bin/env bash
# Tier 1 pipeline: filtered frames -> COLMAP (via nerfstudio) -> scale correct -> train.
#
# Usage: ./02_run_pipeline.sh <frames_dir> <run_name> [reference_points.csv]
#
# If reference_points.csv is omitted, trains at COLMAP's raw (unscaled) size --
# fine for a first look, but distances/coverage numbers won't be in metres.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

FRAMES_DIR="$1"
RUN_NAME="$2"
REF_POINTS="${3:-}"

OUT_DIR="${SCRIPT_DIR}/data/processed/${RUN_NAME}"

echo "== COLMAP + pose extraction via nerfstudio =="
# Check `ns-process-data images --help` for your installed nerfstudio version --
# flag names have shifted between releases.
ns-process-data images \
    --data "${FRAMES_DIR}" \
    --output-dir "${OUT_DIR}" \
    --matching-method sequential

TRANSFORMS="${OUT_DIR}/transforms.json"

if [[ -n "${REF_POINTS}" ]]; then
    echo "== Tier 1 scale correction =="
    python3 "${SCRIPT_DIR}/scale_correct.py" "${TRANSFORMS}" "${REF_POINTS}" "${OUT_DIR}/transforms_scaled.json"
    cp "${OUT_DIR}/transforms_scaled.json" "${TRANSFORMS}"
else
    echo "no reference_points.csv given -- training on COLMAP's raw, unscaled poses"
fi

echo "== Training splat =="
ns-train splatfacto --data "${OUT_DIR}" --output-dir "${SCRIPT_DIR}/data/splats/${RUN_NAME}"

echo "done -- ns-train prints the exact config.yml path to view/export from"

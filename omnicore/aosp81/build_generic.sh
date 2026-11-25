#!/usr/bin/env bash
# Execute ONLY on a provisioned, isolated Linux x86_64 AOSP 8.1 build host.
# Does not sync sources, flash devices, change security settings or touch MT6580.
set -euo pipefail

if [[ "$#" -ne 2 ]]; then
  echo "Usage: $0 /absolute/path/to/aosp /absolute/path/to/manifest.lock.xml" >&2
  exit 2
fi
AOSP_DIR="$(realpath "$1")"
LOCK_FILE="$(realpath "$2")"
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
JOBS="${OMNICORE_BUILD_JOBS:-4}"
if ! [[ "$JOBS" =~ ^[1-9][0-9]?$ ]]; then
  echo "Invalid OMNICORE_BUILD_JOBS (1..99)" >&2
  exit 2
fi

python3 "$SCRIPT_DIR/preflight.py" --manifest "$SCRIPT_DIR/omnicore.xml" \
  --aosp "$AOSP_DIR" --lock "$LOCK_FILE"
python3 "$SCRIPT_DIR/install_overlay.py" --aosp "$AOSP_DIR" --lock "$LOCK_FILE" --apply

# Correctness is determined by actual command exit status, not grepping logs.
cd "$AOSP_DIR"
source build/envsetup.sh
lunch omnicore_emulator_x86_64-eng

mkdir -p "$AOSP_DIR/out/omnicore-evidence"
LOG="$AOSP_DIR/out/omnicore-evidence/build.log"
# pipefail ensures Ninja/make failure is not masked by tee.
m -j"$JOBS" 2>&1 | tee "$LOG"

PRODUCT_OUT="$AOSP_DIR/out/target/product/generic_x86_64"
python3 "$SCRIPT_DIR/verify_generic_build.py" --product-out "$PRODUCT_OUT" \
  | tee "$AOSP_DIR/out/omnicore-evidence/image-sanity.json"
sha256sum "$LOCK_FILE" > "$AOSP_DIR/out/omnicore-evidence/manifest.sha256"

printf 'F1 build command completed with exit code 0. Emulator boot NOT tested.\n'

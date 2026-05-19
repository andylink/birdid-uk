#!/usr/bin/env bash
# scripts/package_perch_model.sh
#
# One-time helper: package the locally-cached Perch v2 model files into
# tarballs ready to upload as GitHub Release assets.
#
# The models are read from the kagglehub cache (~/.cache/kagglehub/) which
# is populated on first use.  No Kaggle credentials are needed if the model
# has already been downloaded on this machine.
#
# Usage (from the repo root):
#   bash scripts/package_perch_model.sh
#
# Output:
#   perch_v2_cpu.tar.gz  (~362 MB) — CPU variant (Raspberry Pi, x86 no GPU)
#   perch_v2_gpu.tar.gz  (~362 MB) — GPU variant (NVIDIA CUDA)
#
# Then upload both as assets to a GitHub Release:
#
#   gh release create models/perch-v2 \
#       perch_v2_cpu.tar.gz perch_v2_gpu.tar.gz \
#       --repo andylink/birdid-uk \
#       --title "Perch v2 model weights" \
#       --notes "Pre-packaged Perch v2 TF SavedModel — no Kaggle account required."
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$REPO_ROOT/venv"

if [[ ! -d "$VENV" ]]; then
    echo "ERROR: venv not found at $VENV" >&2
    echo "       Run install.sh first." >&2
    exit 1
fi

PYTHON="$VENV/bin/python"

if ! "$PYTHON" -c "import kagglehub" 2>/dev/null; then
    echo "ERROR: kagglehub is not installed in the venv." >&2
    echo "       pip install perch-hoplite[tf]" >&2
    exit 1
fi

echo ""
echo "  BirdID-UK — Perch v2 model packager"
echo "  ─────────────────────────────────────────────"
echo ""

# ── Resolve model paths from kagglehub cache ──────────────────────────────────
# Use load_from_cache so we never trigger a download — the models must already
# be present.  If they are not, the user is told how to get them.

get_cached_path() {
    local owner="$1" model="$2" framework="$3" variation="$4" version="$5"
    "$PYTHON" - <<PYEOF
from kagglehub.cache import load_from_cache, ModelHandle
try:
    h = ModelHandle(
        owner="$owner", model="$model",
        framework="$framework", variation="$variation", version=$version,
    )
    path = load_from_cache(h)
    print(path)
except Exception as e:
    import sys
    print(f"NOT_FOUND:{e}", file=sys.stderr)
    sys.exit(1)
PYEOF
}

echo "  [+] Locating CPU model in kagglehub cache..."
CPU_PATH="$(get_cached_path google bird-vocalization-classifier tensorFlow2 perch_v2_cpu 1)" || {
    echo "  [!] CPU model not found in cache." >&2
    echo "      It will be downloaded automatically if you run with Kaggle credentials." >&2
    CPU_PATH=""
}

echo "  [+] Locating GPU model in kagglehub cache..."
GPU_PATH="$(get_cached_path google bird-vocalization-classifier tensorFlow2 perch_v2 2)" || {
    echo "  [!] GPU model not found in cache." >&2
    GPU_PATH=""
}

if [[ -z "$CPU_PATH" && -z "$GPU_PATH" ]]; then
    echo ""
    echo "  ERROR: Neither model variant found in the kagglehub cache." >&2
    echo "  The cache is usually at: ~/.cache/kagglehub/" >&2
    echo ""
    echo "  To populate it, run inference once with Kaggle credentials configured:" >&2
    echo "    source $VENV/bin/activate" >&2
    echo "    python -c \"from inference.perch import PerchModel; PerchModel()._ensure_model()\"" >&2
    exit 1
fi

echo ""

# ── Package ───────────────────────────────────────────────────────────────────

package() {
    local src="$1" out="$2" label="$3"
    if [[ -z "$src" ]]; then
        echo "  [!] Skipping $label — not found in cache."
        return
    fi
    echo "  [+] Packaging $label"
    echo "      Source: $src"
    echo "      Output: $out"
    # Flat tarball — install.sh extracts with:  tar -xz -C "$PERCH_MODEL_DIR"
    tar -czf "$out" -C "$src" .
    local size
    size="$(du -sh "$out" | cut -f1)"
    echo "  [+] Done: $out  ($size)"
    echo ""
}

package "$CPU_PATH" "$REPO_ROOT/perch_v2_cpu.tar.gz" "CPU (perch_v2_cpu)"
package "$GPU_PATH" "$REPO_ROOT/perch_v2_gpu.tar.gz" "GPU (perch_v2)"

echo "  ─────────────────────────────────────────────"
echo "  Upload both files as assets on a GitHub Release:"
echo ""
echo "    gh release create models/perch-v2 \\"
echo "        perch_v2_cpu.tar.gz perch_v2_gpu.tar.gz \\"
echo "        --repo andylink/birdid-uk \\"
echo "        --title \"Perch v2 model weights\" \\"
echo "        --notes \"Pre-packaged Perch v2 TF SavedModel — no Kaggle account required.\""
echo ""
echo "  install.sh will then automatically download the right variant."
echo ""

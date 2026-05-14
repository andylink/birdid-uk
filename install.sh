#!/usr/bin/env bash
# install.sh — set up BirdID-UK on a Raspberry Pi or Linux server.
#
# Usage:
#   bash install.sh            # standard install
#   bash install.sh --systemd  # also install and enable systemd services
#
# Run from the cloned repository root:
#   git clone https://github.com/andylink/birdid-uk.git
#   cd BirdID-UK
#   bash install.sh
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SYSTEMD=false

for arg in "$@"; do
    case "$arg" in
        --systemd) INSTALL_SYSTEMD=true ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────

info()    { echo "  [+] $*"; }
section() { echo ""; echo "==> $*"; }
warn()    { echo "  [!] $*"; }

# ── Banner ────────────────────────────────────────────────────────────────────

echo ""
echo "  BirdID-UK — Real-time garden bird classifier"
echo "  ─────────────────────────────────────────────"

# ── OS check ─────────────────────────────────────────────────────────────────

if [[ "$(uname -s)" != "Linux" ]]; then
    echo "ERROR: This installer is for Linux only." >&2
    exit 1
fi

if ! command -v apt-get &>/dev/null; then
    warn "apt-get not found. Skipping system package installation."
    warn "Ensure the following are installed manually:"
    warn "  portaudio19-dev  python3-venv  python3-dev  libsndfile1"
    SKIP_APT=true
else
    SKIP_APT=false
fi

# ── System packages ───────────────────────────────────────────────────────────

if [[ "$SKIP_APT" == "false" ]]; then
    section "Installing system packages (requires sudo)..."
    sudo apt-get update -qq
    PACKAGES=(python3-venv python3-dev portaudio19-dev libsndfile1 libsndfile1-dev)

    # ffmpeg is required for RTSP audio sources — optional but recommended
    PACKAGES+=(ffmpeg)

    # Raspberry Pi: install optimised BLAS for faster numpy
    if grep -qi "raspberry\|rpi\|bcm" /proc/cpuinfo 2>/dev/null || \
       [[ "$(uname -m)" == "aarch64" || "$(uname -m)" == "armv7l" ]]; then
        info "Detected Raspberry Pi / ARM — adding libatlas-base-dev"
        PACKAGES+=(libatlas-base-dev)
    fi

    sudo apt-get install -y --no-install-recommends "${PACKAGES[@]}"
    info "System packages installed."
fi

# ── Python version check ──────────────────────────────────────────────────────

section "Checking Python version..."
PYTHON=""
for candidate in python3.11 python3; do
    if command -v "$candidate" &>/dev/null; then
        ver="$("$candidate" -c 'import sys; print(sys.version_info[:2])')"
        if [[ "$ver" == "(3, 11)" || "$ver" > "(3, 11)" ]]; then
            PYTHON="$candidate"
            break
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "ERROR: Python 3.11 or newer is required." >&2
    echo "       On Raspberry Pi OS (Bookworm) run:  sudo apt-get install python3.11" >&2
    exit 1
fi

info "Using $PYTHON ($($PYTHON --version))"

# ── Python virtual environment ────────────────────────────────────────────────

section "Setting up Python virtual environment..."
VENV="$REPO_ROOT/venv"

if [[ -d "$VENV" ]]; then
    info "Existing venv found — upgrading packages."
else
    info "Creating venv at $VENV"
    "$PYTHON" -m venv "$VENV"
fi

# shellcheck source=/dev/null
source "$VENV/bin/activate"

pip install --upgrade pip --quiet
info "pip upgraded."

# ── Python dependencies ───────────────────────────────────────────────────────

section "Installing Python dependencies..."
info "This may take several minutes on a Raspberry Pi (birdnet-analyzer builds from source)."
pip install -r "$REPO_ROOT/requirements.txt" --quiet
info "Dependencies installed."

# ── Data directories ──────────────────────────────────────────────────────────

section "Creating data directories..."
mkdir -p "$REPO_ROOT/data/detections"
mkdir -p "$REPO_ROOT/data/species_images"
info "data/detections/ and data/species_images/ ready."

# ── Config file ───────────────────────────────────────────────────────────────

section "Checking configuration..."
if [[ -f "$REPO_ROOT/config.toml" ]]; then
    info "config.toml already exists — leaving it untouched."
else
    cp "$REPO_ROOT/config.toml.example" "$REPO_ROOT/config.toml"
    info "Copied config.toml.example → config.toml"
    warn "You MUST edit config.toml before running the detector."
    warn "  Key settings to change:"
    warn "    [general]  timezone, station_name"
    warn "    [location] lat, lon  (for correct sunrise/sunset filtering)"
    warn "    [audio]    device    (run: python -m sounddevice to find the index)"
fi

# ── Systemd services ──────────────────────────────────────────────────────────

if [[ "$INSTALL_SYSTEMD" == "true" ]]; then
    section "Installing systemd services..."

    UNIT_DIR="/etc/systemd/system"
    SERVICE_FILES=(
        "$REPO_ROOT/systemd/birddetector.target"
        "$REPO_ROOT/systemd/birddetector-capture.service"
        "$REPO_ROOT/systemd/birddetector-dashboard.service"
    )

    # Patch ExecStart paths to point at this venv and repo root
    TMP_SYSTEMD=$(mktemp -d)
    trap 'rm -rf "$TMP_SYSTEMD"' EXIT

    for f in "${SERVICE_FILES[@]}"; do
        fname="$(basename "$f")"
        sed "s|/opt/birdid-uk|$REPO_ROOT|g" \
            "$f" > "$TMP_SYSTEMD/$fname"
    done

    sudo cp "$TMP_SYSTEMD/"* "$UNIT_DIR/"
    sudo systemctl daemon-reload
    sudo systemctl enable birddetector.target
    info "Systemd services installed and enabled."
    info "Start with:  sudo systemctl start birddetector.target"
    info "Logs:        journalctl -u birddetector-capture -f"
fi

# ── Done ──────────────────────────────────────────────────────────────────────

echo ""
echo "  ─────────────────────────────────────────────"
echo "  Installation complete."
echo ""
echo "  Next steps:"
echo ""
echo "  1. Edit config.toml:"
echo "       nano $REPO_ROOT/config.toml"
echo ""
echo "  2. Find your microphone device index:"
echo "       source $VENV/bin/activate"
echo "       python -m sounddevice"
echo "       # set the number shown as  device = N  in config.toml"
echo ""
echo "  3. Run the detector + dashboard:"
echo "       source $VENV/bin/activate"
echo "       python $REPO_ROOT/main.py"
echo ""
echo "  4. Open the dashboard:"
echo "       http://$(hostname -I | awk '{print $1}'):8080"
echo ""

if [[ "$INSTALL_SYSTEMD" == "false" ]]; then
    echo "  Tip: re-run with --systemd to install as a background service:"
    echo "       bash $REPO_ROOT/install.sh --systemd"
    echo ""
fi

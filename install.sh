#!/usr/bin/env bash
# install.sh — set up BirdID-UK on a Raspberry Pi or Linux server.
#
# One-line install from a fresh machine:
#   curl -fsSL https://raw.githubusercontent.com/andylink/birdid-uk/main/install.sh | bash
#
# Or from a cloned repo:
#   bash install.sh [--systemd] [--configure] [--no-configure]
#
# Flags:
#   --systemd       Also install and enable systemd services
#   --configure     Run the setup wizard after install without prompting
#   --no-configure  Skip the "run wizard?" prompt at the end (silent install)
#
set -euo pipefail

# ── Curl-bootstrap ────────────────────────────────────────────────────────────
# When piped via "curl | bash", BASH_SOURCE[0] is empty or "bash" and detect.py
# won't be found relative to the script.  In that case: clone the repo, then
# re-exec the real install.sh from inside it.

_SCRIPT_SELF="${BASH_SOURCE[0]:-}"
_SCRIPT_DIR=""
if [[ -n "$_SCRIPT_SELF" && "$_SCRIPT_SELF" != "bash" && "$_SCRIPT_SELF" != "/dev/stdin" ]]; then
    _SCRIPT_DIR="$(cd "$(dirname "$_SCRIPT_SELF")" 2>/dev/null && pwd || true)"
fi

if [[ -z "$_SCRIPT_DIR" || ! -f "$_SCRIPT_DIR/detect.py" ]]; then

    REPO_URL="https://github.com/andylink/birdid-uk.git"

    echo ""
    echo "  BirdID-UK — Real-time garden bird classifier"
    echo "  ─────────────────────────────────────────────"
    echo ""

    if ! command -v git &>/dev/null; then
        echo "  ERROR: git is required but not found." >&2
        echo "         Install it with:  sudo apt-get install git" >&2
        exit 1
    fi

    default_dir="$HOME/birdid-uk"

    # Read from /dev/tty so this works even when piped through curl
    if [[ -e /dev/tty ]]; then
        printf "  Install directory [%s]: " "$default_dir" >/dev/tty
        read -r _install_dir </dev/tty || true
    else
        _install_dir=""
    fi
    _install_dir="${_install_dir:-$default_dir}"
    _install_dir="${_install_dir/#\~/$HOME}"   # expand leading ~

    if [[ -d "$_install_dir/.git" ]]; then
        echo "  [+] Existing repo found at '$_install_dir' — pulling latest..."
        git -C "$_install_dir" pull --ff-only
    elif [[ -d "$_install_dir" ]]; then
        echo "  [!] '$_install_dir' exists but is not a git repo." >&2
        echo "  [!] Remove it or choose a different path." >&2
        exit 1
    else
        echo "  [+] Cloning BirdID-UK to $_install_dir ..."
        git clone "$REPO_URL" "$_install_dir"
    fi

    echo "  [+] Launching installer..."
    exec bash "$_install_dir/install.sh" "$@"
fi

# ── Running from inside the repo ──────────────────────────────────────────────

REPO_ROOT="$_SCRIPT_DIR"
INSTALL_SYSTEMD=false
RUN_CONFIGURE="ask"   # "ask" | "yes" | "no"

for arg in "$@"; do
    case "$arg" in
        --systemd)       INSTALL_SYSTEMD=true ;;
        --configure)     RUN_CONFIGURE="yes" ;;
        --no-configure)  RUN_CONFIGURE="no" ;;
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
    warn "apt-get not found — skipping system package installation."
    warn "Ensure these are installed manually before continuing:"
    warn "  portaudio19-dev  python3-venv  python3-dev  libsndfile1  ffmpeg"
    SKIP_APT=true
else
    SKIP_APT=false
fi

# ── System packages ───────────────────────────────────────────────────────────

if [[ "$SKIP_APT" == "false" ]]; then
    section "Installing system packages (requires sudo)..."
    sudo apt-get update -qq
    PACKAGES=(python3-venv python3-dev portaudio19-dev libsndfile1 libsndfile1-dev ffmpeg)

    # Raspberry Pi / ARM: optimised BLAS for faster numpy
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
for candidate in python3.11 python3.12 python3.13 python3; do
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

    TMP_SYSTEMD=$(mktemp -d)
    trap 'rm -rf "$TMP_SYSTEMD"' EXIT

    for f in "${SERVICE_FILES[@]}"; do
        fname="$(basename "$f")"
        sed "s|/opt/birdid-uk|$REPO_ROOT|g" "$f" > "$TMP_SYSTEMD/$fname"
    done

    sudo cp "$TMP_SYSTEMD/"* "$UNIT_DIR/"
    sudo systemctl daemon-reload
    sudo systemctl enable birddetector.target
    info "Systemd services installed and enabled."
    info "Start with:  sudo systemctl start birddetector.target"
    info "Logs:        journalctl -u birddetector-capture -f"
fi

# ── Setup wizard ──────────────────────────────────────────────────────────────

WIZARD="$REPO_ROOT/scripts/setup_wizard.py"

if [[ "$RUN_CONFIGURE" == "yes" ]]; then
    echo ""
    "$VENV/bin/python" "$WIZARD"
elif [[ "$RUN_CONFIGURE" == "ask" ]]; then
    echo ""
    echo "  ─────────────────────────────────────────────"
    echo ""
    # Read from /dev/tty in case stdin was redirected
    if [[ -e /dev/tty ]]; then
        printf "  Run the setup wizard to configure your mic and location? [Y/n]: " >/dev/tty
        read -r _wiz_answer </dev/tty || true
    else
        _wiz_answer="y"
    fi
    _wiz_answer="${_wiz_answer:-y}"
    if [[ "$_wiz_answer" =~ ^[Yy]$ ]]; then
        "$VENV/bin/python" "$WIZARD"
    else
        echo ""
        echo "  Skipped.  Run the wizard later with:"
        echo "    source $VENV/bin/activate"
        echo "    python $WIZARD"
        echo ""
        echo "  Or edit config.toml directly:"
        echo "    nano $REPO_ROOT/config.toml"
        echo ""
        echo "  Key settings:"
        echo "    [general]  station_name, timezone"
        echo "    [location] lat, lon  (for sunrise/sunset filtering)"
        echo "    [audio]    device    (run: python -m sounddevice to list devices)"
        echo ""
        echo "  Then start the detector:"
        echo "    source $VENV/bin/activate"
        echo "    python $REPO_ROOT/main.py"
        echo ""
        echo "  Open the dashboard:  http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<your-ip>'):8080"
        echo ""
    fi
fi

if [[ "$INSTALL_SYSTEMD" == "false" && "$RUN_CONFIGURE" != "yes" ]]; then
    echo "  Tip: install as a background service with:"
    echo "       bash $REPO_ROOT/install.sh --systemd"
    echo ""
fi

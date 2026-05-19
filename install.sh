#!/usr/bin/env bash
# install.sh — set up BirdID-UK on a Raspberry Pi or Linux server.
#
# One-line install from a fresh machine:
#   curl -fsSL https://raw.githubusercontent.com/andylink/birdid-uk/main/install.sh | bash
#
# Or from a cloned repo:
#   bash install.sh [--systemd] [--systemd-only] [--configure] [--no-configure]
#
# Flags:
#   --systemd       Also install and enable systemd services (or ask interactively)
#   --systemd-only  Only (re)install systemd units — skip all other steps
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
SYSTEMD_ONLY=false
RUN_CONFIGURE="ask"   # "ask" | "yes" | "no"

for arg in "$@"; do
    case "$arg" in
        --systemd)       INSTALL_SYSTEMD=true ;;
        --systemd-only)  SYSTEMD_ONLY=true; INSTALL_SYSTEMD=true ;;
        --configure)     RUN_CONFIGURE="yes" ;;
        --no-configure)  RUN_CONFIGURE="no" ;;
        *) echo "Unknown argument: $arg" >&2; exit 1 ;;
    esac
done

# ── Helpers ───────────────────────────────────────────────────────────────────

info()    { echo "  [+] $*"; }
section() { echo ""; echo "==> $*"; }
warn()    { echo "  [!] $*"; }

_ask() {
    # _ask <prompt> [default]
    # Reads from /dev/tty so it works when stdin is redirected (curl | bash).
    local prompt="$1" default="${2:-}" reply
    if [[ -e /dev/tty ]]; then
        printf "  %s" "$prompt" >/dev/tty
        read -r reply </dev/tty || true
    else
        reply=""
    fi
    echo "${reply:-$default}"
}

_ask_secret() {
    local prompt="$1" reply
    if [[ -e /dev/tty ]]; then
        printf "  %s" "$prompt" >/dev/tty
        read -rs reply </dev/tty || true
        printf "\n" >/dev/tty
    else
        reply=""
    fi
    echo "$reply"
}

_ask_yn() {
    # _ask_yn <prompt> <default y|n>  → exits 0 for yes, 1 for no
    local prompt="$1" default="${2:-y}" answer
    local opts="Y/n"
    [[ "$default" == "n" ]] && opts="y/N"
    answer="$(_ask "$prompt [$opts]: " "$default")"
    answer="${answer,,}"
    [[ "$answer" =~ ^(y|yes)$ ]]
}

# ── Systemd-only shortcut ─────────────────────────────────────────────────────
# When called with --systemd-only (from setup_wizard.py), skip all install
# steps and go straight to the systemd section.

if [[ "$SYSTEMD_ONLY" == "true" ]]; then
    VENV="$REPO_ROOT/venv"
    # fall through to the systemd block below
    true
else

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

# ── Perch inference backend (optional) ───────────────────────────────────────

section "Perch inference backend (optional)..."
echo "  Perch is Google's bird vocalization model — an alternative to the default BirdNET."
echo "  It requires ~2 GB of extra disk space (TensorFlow) and a one-time ~362 MB"
echo "  model download (fetched automatically from GitHub, no Kaggle account needed)."
echo ""

_PERCH_INSTALLED=false
if "$VENV/bin/python" -c "import perch_hoplite" 2>/dev/null; then
    _PERCH_INSTALLED=true
    info "Perch is already installed."
fi

if [[ "$_PERCH_INSTALLED" == "false" ]]; then
    if _ask_yn "Install Perch now?" "n"; then
        # Detect CUDA availability to choose the right extra
        if "$VENV/bin/python" -c "import subprocess,sys; r=subprocess.run(['nvidia-smi'],capture_output=True); sys.exit(0 if r.returncode==0 else 1)" 2>/dev/null; then
            _PERCH_EXTRA="tf-cuda"
            info "NVIDIA GPU detected — installing perch-hoplite[tf-cuda] (GPU support)"
        else
            _PERCH_EXTRA="tf"
            info "No NVIDIA GPU detected — installing perch-hoplite[tf] (CPU)"
        fi

        pip install "perch-hoplite[$_PERCH_EXTRA]" --quiet
        info "Perch installed."
        _PERCH_INSTALLED=true

        # ── Model download ──────────────────────────────────────────────
        # The Perch v2 CPU model (~362 MB compressed) is hosted as a GitHub
        # Release asset so users don't need a Kaggle account.
        # We always use the CPU variant: the GPU (XLA) saved_model has a
        # DEVICE_TYPE_INVALID bug in its embedded cuDNN backend config that
        # prevents execution on sm_86+ hardware with cuDNN 9. BirdNET runs on
        # GPU; Perch runs on CPU with acceptable latency for secondary validation.
        PERCH_MODEL_DIR="$HOME/.cache/birdid-uk/perch_v2"
        _GH_RELEASE_BASE="https://github.com/andylink/birdid-uk/releases/download/models%2Fperch-v2"
        _PERCH_TARBALL_URL="$_GH_RELEASE_BASE/perch_v2_cpu.tar.gz"

        if [[ -f "$PERCH_MODEL_DIR/saved_model.pb" || \
              -f "$PERCH_MODEL_DIR/savedmodel/saved_model.pb" ]]; then
            info "Perch model already cached at $PERCH_MODEL_DIR"
        else
            info "Downloading Perch v2 model (CPU, ~362 MB)..."
            mkdir -p "$PERCH_MODEL_DIR"
            if curl -fsSL --retry 3 "$_PERCH_TARBALL_URL" | tar -xz -C "$PERCH_MODEL_DIR"; then
                info "Perch model downloaded to $PERCH_MODEL_DIR"
            else
                warn "Download failed — Perch will attempt to download on first run."
                warn "If that also fails, re-run:  bash $REPO_ROOT/install.sh"
            fi
        fi

        # Switch config.toml to use perch if it exists
        if [[ -f "$REPO_ROOT/config.toml" ]]; then
            echo ""
            if _ask_yn "Switch inference model to 'perch' in config.toml?" "n"; then
                sed -i 's/^model\s*=\s*"birdnet"/model = "perch"/' "$REPO_ROOT/config.toml"
                info "config.toml updated: model = \"perch\""
            else
                info "Keeping model = \"birdnet\" in config.toml."
                info "Change it manually to \"perch\" when ready."
            fi
        fi
    else
        info "Skipping Perch — using BirdNET (default)."
        info "Install it later by re-running:  bash $REPO_ROOT/install.sh"
    fi
fi

# ── Frontend build ────────────────────────────────────────────────────────────

section "Building frontend..."
FRONTEND_DIR="$REPO_ROOT/dashboard/frontend"
if command -v npm &>/dev/null; then
    npm --prefix "$FRONTEND_DIR" install --silent
    npm --prefix "$FRONTEND_DIR" run build --silent
    info "Frontend built."
else
    warn "npm not found — skipping frontend build."
    warn "Install Node.js then run:  npm --prefix $FRONTEND_DIR install && npm --prefix $FRONTEND_DIR run build"
fi

# ── Data directories ──────────────────────────────────────────────────────────

section "Creating data directories..."
mkdir -p "$REPO_ROOT/data/detections"
mkdir -p "$REPO_ROOT/data/species_images"
mkdir -p "$REPO_ROOT/data/spectrograms"
info "data/detections/, data/spectrograms/, and data/species_images/ ready."

# ── Config file ───────────────────────────────────────────────────────────────

section "Checking configuration..."
if [[ -f "$REPO_ROOT/config.toml" ]]; then
    info "config.toml already exists — leaving it untouched."
else
    cp "$REPO_ROOT/config.toml.example" "$REPO_ROOT/config.toml"
    info "Copied config.toml.example → config.toml"
fi

# ── Admin password setup ──────────────────────────────────────────────────────

section "Setting up admin dashboard password..."
echo "  The admin password protects destructive actions (delete, bulk-delete, etc.)."

# Check if a password is already set
_HASH_EMPTY=false
if grep -q 'password_hash\s*=\s*""' "$REPO_ROOT/config.toml" 2>/dev/null; then
    _HASH_EMPTY=true
fi

if [[ "$_HASH_EMPTY" == "false" ]]; then
    echo "  A password is already set."
    echo "  Leave the new password blank to keep the existing one."
fi
echo ""

_admin_pass="$(_ask_secret "Admin password (leave blank to skip): ")"

if [[ -n "$_admin_pass" ]]; then
    BIRDID_ADMIN_PASS="$_admin_pass" BIRDID_CONFIG="$REPO_ROOT/config.toml" \
        "$VENV/bin/python" - <<'PYEOF'
import os, re, secrets, bcrypt
from pathlib import Path

config_path = Path(os.environ["BIRDID_CONFIG"])
pw_hash     = bcrypt.hashpw(os.environ["BIRDID_ADMIN_PASS"].encode(), bcrypt.gensalt()).decode()
secret      = secrets.token_hex(32)

text = config_path.read_text(encoding="utf-8")
# Overwrite existing values (handles both empty "" and previously set hashes)
text = re.sub(r'password_hash\s*=\s*"[^"]*"',  f'password_hash  = "{pw_hash}"',  text)
text = re.sub(r'session_secret\s*=\s*"[^"]*"', f'session_secret = "{secret}"', text)
config_path.write_text(text, encoding="utf-8")
PYEOF
    info "Admin password and session secret written to config.toml."
else
    if [[ "$_HASH_EMPTY" == "true" ]]; then
        warn "Skipped. Admin features will not require a password until one is set."
        warn "Re-run install.sh to set a password later."
    else
        info "Password unchanged."
    fi
fi

# ── BirdWeather integration (optional) ───────────────────────────────────────

section "BirdWeather integration (optional)..."
echo "  BirdWeather (app.birdweather.com) lets you share detections publicly"
echo "  and see what other stations are hearing nearby."
echo ""

_BIRDWEATHER_ENABLED=false
if grep -A5 '\[birdweather\]' "$REPO_ROOT/config.toml" 2>/dev/null | grep -q 'enabled\s*=\s*true'; then
    _BIRDWEATHER_ENABLED=true
fi
_existing_token=$(grep -A5 '\[birdweather\]' "$REPO_ROOT/config.toml" 2>/dev/null \
    | grep 'token\s*=' | sed 's/.*=\s*"\(.*\)"/\1/' || true)

if [[ -n "$_existing_token" ]]; then
    info "BirdWeather token already set (${_existing_token:0:8}…)."
    info "Leave blank below to keep the existing token."
fi

_bw_default="n"
[[ "$_BIRDWEATHER_ENABLED" == "true" ]] && _bw_default="y"

if _ask_yn "Enable BirdWeather uploads?" "$_bw_default"; then
    _BIRDWEATHER_TOKEN="$(_ask "BirdWeather station token: " "$_existing_token")"
    if [[ -n "$_BIRDWEATHER_TOKEN" ]]; then
        BIRDID_BW_TOKEN="$_BIRDWEATHER_TOKEN" BIRDID_CONFIG="$REPO_ROOT/config.toml" \
            "$VENV/bin/python" - <<'PYEOF'
import os, re
from pathlib import Path

config_path = Path(os.environ["BIRDID_CONFIG"])
token       = os.environ["BIRDID_BW_TOKEN"]

text = config_path.read_text(encoding="utf-8")
# Set enabled = true and token in the [birdweather] section
# Match inside the section by replacing the first occurrence after [birdweather]
in_bw = False
lines_out = []
for line in text.splitlines(keepends=True):
    if re.match(r'^\[birdweather\]', line):
        in_bw = True
    elif re.match(r'^\[', line):
        in_bw = False
    if in_bw:
        line = re.sub(r'^enabled\s*=.*$', 'enabled      = true', line, flags=re.MULTILINE)
        line = re.sub(r'^token\s*=.*$',   f'token        = "{token}"', line, flags=re.MULTILINE)
    lines_out.append(line)
config_path.write_text("".join(lines_out), encoding="utf-8")
PYEOF
        info "BirdWeather enabled with token ${_BIRDWEATHER_TOKEN:0:8}… written to config.toml."
    else
        warn "No token entered — BirdWeather not enabled."
        warn "Register a station at https://app.birdweather.com to get a token."
    fi
else
    info "BirdWeather uploads disabled."
fi

# ── Ask about systemd (interactive, not flag-required) ───────────────────────

if [[ "$INSTALL_SYSTEMD" == "false" ]]; then
    section "Background service (systemd)..."
    echo "  Installing as a systemd service means BirdID-UK starts automatically at boot"
    echo "  and keeps running in the background without a terminal."
    echo ""
    if _ask_yn "Install as a systemd background service?" "y"; then
        INSTALL_SYSTEMD=true
    else
        info "Skipping systemd.  Start manually with:"
        info "  source $VENV/bin/activate && python $REPO_ROOT/main.py"
        info "Add it later with:  bash $REPO_ROOT/install.sh --systemd-only"
    fi
fi

fi   # end of [[ "$SYSTEMD_ONLY" == "false" ]] block

# ── Systemd services ──────────────────────────────────────────────────────────

if [[ "$INSTALL_SYSTEMD" == "true" ]]; then
    section "Installing systemd services..."

    UNIT_DIR="/etc/systemd/system"

    # Remove any stale unit files left over from older installs that used
    # different service names (e.g. birddetector-capture → birdid-uk-capture).
    STALE_UNITS=(
        "birddetector-capture.service"
        "birddetector-dashboard.service"
        "birddetector.target"
    )
    for stale in "${STALE_UNITS[@]}"; do
        stale_path="$UNIT_DIR/$stale"
        if [[ -f "$stale_path" ]]; then
            warn "Removing stale unit: $stale_path"
            sudo systemctl disable --now "$stale" 2>/dev/null || true
            sudo rm -f "$stale_path"
        fi
    done

    SERVICE_FILES=(
        "$REPO_ROOT/systemd/birdid-uk.target"
        "$REPO_ROOT/systemd/birdid-uk-capture.service"
        "$REPO_ROOT/systemd/birdid-uk-dashboard.service"
    )

    TMP_SYSTEMD=$(mktemp -d)
    trap 'rm -rf "$TMP_SYSTEMD"' EXIT

    for f in "${SERVICE_FILES[@]}"; do
        fname="$(basename "$f")"
        sed -e "s|/opt/birdid-uk|$REPO_ROOT|g" \
            -e "s|BIRDID_USER|$(whoami)|g" \
            "$f" > "$TMP_SYSTEMD/$fname"
    done

    sudo cp "$TMP_SYSTEMD/"* "$UNIT_DIR/"

    # Generate cuda.env so the systemd service can find CUDA runtime libraries
    # installed as pip packages (nvidia-cuda-runtime-cu12, nvidia-cublas-cu12, etc.).
    # These live inside the venv at non-standard paths the system linker won't find.
    # Collect every nvidia/*/lib dir that contains at least one .so file.
    CUDA_LIB_PATH="$(find "$VENV/lib" -maxdepth 7 -name "*.so*" -not -name "*_static*" \
        2>/dev/null | sed 's|/[^/]*$||' | sort -u | tr '\n' ':' | sed 's/:$//')"
    if [[ -n "$CUDA_LIB_PATH" ]]; then
        echo "LD_LIBRARY_PATH=$CUDA_LIB_PATH" > "$REPO_ROOT/cuda.env"
        info "CUDA libraries written to cuda.env ($(echo "$CUDA_LIB_PATH" | tr ':' '\n' | wc -l) paths)"
    else
        echo "# No CUDA pip libraries detected — GPU inference will use system CUDA or CPU." \
            > "$REPO_ROOT/cuda.env"
        info "No CUDA pip libraries found — cuda.env written with no-op comment (CPU fallback)."
    fi

    sudo systemctl daemon-reload
    sudo systemctl enable birdid-uk.target
    info "Systemd services installed and enabled."
    info "Start with:  sudo systemctl start birdid-uk.target"
    info "Logs:        journalctl -u birdid-uk-capture -f"

    # If this was a systemd-only call, exit cleanly here
    if [[ "$SYSTEMD_ONLY" == "true" ]]; then
        exit 0
    fi
fi

# ── Setup wizard ──────────────────────────────────────────────────────────────

WIZARD="$REPO_ROOT/scripts/setup_wizard.py"

if [[ "$RUN_CONFIGURE" == "yes" ]]; then
    echo ""
    "$VENV/bin/python" "$WIZARD" --skip-systemd
elif [[ "$RUN_CONFIGURE" == "ask" ]]; then
    echo ""
    echo "  ─────────────────────────────────────────────"
    echo ""
    if _ask_yn "Run the setup wizard to configure your mic, location, and station name?" "y"; then
        "$VENV/bin/python" "$WIZARD" --skip-systemd
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

# ── Final tip (only when wizard was skipped / silent install) ─────────────────

if [[ "$RUN_CONFIGURE" == "no" ]]; then
    echo ""
    echo "  ─────────────────────────────────────────────"
    if [[ "$INSTALL_SYSTEMD" == "true" ]]; then
        echo "  Installation complete."
        echo ""
        echo "  Start:  sudo systemctl start birdid-uk.target"
        echo "  Logs:   journalctl -u birdid-uk-capture -f"
        echo "  Dashboard:  http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<your-ip>'):8080"
    else
        echo "  Installation complete."
        echo ""
        echo "  Start the detector:"
        echo "    source $VENV/bin/activate && python $REPO_ROOT/main.py"
        echo "  Dashboard:  http://$(hostname -I 2>/dev/null | awk '{print $1}' || echo '<your-ip>'):8080"
        echo "  Install as a service later:  bash $REPO_ROOT/install.sh --systemd-only"
    fi
    echo "  ─────────────────────────────────────────────"
    echo ""
fi

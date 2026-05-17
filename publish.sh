#!/usr/bin/env bash
# publish.sh — build the SvelteKit frontend and push a clean snapshot to the
# public distribution repo (andylink/birdid-uk), preserving commit history.
#
# Usage:
#   ./publish.sh              # uses remote named "public"
#   ./publish.sh my-remote    # uses a different remote name
#
# Prerequisites:
#   - Node.js and npm must be installed locally
#   - A git remote pointing at the public repo must exist:
#       git remote add public git@github.com:andylink/birdid-uk.git
#
# What gets published:
#   - All tracked source files (Python, Svelte source, configs) via git archive
#   - The freshly-built dashboard/frontend/dist/ (injected after build)
#   - config.toml is explicitly excluded (it is gitignored anyway)
#
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLIC_REMOTE="${1:-public}"

# ── Helpers ───────────────────────────────────────────────────────────────────

info()    { echo "  [+] $*"; }
section() { echo ""; echo "==> $*"; }
warn()    { echo "  [!] $*"; }

# ── Preflight checks ──────────────────────────────────────────────────────────

if ! command -v node &>/dev/null; then
    echo "ERROR: Node.js is not installed. Install it to build the frontend." >&2
    exit 1
fi

if ! command -v rsync &>/dev/null; then
    echo "ERROR: rsync is not installed.  Install with: sudo apt-get install rsync" >&2
    exit 1
fi

if ! git -C "$REPO_ROOT" remote get-url "$PUBLIC_REMOTE" &>/dev/null; then
    echo "ERROR: git remote '$PUBLIC_REMOTE' not found." >&2
    echo "       Add it with:" >&2
    echo "         git remote add $PUBLIC_REMOTE git@github.com:andylink/birdid-uk.git" >&2
    exit 1
fi

if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    warn "You have uncommitted changes."
    warn "The snapshot reflects the last commit, not your working tree."
    read -r -p "  Continue anyway? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || exit 0
fi

TAG="$(git -C "$REPO_ROOT" describe --tags --exact-match 2>/dev/null || true)"

if [[ -z "$TAG" ]]; then
    echo "ERROR: HEAD is not tagged.  Tag the release before publishing:" >&2
    echo "         git tag v1.2.3" >&2
    echo "         git push origin v1.2.3" >&2
    echo "       Then re-run ./publish.sh" >&2
    exit 1
fi

COMMIT_MSG="Publish $TAG ($(date -u +%Y-%m-%dT%H:%MZ))"
PUBLIC_URL="$(git -C "$REPO_ROOT" remote get-url "$PUBLIC_REMOTE")"

# ── Build frontend ────────────────────────────────────────────────────────────

section "Building SvelteKit frontend..."
(cd "$REPO_ROOT/dashboard/frontend" && npm ci --silent && npm run build)
info "Frontend built."

# ── Create snapshot ───────────────────────────────────────────────────────────

section "Creating snapshot from git archive..."
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

SNAPSHOT="$WORK/snapshot"
mkdir "$SNAPSHOT"

# Export all tracked source files (Svelte source, Python, configs, etc.)
git -C "$REPO_ROOT" archive HEAD | tar -x -C "$SNAPSHOT"

# Inject the freshly-built dist/ (gitignored in the dev repo)
mkdir -p "$SNAPSHOT/dashboard/frontend/dist"
cp -r "$REPO_ROOT/dashboard/frontend/dist/." "$SNAPSHOT/dashboard/frontend/dist/"

# Belt-and-braces: never publish personal config
rm -f "$SNAPSHOT/config.toml"

# Ensure config.toml.example is present
if [[ ! -f "$SNAPSHOT/config.toml.example" ]]; then
    cp "$REPO_ROOT/config.toml.example" "$SNAPSHOT/config.toml.example"
fi

info "Snapshot ready."

# ── Clone public repo and sync ────────────────────────────────────────────────

section "Cloning public repo ($PUBLIC_URL)..."
PUBLIC_CLONE="$WORK/public"
git clone --quiet "$PUBLIC_URL" "$PUBLIC_CLONE"
info "Cloned."

section "Syncing snapshot into public repo..."
# rsync: mirror snapshot into clone, preserving the .git directory
rsync -a --delete --exclude='.git' "$SNAPSHOT/" "$PUBLIC_CLONE/"

# ── Commit and push ───────────────────────────────────────────────────────────

cd "$PUBLIC_CLONE"

if git diff --staged --quiet && git diff --quiet && [[ -z "$(git status --short)" ]]; then
    warn "Nothing changed — public repo is already up to date."
    exit 0
fi

git add -A

if git diff --staged --quiet; then
    warn "Nothing to commit — public repo is already up to date."
    exit 0
fi

git commit -q -m "$COMMIT_MSG"
git push origin main -q

echo ""
echo "==> Published successfully."
echo "    Remote : $PUBLIC_URL"
echo "    Commit : $COMMIT_MSG"
echo ""
if [[ -n "$TAG" ]]; then
    echo "    Create a GitHub release for this tag:"
    echo "      gh release create $TAG --title '$TAG' --notes '' --repo andylink/birdid-uk"
else
    echo "    Tag a release with:"
    echo "      git tag vX.Y.Z && git push origin vX.Y.Z"
    echo "    Then re-run this script and create a release:"
    echo "      gh release create vX.Y.Z --title 'vX.Y.Z' --notes '' --repo andylink/birdid-uk"
fi
echo ""

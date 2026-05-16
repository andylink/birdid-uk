#!/usr/bin/env bash
# publish.sh — build the SvelteKit frontend and push a clean snapshot to the
# public distribution repo (BirdID-UK).
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
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PUBLIC_REMOTE="${1:-public}"

# ── Preflight checks ──────────────────────────────────────────────────────────

if ! command -v node &>/dev/null; then
    echo "ERROR: Node.js is not installed. Install it to build the frontend." >&2
    exit 1
fi

if ! git -C "$REPO_ROOT" remote get-url "$PUBLIC_REMOTE" &>/dev/null; then
    echo "ERROR: git remote '$PUBLIC_REMOTE' not found." >&2
    echo "       Add it with:" >&2
    echo "         git remote add $PUBLIC_REMOTE git@github.com:andylink/birdid-uk.git" >&2
    exit 1
fi

if [[ -n "$(git -C "$REPO_ROOT" status --porcelain)" ]]; then
    echo "WARNING: You have uncommitted changes. The snapshot will reflect the" \
         "last commit, not your working tree."
    read -r -p "Continue anyway? [y/N] " answer
    [[ "$answer" =~ ^[Yy]$ ]] || exit 0
fi

# ── Build frontend ─────────────────────────────────────────────────────────────

echo ""
echo "==> Building SvelteKit frontend..."
(cd "$REPO_ROOT/dashboard/frontend" && npm ci --silent && npm run build)
echo "    Done."

# ── Create clean snapshot ─────────────────────────────────────────────────────

echo ""
echo "==> Creating clean snapshot from git archive..."
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# git archive exports only tracked files, honouring .gitignore.
# config.toml is gitignored so it will NOT be included.
git -C "$REPO_ROOT" archive HEAD | tar -x -C "$WORK"

# Inject the freshly built frontend dist (not tracked in the private repo)
cp -r "$REPO_ROOT/dashboard/frontend/dist" "$WORK/dashboard/frontend/dist"

# Belt-and-braces: ensure personal config is never included
rm -f "$WORK/config.toml"

# Ensure config.toml.example is present
if [[ ! -f "$WORK/config.toml.example" ]]; then
    cp "$REPO_ROOT/config.toml.example" "$WORK/config.toml.example"
fi

# ── Push to public remote ─────────────────────────────────────────────────────

PUBLIC_URL="$(git -C "$REPO_ROOT" remote get-url "$PUBLIC_REMOTE")"
COMMIT_MSG="Publish $(date -u +%Y-%m-%dT%H:%MZ)"

echo ""
echo "==> Pushing to $PUBLIC_URL ..."
cd "$WORK"
git init -q
git checkout -q -b main
git add -A
git commit -q -m "$COMMIT_MSG"
git remote add public "$PUBLIC_URL"
git push public main --force -q

echo ""
echo "==> Published successfully."
echo "    Remote : $PUBLIC_URL"
echo "    Commit : $COMMIT_MSG"
echo ""
echo "    Next steps if this is a notable release:"
echo "      gh release create vX.Y.Z --title 'vX.Y.Z' --notes '' --repo andylink/birdid-uk"

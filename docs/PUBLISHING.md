# BirdID-UK — Publishing Guide

How to release an update to the public distribution repo
(`andylink/birdid-uk`) from the private dev repo (`andylink/birdid-uk-dev`).

---

## One-time setup

This only needs to be done once per development machine.

### 1. Add the `public` remote

```sh
git remote add public git@github.com:andylink/birdid-uk.git
```

Verify:

```sh
git remote -v
# origin   git@github.com:andylink/birdid-uk-dev.git (fetch)
# origin   git@github.com:andylink/birdid-uk-dev.git (push)
# public   git@github.com:andylink/birdid-uk.git     (fetch)
# public   git@github.com:andylink/birdid-uk.git     (push)
```

### 2. Ensure Node.js and rsync are installed

```sh
node --version    # must be 20+
rsync --version   # ships with most Linux/macOS installs
```

---

## Release workflow

Every publish must start from a tagged commit.  Use
[semantic versioning](https://semver.org) — `vMAJOR.MINOR.PATCH`.

| Change type | Example | Version bump |
|---|---|---|
| Bug fix, minor tweak | config parsing fix | PATCH — `v1.0.1` |
| New feature, config option | MQTT support | MINOR — `v1.1.0` |
| Breaking change (config format, API) | schema migration required | MAJOR — `v2.0.0` |

---

### Step 1 — Finish and commit your changes

```sh
# Make sure everything is committed on main
git status
git add -A
git commit -m "feat: describe your change"
git push origin main
```

### Step 2 — Tag the release

```sh
git tag v1.2.3
git push origin v1.2.3
```

> The tag must be on HEAD before running `publish.sh`.  If you forget,
> `publish.sh` will tell you exactly what to run and exit cleanly.

### Step 3 — Publish

```sh
./publish.sh
```

This will:

1. Verify HEAD is tagged
2. Build the SvelteKit frontend (`npm ci && npm run build`)
3. Clone `andylink/birdid-uk` into a temp directory
4. Mirror all tracked source files + the built `dist/` into the clone
5. Commit with message `Publish v1.2.3 (2026-01-15T10:30Z)`
6. Push to `andylink/birdid-uk main` (normal push, history preserved)

At the end the script prints the `gh release create` command for step 4.

### Step 4 — Create the GitHub release

Copy and run the command printed by `publish.sh`:

```sh
gh release create v1.2.3 \
  --title "v1.2.3" \
  --notes "Brief description of what changed." \
  --repo andylink/birdid-uk
```

Or open `https://github.com/andylink/birdid-uk/releases/new` in a browser
and fill in the form.

---

## What ends up in the public repo

| Content | Included | Notes |
|---|---|---|
| Python source (`*.py`) | Yes | All tracked files via `git archive` |
| Svelte source (`src/`) | Yes | Open source — full code included |
| Built frontend (`dist/`) | Yes | Injected after local build |
| `config.toml` | **No** | Gitignored; personal settings never published |
| `config.toml.example` | Yes | Template for new installs |
| `node_modules/` | **No** | Never tracked |
| Dev history / WIP branches | **No** | Public repo only gets the published snapshot |

---

## Hotfix workflow

If you need to fix a bug in the current release without shipping unfinished
work from `main`:

```sh
# Create a hotfix branch from the release tag
git checkout -b hotfix/v1.2.4 v1.2.3
# ... make the fix ...
git commit -m "fix: ..."
git push origin hotfix/v1.2.4

# Merge back to main
git checkout main
git merge --no-ff hotfix/v1.2.4
git push origin main

# Tag and publish from main
git tag v1.2.4
git push origin v1.2.4
./publish.sh
```

---

## Troubleshooting

**`ERROR: HEAD is not tagged`**

You haven't tagged the commit yet.  Run:

```sh
git tag v1.2.3
git push origin v1.2.3
```

**`ERROR: git remote 'public' not found`**

Re-do the one-time setup step above.

**`Nothing changed — public repo already up to date`**

The snapshot is identical to the last publish.  Make sure your changes are
committed and the tag points to the new commit.

**Frontend build fails**

```sh
cd dashboard/frontend
npm ci
npm run build    # error output will be shown here
```

Fix any TypeScript / build errors then re-run `./publish.sh`.

**Push rejected (non-fast-forward)**

Someone else pushed to `andylink/birdid-uk` directly.  Pull first:

```sh
cd /tmp  &&  git clone git@github.com:andylink/birdid-uk.git  # inspect
```

In practice this shouldn't happen — only `publish.sh` writes to the public
repo.  If the history has diverged, contact the repo owner.

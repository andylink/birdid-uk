# BirdID-UK — Beta Fix Plan

Generated: 2026-05-19  
Scope: Full codebase review across detector, dashboard API, filters, inference, frontend, and test suite.

Issues are grouped into four priority tiers. Each item includes the affected file(s), a short description, and an estimated effort.

---

## Table of Contents

1. [Critical — Fix Before Going Live](#critical--fix-before-going-live)
2. [High — Fix Before Beta](#high--fix-before-beta)
3. [Medium — Fix in First Post-Launch Iteration](#medium--fix-in-first-post-launch-iteration)
4. [Low — Clean Up When Time Allows](#low--clean-up-when-time-allows)
5. [Test & CI Improvements](#test--ci-improvements)
6. [Effort Summary](#effort-summary)

---

## Critical — Fix Before Going Live

These issues cause data loss, exploitable security vulnerabilities, or guaranteed runtime crashes.

---

## High — Fix Before Beta

These issues are exploitable, user-visible bugs, or will cause incorrect behaviour in production.

---

### H2. SSE detection stream has no authentication

**File:** `dashboard/app.py:161–164`  
**Effort:** ~10 min

`GET /stream/detections` is accessible to any unauthenticated client on the network.

**Fix:** If the dashboard read endpoints are intended to be public (single-user home use), document this explicitly. If not, add `Depends(get_current_admin)`:
```python
@app.get("/stream/detections")
async def stream_detections(admin=Depends(get_current_admin)):
    ...
```
At minimum, decide and document the intended access policy.

---

### H3. No brute-force protection on admin login

**File:** `dashboard/routes/auth.py:29–46`  
**Effort:** ~30 min

No rate limiting, no lockout, no artificial delay on failed login attempts. An attacker with network access can make unlimited password guesses.

**Fix:** Add `slowapi` rate limiting, or implement a simple in-process counter:
```python
pip install slowapi
```
```python
from slowapi import Limiter
from slowapi.util import get_remote_address
limiter = Limiter(key_func=get_remote_address)

@router.post("/login")
@limiter.limit("5/minute")
async def login(request: Request, ...):
    ...
```
Add `app.state.limiter = limiter` and `SlowAPIMiddleware` to `app.py`.

---

### H4. `window_blocks` integer truncation shrinks inference window

**File:** `detector.py:480`  
**Effort:** ~5 min

`int(model.window_seconds)` truncates before the floor division, silently shrinking the inference window if `window_seconds` has a fractional component.

**Fix:**
```python
# Replace:
window_blocks = int(model.window_seconds) // cfg.audio.hop_seconds

# With:
import math
window_blocks = math.ceil(model.window_seconds / cfg.audio.hop_seconds)
```

---

### H5. No startup validation that `hop_seconds` divides `window_seconds`

**File:** `detector.py` (startup), `config.py`  
**Effort:** ~10 min

A user setting `hop_seconds = 2` with a 3-second BirdNET window silently runs inference on an undersized buffer.

**Fix:** Add to `detector.main()` after the model is loaded:
```python
remainder = model.window_seconds % cfg.audio.hop_seconds
if remainder > 0.01:
    raise ValueError(
        f"audio.hop_seconds ({cfg.audio.hop_seconds}) must divide evenly into "
        f"model window_seconds ({model.window_seconds}). "
        f"Try hop_seconds = 1 or hop_seconds = 3."
    )
```

---

### H6. SSE client only subscribes to `'detection'` events

**File:** `dashboard/frontend/src/lib/sse.ts:28–35`  
**Effort:** ~15 min

The public `on(event, handler)` API accepts any event name, but the `EventSource` only ever calls `addEventListener('detection', ...)`. All other event types are silently dropped.

**Fix:** Wire each registered event to the underlying `EventSource`:
```ts
on(event: string, handler: (data: unknown) => void): void {
    this._handlers.set(event, handler);
    if (this._source) {
        this._source.addEventListener(event, (e: MessageEvent) => {
            handler(JSON.parse(e.data));
        });
    }
}
```
And replay all registered handlers when reconnecting.

---

### H7. `_status_excluded` crashes on `null` British list status

**File:** `filters/species_filter.py:115,219`  
**Effort:** ~5 min

`sp.get("british_list_status", "")` returns `None` when the JSON field is `null`, not `""`. Calling `.split(",")` on `None` raises `AttributeError`.

**Fix:**
```python
# Replace in both build_birdnet_to_bto_map and build_bou_allowed_set:
status = sp.get("british_list_status", "")

# With:
status = sp.get("british_list_status") or ""
```

---

### H8. Nocturnal filter catches only `FileNotFoundError`

**File:** `filters/nocturnal_filter.py:108–112`  
**Effort:** ~5 min

A malformed JSON file or permission error will crash startup with an unhandled exception. `SeasonalFilter` correctly catches `(json.JSONDecodeError, OSError)`.

**Fix:**
```python
# Replace:
except FileNotFoundError:

# With:
except (FileNotFoundError, json.JSONDecodeError, OSError):
```

---

### H9. CSV export date filter ignores timezone

**File:** `dashboard/routes/admin.py:81–86`  
**Effort:** ~20 min

The CSV export compares raw date strings against UTC timestamps, bypassing the `_day_utc_bounds()` conversion used everywhere else. Users in BST (UTC+1) get results shifted by one hour.

**Fix:** Apply the same timezone conversion as the detections list endpoint:
```python
from dashboard.utils import _day_utc_bounds
from dashboard.config import LOCAL_TZ
import zoneinfo

if date_from:
    start_utc, _ = _day_utc_bounds(date.fromisoformat(date_from), LOCAL_TZ)
    clauses.append("timestamp >= :date_from")
    params["date_from"] = start_utc.isoformat()
if date_to:
    _, end_utc = _day_utc_bounds(date.fromisoformat(date_to), LOCAL_TZ)
    clauses.append("timestamp < :date_to")
    params["date_to"] = end_utc.isoformat()
```

---

### H10. `reseed_species` can leave `species_info` table empty

**File:** `dashboard/routes/admin.py:280–321`  
**Effort:** ~20 min

The endpoint deletes all rows then inserts new ones. If JSON parsing or the bulk insert fails midway, the table is permanently empty.

**Fix:** Wrap both operations in a single transaction and handle errors before deleting:
```python
entries = json.loads(_JSON_PATH.read_text(encoding="utf-8"))  # parse FIRST
rows = [...]  # build rows BEFORE any DB writes
async with db.begin():
    await db.execute(text("DELETE FROM species_info"))
    await db.execute(text("INSERT INTO species_info ..."), rows)
```

---

### H11. `<button>` nested inside `<a>` — invalid HTML

**Files:** `dashboard/frontend/src/lib/components/species/SpeciesCard.svelte`, `SpeciesRow.svelte`  
**Effort:** ~30 min

Interactive content cannot be nested per the HTML spec. Breaks keyboard navigation, screen readers, and produces undefined browser behaviour (WCAG 4.1.1).

**Fix:** Restructure so the `<button>` is a sibling of the `<a>`, not a child. Use `position: relative` on the parent and `position: absolute` on the button overlay if visual overlap is needed.

---

### H13. `TimeOfDayChart` uses browser-local time instead of site timezone

**File:** `dashboard/frontend/src/lib/components/analytics/TimeOfDayChart.svelte:36–38`  
**Effort:** ~10 min

The chart builds its "today" date string using `new Date().toISOString()` (UTC/browser-local), instead of the configured site timezone. Users in non-UK timezones see wrong date-boundary results.

**Fix:** Import and use `localToday()` from `$lib/time.ts`:
```ts
import { localToday } from '$lib/time';
// Replace the manual date construction with:
const today = localToday();
```

---

## Medium — Fix in First Post-Launch Iteration

---

### M1. `capture_buffer` float32 audio silently zeroed

**File:** `capture_buffer.py:41,62–67`  
**Effort:** ~15 min

The ring buffer is allocated as `np.int16`. If any audio source returns `float32` chunks, the silent cast clips values to 0, producing completely silent clips.

**Fix:** Validate or explicitly convert dtype in `write()`:
```python
def write(self, chunk: np.ndarray) -> None:
    if chunk.dtype != np.int16:
        chunk = np.clip(chunk * 32767, -32768, 32767).astype(np.int16)
    ...
```

---

### M2. `capture_buffer` edge case when `start_pos == end_pos`

**File:** `capture_buffer.py:109–117`  
**Effort:** ~10 min

When `length_samples` equals buffer capacity exactly, `start_pos == end_pos` and the wrap-around branch returns the full buffer capacity rather than the correct slice. Add an explicit guard:
```python
if length_samples == 0:
    return np.array([], dtype=np.int16)
if start_pos < end_pos:
    return buf[start_pos:end_pos].copy()
else:
    return np.concatenate([buf[start_pos:], buf[:end_pos]])
```

---

### M3. `_dedup_recent` dict grows without bound

**File:** `detector.py:104,172–181`  
**Effort:** ~15 min

Entries are added but never removed. Over a long uptime this is a slow memory leak.

**Fix:** Evict stale entries in `_check_dedup()`:
```python
def _check_dedup(...):
    cutoff = ts - timedelta(seconds=dedup_window_seconds * 2)
    stale = [k for k, v in _dedup_recent.items() if max(v) < cutoff]
    for k in stale:
        del _dedup_recent[k]
    ...
```

---

### M4. `matplotlib` figure leak on exception

**File:** `spectrogram.py:48–61`  
**Effort:** ~10 min

If `librosa.display.specshow` or `plt.savefig` raises, `plt.close(fig)` is never called. Matplotlib registers open figures globally, leading to a handle leak over many failed renders.

**Fix:**
```python
fig, ax = plt.subplots(...)
try:
    # ... render ...
    plt.savefig(...)
finally:
    plt.close(fig)
```

---

### M5. `verification_status` and `period` params not validated

**Files:** `dashboard/routes/detections.py:39`, `dashboard/utils.py:169`  
**Effort:** ~20 min

Invalid values return empty 200 responses rather than 422. Use `Literal` types or `Enum` in the query declarations:
```python
from typing import Literal
verification_status: Optional[Literal["unverified","auto","cv","human"]] = None
period: Optional[Literal["today","7d","30d","90d","365d","all","custom"]] = None
```

---

### M6. `date.fromisoformat()` calls missing `try/except`

**Files:** `dashboard/routes/analytics.py:43,123`, `dashboard/routes/detections.py:60`  
**Effort:** ~20 min

Bad date strings cause unhandled `ValueError` → 500 responses instead of clean 422s.

**Fix:** Wrap each call:
```python
try:
    d = date.fromisoformat(date_str)
except ValueError:
    raise HTTPException(status_code=422, detail=f"Invalid date format: {date_str!r}")
```

---

### M7. SSE stream holds a DB connection per client

**File:** `dashboard/stream.py:44`  
**Effort:** ~30 min

Each SSE client holds an open connection for its lifetime. With `pool_size=5, max_overflow=10`, 15 simultaneous clients exhaust the pool. Move the connection acquisition inside the poll loop:

```python
async def detection_generator():
    last_id = ...
    while True:
        async with get_engine().connect() as conn:
            rows = (await conn.execute(...)).mappings().all()
        for row in rows:
            yield ...
        await asyncio.sleep(SSE_POLL_SECONDS)
```

---

### M8. SSE stream — no reconnect support and no keepalive

**File:** `dashboard/stream.py`  
**Effort:** ~20 min

Clients miss detections on reconnect (no `Last-Event-ID` support), and idle connections are dropped by proxies after 30–60 s (no keepalive).

**Fix:**
- Accept `last_event_id` from the SSE framework and initialise `last_id` from it.
- Periodically yield a comment ping: `yield {"event": "ping", "data": ""}` (or the sse-starlette equivalent) when no detections arrive.

---

### M9. `asyncio.get_event_loop()` deprecated

**File:** `dashboard/routes/admin.py:244`  
**Effort:** ~2 min

```python
# Replace:
loop = asyncio.get_event_loop()
deleted = await loop.run_in_executor(None, run_cleanup)

# With:
deleted = await asyncio.to_thread(run_cleanup)
```

---

### M10. `INSERT OR REPLACE` is SQLite-only

**File:** `dashboard/routes/admin.py:307`  
**Effort:** ~15 min

Fails silently or raises on PostgreSQL. Either add a `DB_TYPE` guard or use `text()` with dialect detection:
```python
if DB_TYPE == "sqlite":
    stmt = "INSERT OR REPLACE INTO species_info ..."
else:
    stmt = "INSERT INTO species_info ... ON CONFLICT (name) DO UPDATE SET ..."
```

---

### M11. `OperationalError` swallowed silently in SSE generator

**File:** `dashboard/stream.py:76–77`  
**Effort:** ~2 min

```python
# Replace:
except OperationalError:
    rows = []

# With:
except OperationalError:
    _log.warning("SSE stream: DB OperationalError (table may not exist yet), retrying")
    rows = []
```

---

### M12. `min_detections`, lat/lon, `on_disagree`, source name not validated at startup

**Files:** `config.py:490–493,556,600,708–713`  
**Effort:** ~20 min

- `min_detections < 1` would fire a confirmation on every single detection.
- `lat = 999` / `lon = 999` produce nonsensical nocturnal filter windows.
- `on_disagree = "ignore"` silently falls through to `"drop"`.
- Source `name` containing `/` creates invalid clip paths.

**Fix:** Add validation in `config.py` after parsing each section:
```python
if not (-90 <= lat <= 90):
    raise ValueError(f"location.lat must be between -90 and 90, got {lat}")
if not (-180 <= lon <= 180):
    raise ValueError(f"location.lon must be between -180 and 180, got {lon}")
if defaults.min_detections < 1:
    raise ValueError("detection.min_detections must be >= 1")
if cv_on_disagree not in ("drop", "flag", "save"):
    raise ValueError(f"cross_validation.on_disagree must be 'drop', 'flag', or 'save'")
if not re.match(r'^[A-Za-z0-9_\-]+$', source_name):
    raise ValueError(f"source.name '{source_name}' contains invalid characters")
```

---

### M13. Fetch errors silently swallowed in weather and analytics pages

**Files:** `dashboard/frontend/src/routes/weather/+page.svelte`, `src/routes/analytics/+page.svelte`  
**Effort:** ~20 min

`.catch(() => {})` discards errors and leaves the user with a blank chart and no explanation.

**Fix:** Add an `error` state and display a message:
```svelte
let error = $state<string | null>(null);

// In fetch:
.catch((e) => { error = 'Failed to load data. Please refresh.'; });

// In template:
{#if error}<p class="text-red-500">{error}</p>{/if}
```

---

### M14. BirdNET inference has no timeout and silences FFmpeg errors

**Files:** `inference/birdnet.py:108`, `audio/rtsp_source.py:131`  
**Effort:** ~30 min

- BirdNET has no subprocess timeout. A hang holds `inference_lock` indefinitely, blocking all sources.
- FFmpeg stderr is `DEVNULL`, making connection failures invisible in logs.

**Fix for BirdNET:** Wrap the `analyze()` call in a `concurrent.futures.ThreadPoolExecutor` with a `timeout` and cancel/raise if it exceeds a configurable limit (e.g. 30 s).

**Fix for RTSP:** Replace `stderr=subprocess.DEVNULL` with `stderr=subprocess.PIPE` and log the stderr content when the process exits non-zero.

---

### M15. `vite.config.ts` health-check plugin should not be committed

**File:** `dashboard/frontend/vite.config.ts`  
**Effort:** ~5 min

The `ignoreApiV2Plugin` block is an OpenCode development artefact. Remove it from the committed file, or move it to a local-only override (e.g. `vite.config.local.ts` added to `.gitignore`).

---

## Low — Clean Up When Time Allows

---

### L1. Extract common `_migrate_*` boilerplate

**File:** `database.py:231–408`  
**Effort:** ~45 min

Five near-identical migration functions (~100 lines of boilerplate). Extract:
```python
def _add_columns_if_missing(engine, table: str, columns: dict[str, str]) -> None:
    with engine.connect() as conn:
        existing = {row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))}
        with engine.begin() as txn:
            for col_name, col_type in columns.items():
                assert col_name.isidentifier(), f"Unsafe column name: {col_name}"
                if col_name not in existing:
                    txn.execute(text(f"ALTER TABLE {table} ADD COLUMN {col_name} {col_type}"))
```

---

### L2. Remove `species_name` duplicate parameter in `CrossValidator.validate()`

**File:** `cross_validate.py:130,144–145`  
**Effort:** ~10 min

`species_name` is an alias for `primary_species` that is never used differently. Remove it and use `primary_species` directly.

---

### L3. Deduplicate `_normalise_bools` helper

**Files:** `dashboard/routes/detections.py:21–30`, `dashboard/routes/species.py:111–120`  
**Effort:** ~10 min

Move the shared function to `dashboard/utils.py` and import it from both files.

---

### L4. `O(n)` species lookup in `NocturnalFilter`

**File:** `filters/nocturnal_filter.py:149–153`  
**Effort:** ~10 min

Replace the linear scan with a lowercase dict built once in `__init__`:
```python
self._windows_lower = {k.lower(): v for k, v in self._windows.items()}

def _get_window(self, species: str) -> dict | None:
    return self._windows_lower.get(species.lower())
```

---

### L5. Align `SeasonalFilter` to case-insensitive lookup

**File:** `filters/seasonal_filter.py:130`  
**Effort:** ~10 min

`SeasonalFilter.check()` uses a case-sensitive dict lookup while `NocturnalFilter` is case-insensitive. Normalise keys to lowercase in `__init__` for consistency.

---

### L6. `sd.wait()` ignores `stop_event` on device removal

**File:** `audio/sounddevice_source.py:73–74`  
**Effort:** ~30 min

`sd.wait()` blocks indefinitely if the audio device is removed. Replace with a persistent `sd.InputStream` and callback to keep the thread responsive to `stop_event`.

---

### L7. `_dedup_recent` variable name and type hint clarification

**File:** `detector.py`  
**Effort:** ~5 min

`_deduplicated: bool | None` only ever takes `None` or `True`, never `False`. Rename the variable or add a comment: `# None = not a duplicate; True = flagged as cross-source duplicate`.

---

### L8. Variable name `l` in config.py

**File:** `config.py:622`  
**Effort:** ~2 min

`l = raw.get("log", {})` — `l` is visually ambiguous with `1`. Rename to `log_raw`.

---

### L9. Per-page `<title>` tags in frontend

**File:** `dashboard/frontend/src/app.html` and all route `+page.svelte` files  
**Effort:** ~20 min

The `<title>` is hardcoded as `"Bird Detector"`. Add `<svelte:head><title>...</title></svelte:head>` to each route.

---

### L10. Add missing nocturnal species to `uk_nocturnal_filter.json`

**File:** `filters/uk_nocturnal_filter.json`  
**Effort:** ~1 hour (research + data entry)

Common UK species with primarily nocturnal/crepuscular vocalisations that are missing and can generate daytime false-positives:
- **Common Snipe** — drumming/chipping almost exclusively at dusk and night
- **Water Rail** — groaning/squealing calls primarily nocturnal
- **Grasshopper Warbler** — reeling song mainly at night and early morning
- **Common Quail** — "wet-my-lips" call mainly at dusk/night

---

### L11. `_sun_cache` eviction comment is wrong (off-by-one)

**File:** `filters/nocturnal_filter.py:138–141`  
**Effort:** ~5 min

The comment says "Keep today and yesterday" but the cutoff keeps 3 days. Fix the cutoff:
```python
cutoff = local_date - timedelta(days=1)  # evict anything older than yesterday
```

---

### L12. Perch `np.exp` computed twice in softmax

**File:** `inference/perch.py:392–393`  
**Effort:** ~2 min

```python
# Replace:
shifted = logits - logits.max()
probs   = np.exp(shifted) / np.exp(shifted).sum()

# With:
shifted     = logits - logits.max()
exp_shifted = np.exp(shifted)
probs       = exp_shifted / exp_shifted.sum()
```

---

## Test & CI Improvements

---

### T1. Add authentication tests — most critical gap

**Files:** New: `tests/integration/test_auth_api.py`  
**Effort:** ~2 hours

The entire auth system has zero test coverage. At minimum, add:
- `POST /api/v1/auth/login` — correct password sets cookie, wrong password returns 401
- `POST /api/v1/auth/logout` — cookie is cleared
- `GET /api/v1/auth/me` — returns `authenticated: false` without cookie
- All admin routes return **401 without a valid session** (this is the highest-value single test)

---

### T2. Fix broken concurrent-access test in `test_capture_buffer.py`

**File:** `tests/unit/test_capture_buffer.py` (concurrent test)  
**Effort:** ~20 min

The `errors` list in the concurrent read/write test is never populated because the worker functions have no `try/except`. Thread exceptions are silently swallowed and the assertion always passes.

**Fix:** Wrap worker bodies in `try/except Exception as e: errors.append(e)`.

---

### T3. Add test coverage for `detector.py` pipeline steps

**Files:** New: `tests/unit/test_detector_pipeline.py`  
**Effort:** ~3 hours

The most complex module has zero coverage. Priority tests to add:
- `_check_dedup()` — same species/source within window → `True`; different species → `False`
- `_Pending` confirmation: hit count reaches `min_detections` within window → confirmed
- `_Pending` expiry: hit count does not reach threshold before `expires_at` → discarded
- `_classify_loop` filter steps: mock inferencer returning a filtered species → no save triggered

---

### T4. Add coverage threshold to CI

**File:** `.github/workflows/tests.yml`  
**Effort:** ~5 min

```yaml
- name: Run tests
  run: pytest --cov=. --cov-report=term-missing --cov-fail-under=60
```
Start at 60% and raise as coverage improves. Without this, CI stays green regardless of how much code is untested.

---

### T5. Add tests before publish in CI

**File:** `.github/workflows/publish.yml`  
**Effort:** ~15 min

Add a test job that the publish job depends on:
```yaml
jobs:
  test:
    uses: ./.github/workflows/tests.yml
  publish:
    needs: test
    ...
```

---

### T6. Add pip caching to CI

**File:** `.github/workflows/tests.yml`  
**Effort:** ~5 min

```yaml
- uses: actions/setup-python@v5
  with:
    python-version: "3.11"
    cache: 'pip'
```

---

### T7. Fix wall-clock-dependent tests

**File:** `tests/unit/test_dashboard_utils.py`  
**Effort:** ~30 min

`test_7d_start_is_6_days_ago` and `test_30d_start_is_29_days_ago` can fail at midnight UTC. Replace `datetime.now()` calls in assertions with a monkeypatched frozen clock.

---

### T8. Add `privacy_filter` unit tests

**Files:** New tests in `tests/unit/`  
**Effort:** ~1 hour

`PrivacyFilter.scan()` is on the critical save path and has zero coverage. Test: voiced fraction above threshold → `True`; below threshold → `False`; disabled filter always passes.

---

### T9. Annotate CI tag requirement

**File:** `.github/workflows/publish.yml`  
**Effort:** ~5 min

`gh release create --verify-tag` requires an annotated (signed) tag. Lightweight tags (the default `git tag v1.0.0`) will fail. Add to the publish workflow comment and to the `PUBLISHING.md` docs: _"Tags must be annotated: `git tag -a v1.0.0 -m 'Release v1.0.0'`"_.

---

## Effort Summary

| Tier | Count | Estimated Total |
|------|-------|----------------|
| Critical (C3–C8) | 6 items | ~1 hour |
| High (H2–H13) | 11 items | ~3 hours |
| Medium (M1–M15) | 15 items | ~5 hours |
| Low (L1–L12) | 12 items | ~3 hours |
| Tests & CI (T1–T9) | 9 items | ~8 hours |
| **Total** | **53 items** | **~20 hours** |

### Recommended Sprint Order for Beta Launch

**Week 1 — Blockers (Critical + selected High):**
C3, C4, C5, C6, C7, C8, H2, H7, H8, H9, H10, H11, H13

**Week 2 — Quality & Correctness (remaining High + key Medium):**
H3, H4, H5, H6, M4, M5, M6, M7, M8, M13

**Week 3 — Tests, CI, and remaining Medium:**
T1, T2, T4, T5, T6, M1, M2, M3, M9, M10, M11, M12, M14, M15

**Ongoing — Low priority and data improvements:**
L1–L12, T3, T7–T9

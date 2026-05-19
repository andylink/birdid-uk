# BirdID-UK — Beta Fix Plan

Generated: 2026-05-19  
Scope: Full codebase review across detector, dashboard API, filters, inference, frontend, and test suite.

Issues are grouped into four priority tiers. Each item includes the affected file(s), a short description, and an estimated effort.

---

## Table of Contents

5. [Test & CI Improvements](#test--ci-improvements)

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


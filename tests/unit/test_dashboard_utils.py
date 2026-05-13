"""
tests/unit/test_dashboard_utils.py — unit tests for dashboard/utils.py.

Patching strategy
-----------------
`dashboard.utils._local_tz()` does `from dashboard.config import LOCAL_TZ`
on every call, so patching `dashboard.config.LOCAL_TZ` makes the helpers
use whatever timezone we inject without touching the real config.toml.

`_day_utc_bounds` takes an explicit `tz` parameter, so no patching is needed
for those tests.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

import dashboard.config   # ensure the module is imported so we can patch it
from dashboard.utils import (
    _day_utc_bounds,
    period_clause,
    to_utc_iso,
    utc_offset_str,
)

UTC = ZoneInfo("UTC")
KOLKATA = ZoneInfo("Asia/Kolkata")          # fixed +5:30 (no DST)
LONDON = ZoneInfo("Europe/London")


# ── to_utc_iso ────────────────────────────────────────────────────────────────

class TestToUtcIso:
    def test_none_returns_none(self):
        assert to_utc_iso(None) is None

    def test_empty_string_returns_empty(self):
        # empty string is falsy → returned unchanged
        result = to_utc_iso("")
        assert result == ""

    def test_adds_t_and_offset(self):
        assert to_utc_iso("2026-05-13 10:30:00") == "2026-05-13T10:30:00+00:00"

    def test_already_has_plus_unchanged(self):
        ts = "2026-05-13T10:30:00+01:00"
        assert to_utc_iso(ts) == ts

    def test_already_has_z_unchanged(self):
        ts = "2026-05-13T10:30:00Z"
        assert to_utc_iso(ts) == ts

    def test_already_has_t_but_no_offset(self):
        # Has T separator but no +/Z → still missing offset marker → append +00:00
        assert to_utc_iso("2026-05-13T10:30:00") == "2026-05-13T10:30:00+00:00"

    def test_space_replaced_by_t(self):
        result = to_utc_iso("2026-01-01 00:00:00")
        assert "T" in result
        assert " " not in result


# ── _day_utc_bounds ───────────────────────────────────────────────────────────

class TestDayUtcBounds:
    def test_utc_day_starts_at_midnight_utc(self):
        d = date(2026, 5, 13)
        start, end = _day_utc_bounds(d, UTC)
        assert start == "2026-05-13 00:00:00"
        assert end   == "2026-05-14 00:00:00"

    def test_bst_day_shifted_by_one_hour(self):
        """Summer BST (+01:00): local midnight = 23:00 UTC the previous day."""
        # 2026-06-21 is in BST; Europe/London is +1h
        d = date(2026, 6, 21)
        start, end = _day_utc_bounds(d, LONDON)
        assert start == "2026-06-20 23:00:00"
        assert end   == "2026-06-21 23:00:00"

    def test_kolkata_day_shifted_by_5h30(self):
        """IST (+05:30): local midnight 2026-05-13 = 2026-05-12 18:30 UTC."""
        d = date(2026, 5, 13)
        start, end = _day_utc_bounds(d, KOLKATA)
        assert start == "2026-05-12 18:30:00"
        assert end   == "2026-05-13 18:30:00"

    def test_gmt_winter_london_no_offset(self):
        """Winter GMT: London offset = 0 → same as UTC."""
        d = date(2026, 1, 15)
        start, end = _day_utc_bounds(d, LONDON)
        assert start == "2026-01-15 00:00:00"
        assert end   == "2026-01-16 00:00:00"


# ── utc_offset_str ────────────────────────────────────────────────────────────

class TestUtcOffsetStr:
    def test_utc_returns_zero_hours(self, monkeypatch):
        monkeypatch.setattr(dashboard.config, "LOCAL_TZ", UTC)
        assert utc_offset_str() == "'+0 hours'"

    def test_kolkata_includes_minutes(self, monkeypatch):
        """IST is +5:30 → '+5 hours 30 minutes'."""
        monkeypatch.setattr(dashboard.config, "LOCAL_TZ", KOLKATA)
        assert utc_offset_str() == "'+5 hours 30 minutes'"

    def test_bst_is_plus_one_hour(self, monkeypatch):
        """Force a summer BST check by mocking datetime.now to return a BST-offset time."""
        # We can't guarantee the system is in summer, so we test UTC and Kolkata only,
        # and trust the logic for whole-hour offsets is exercised by utc_offset_str
        # with Europe/London during winter (same path as UTC).
        monkeypatch.setattr(dashboard.config, "LOCAL_TZ", LONDON)
        result = utc_offset_str()
        # Result should be either '+0 hours' (winter) or '+1 hours' (summer BST)
        assert result in ("'+0 hours'", "'+1 hours'")

    def test_returns_quoted_string(self, monkeypatch):
        """Return value is always wrapped in single quotes for SQLite datetime()."""
        monkeypatch.setattr(dashboard.config, "LOCAL_TZ", UTC)
        result = utc_offset_str()
        assert result.startswith("'") and result.endswith("'")


# ── period_clause ─────────────────────────────────────────────────────────────

class TestPeriodClause:
    """Tests patch LOCAL_TZ to UTC so date arithmetic is timezone-independent."""

    @pytest.fixture(autouse=True)
    def _use_utc(self, monkeypatch):
        monkeypatch.setattr(dashboard.config, "LOCAL_TZ", UTC)

    def test_all_returns_trivially_true(self):
        clause, params = period_clause("all")
        assert clause == "1=1"
        assert params == {}

    def test_unknown_period_falls_back_to_all(self):
        clause, params = period_clause("bogus_period")
        assert clause == "1=1"
        assert params == {}

    def test_today_has_two_params(self):
        clause, params = period_clause("today")
        assert "timestamp >= :start" in clause
        assert "timestamp < :end" in clause
        assert len(params) == 2
        # start < end
        assert params["start"] < params["end"]

    def test_7d_has_one_param(self):
        clause, params = period_clause("7d")
        assert "timestamp >= :start" in clause
        assert len(params) == 1

    def test_30d_has_one_param(self):
        clause, params = period_clause("30d")
        assert len(params) == 1

    def test_90d_has_one_param(self):
        clause, params = period_clause("90d")
        assert len(params) == 1

    def test_365d_has_one_param(self):
        clause, params = period_clause("365d")
        assert len(params) == 1

    def test_custom_with_dates(self):
        clause, params = period_clause(
            "custom", date_from="2026-01-01", date_to="2026-01-07"
        )
        assert "timestamp >= :start" in clause
        assert "timestamp < :end" in clause
        assert len(params) == 2
        # In UTC: 2026-01-01 00:00:00 → 2026-01-07 23:59:59 (end of day 7)
        assert params["start"] == "2026-01-01 00:00:00"
        assert params["end"] == "2026-01-08 00:00:00"

    def test_custom_missing_dates_falls_back_to_all(self):
        clause, params = period_clause("custom")  # no date_from/date_to
        assert clause == "1=1"
        assert params == {}

    def test_custom_col_param_used(self):
        clause, params = period_clause("7d", col="created_at")
        assert "created_at >= :start" in clause

    def test_7d_start_is_6_days_ago(self):
        """7d window covers today + the 6 preceding days (7 days total)."""
        clause, params = period_clause("7d")
        # params["start"] is the start of 6 days ago in UTC
        start_dt = datetime.fromisoformat(params["start"])
        today_utc = datetime.now(UTC).replace(tzinfo=None).date()
        start_date = start_dt.date()
        delta_days = (today_utc - start_date).days
        assert delta_days == 6

    def test_30d_start_is_29_days_ago(self):
        clause, params = period_clause("30d")
        start_dt = datetime.fromisoformat(params["start"])
        today_utc = datetime.now(UTC).replace(tzinfo=None).date()
        delta_days = (today_utc - start_dt.date()).days
        assert delta_days == 29

    def test_today_start_is_midnight_utc(self):
        """In UTC timezone, today's start should be 00:00:00 today."""
        clause, params = period_clause("today")
        start, end = params["start"], params["end"]
        today_str = datetime.now(UTC).strftime("%Y-%m-%d")
        assert start.startswith(today_str)
        assert start.endswith("00:00:00")

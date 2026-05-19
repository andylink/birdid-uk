"""
Unit tests for dashboard/utils.py.

Patching notes
--------------
`dashboard.utils._local_tz()` reads from `dashboard.config.LOCAL_TZ` on every
call, so patching `dashboard.config.LOCAL_TZ` is enough to control the timezone
without touching config.toml.

`_day_utc_bounds` accepts an explicit `tz` parameter so no patching is needed
for those tests.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

import dashboard.config   # imported so we can patch LOCAL_TZ
from dashboard.utils import (
    _day_utc_bounds,
    period_clause,
    to_utc_iso,
    utc_offset_str,
)

UTC = ZoneInfo("UTC")
KOLKATA = ZoneInfo("Asia/Kolkata")   # fixed +5:30, no DST
LONDON = ZoneInfo("Europe/London")


# ── to_utc_iso ────────────────────────────────────────────────────────────────

class TestToUtcIso:
    def test_none_returns_none(self):
        assert to_utc_iso(None) is None

    def test_empty_string_returns_empty(self):
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
        # T separator present but no timezone marker → add +00:00
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
        """In BST (+01:00), local midnight is 23:00 UTC the previous day."""
        d = date(2026, 6, 21)
        start, end = _day_utc_bounds(d, LONDON)
        assert start == "2026-06-20 23:00:00"
        assert end   == "2026-06-21 23:00:00"

    def test_kolkata_day_shifted_by_5h30(self):
        """In IST (+05:30), local midnight 2026-05-13 = 2026-05-12 18:30 UTC."""
        d = date(2026, 5, 13)
        start, end = _day_utc_bounds(d, KOLKATA)
        assert start == "2026-05-12 18:30:00"
        assert end   == "2026-05-13 18:30:00"

    def test_gmt_winter_london_no_offset(self):
        """In winter, London is GMT (no offset), so bounds match UTC."""
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
        """IST (+5:30) should produce '+5 hours 30 minutes'."""
        monkeypatch.setattr(dashboard.config, "LOCAL_TZ", KOLKATA)
        assert utc_offset_str() == "'+5 hours 30 minutes'"

    def test_bst_is_plus_one_hour(self, monkeypatch):
        """London offset is +0 in winter or +1 in summer; both are valid outcomes."""
        monkeypatch.setattr(dashboard.config, "LOCAL_TZ", LONDON)
        result = utc_offset_str()
        assert result in ("'+0 hours'", "'+1 hours'")

    def test_returns_quoted_string(self, monkeypatch):
        """Return value is single-quoted so it can be used directly in SQLite datetime()."""
        monkeypatch.setattr(dashboard.config, "LOCAL_TZ", UTC)
        result = utc_offset_str()
        assert result.startswith("'") and result.endswith("'")


# ── period_clause ─────────────────────────────────────────────────────────────

class TestPeriodClause:
    """LOCAL_TZ is fixed to UTC so date arithmetic is deterministic."""

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
        # end should be the start of the day after date_to
        assert params["start"] == "2026-01-01 00:00:00"
        assert params["end"] == "2026-01-08 00:00:00"

    def test_custom_missing_dates_falls_back_to_all(self):
        clause, params = period_clause("custom")
        assert clause == "1=1"
        assert params == {}

    def test_custom_col_param_used(self):
        clause, params = period_clause("7d", col="created_at")
        assert "created_at >= :start" in clause

    def test_7d_start_is_6_days_ago(self):
        """'7d' covers today plus the 6 preceding days (7 days total)."""
        clause, params = period_clause("7d")
        start_dt = datetime.fromisoformat(params["start"])
        today_utc = datetime.now(UTC).replace(tzinfo=None).date()
        delta_days = (today_utc - start_dt.date()).days
        assert delta_days == 6

    def test_30d_start_is_29_days_ago(self):
        clause, params = period_clause("30d")
        start_dt = datetime.fromisoformat(params["start"])
        today_utc = datetime.now(UTC).replace(tzinfo=None).date()
        delta_days = (today_utc - start_dt.date()).days
        assert delta_days == 29

    def test_today_start_is_midnight_utc(self):
        """In UTC, today's start should be midnight of the current date."""
        clause, params = period_clause("today")
        start, end = params["start"], params["end"]
        today_str = datetime.now(UTC).strftime("%Y-%m-%d")
        assert start.startswith(today_str)
        assert start.endswith("00:00:00")

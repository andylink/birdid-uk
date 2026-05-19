"""
Sunrise and sunset times for a given local date.

Uses the astral library with the lat/lon from [location] in config.toml.
Returned times are in the configured local timezone so the frontend can
overlay them directly onto the hourly activity heatmap.
"""

from __future__ import annotations

from datetime import date as date_cls

from astral import LocationInfo
from astral.sun import sun as _astral_sun
from fastapi import APIRouter, HTTPException, Query

from dashboard.config import LOCAL_TZ, SUN_LAT, SUN_LON, TIMEZONE

router = APIRouter()

# Built once at startup from config — reused for every request.
_LOCATION = LocationInfo(
    name="Garden",
    region="UK",
    timezone=TIMEZONE,
    latitude=SUN_LAT,
    longitude=SUN_LON,
)


@router.get("/api/v1/sun")
async def get_sun_times(
    date: str = Query(..., description="YYYY-MM-DD local date"),
):
    """Return sunrise and sunset times (HH:MM) in local time for the given date."""
    try:
        d = date_cls.fromisoformat(date)
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid date — expected YYYY-MM-DD",
        )

    try:
        s = _astral_sun(_LOCATION.observer, date=d, tzinfo=LOCAL_TZ)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Sun time calculation failed: {exc}",
        )

    return {
        "sunrise": s["sunrise"].strftime("%H:%M"),
        "sunset":  s["sunset"].strftime("%H:%M"),
    }

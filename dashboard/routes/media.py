"""
Audio and spectrogram serving.

Spectrograms are served from pre-rendered PNGs in the spectrograms directory
where possible.  These are written at detection time by detector.py and persist
after the source audio clip has been deleted by the retention policy.

If no saved PNG exists (e.g. the detector hasn't run since this change was
deployed, or saving failed), the endpoint falls back to rendering on the fly
from the FLAC clip.  If neither is available a 404 is returned.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from dashboard.config import DETECTIONS_DIR, SPECTROGRAMS_DIR
from spectrogram import render_spectrogram

router = APIRouter()

_log = __import__("logging").getLogger(__name__)


def _safe_path(base: Path, filename: str) -> Path:
    """Resolve *filename* relative to *base* and verify it stays within *base*.

    Raises HTTP 400 if the resolved path escapes the base directory, preventing
    path-traversal attacks such as ``../../etc/passwd``.
    """
    resolved = (base / filename).resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise HTTPException(status_code=400, detail="Invalid filename")
    return resolved


@router.get("/audio/{filename}")
async def serve_audio(filename: str):
    """Serve a FLAC clip from the detections directory."""
    path = _safe_path(DETECTIONS_DIR, filename)
    if not path.is_file() or path.suffix.lower() != ".flac":
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(str(path), media_type="audio/flac")


@router.get("/spectrogram/{filename}")
async def serve_spectrogram(filename: str):
    """Return a PNG mel-spectrogram for a detection clip.

    Lookup order:
      1. Pre-saved PNG in the spectrograms directory — always available even
         after the source audio clip has been deleted by retention.
      2. On-the-fly render from the FLAC clip — used as a fallback when no
         saved PNG exists (e.g. detections recorded before this feature).
      3. 404 — neither PNG nor FLAC is available.
    """
    stem     = Path(filename).stem
    png_path = _safe_path(SPECTROGRAMS_DIR, f"{stem}.png")

    # Fast path: return the pre-saved PNG directly from disk.
    if png_path.is_file():
        return FileResponse(str(png_path), media_type="image/png")

    # Fallback: render from the FLAC if it still exists.
    flac_path = _safe_path(DETECTIONS_DIR, filename)
    if not flac_path.is_file():
        raise HTTPException(status_code=404, detail="Spectrogram not available")

    try:
        png = render_spectrogram(str(flac_path))
    except Exception as exc:
        _log.exception("Spectrogram render failed for %s", flac_path)
        raise HTTPException(status_code=500, detail="Spectrogram rendering failed") from exc

    return Response(content=png, media_type="image/png")

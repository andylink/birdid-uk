"""
dashboard/routes/media.py — audio clip serving and spectrogram generation.

Spectrograms are rendered with librosa + matplotlib (slate-900 background)
and cached in an LRU cache (256 entries) keyed on the absolute file path.
"""

from __future__ import annotations

import io
from functools import lru_cache

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response

from dashboard.config import DETECTIONS_DIR

router = APIRouter()


@lru_cache(maxsize=256)
def _render_spectrogram(filepath: str) -> bytes:
    """Render a mel-spectrogram PNG for *filepath* and return raw PNG bytes."""
    import librosa
    import librosa.display
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    y, sr = librosa.load(filepath, sr=None, mono=True)
    S = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=80, fmax=sr // 2)
    S_db = librosa.power_to_db(S, ref=np.max)

    fig, ax = plt.subplots(figsize=(6, 1.2))
    fig.patch.set_facecolor("#0f172a")  # slate-900
    ax.set_facecolor("#0f172a")

    librosa.display.specshow(
        S_db,
        sr=sr,
        ax=ax,
        cmap="viridis",
        x_axis=None,
        y_axis=None,
    )
    ax.set_axis_off()
    plt.tight_layout(pad=0)

    buf = io.BytesIO()
    plt.savefig(
        buf, format="png", dpi=100, bbox_inches="tight", pad_inches=0,
        facecolor="#0f172a",
    )
    plt.close(fig)
    buf.seek(0)
    return buf.read()


@router.get("/audio/{filename}")
async def serve_audio(filename: str):
    """Serve a raw WAV clip from the detections directory."""
    path = DETECTIONS_DIR / filename
    if not path.is_file() or path.suffix.lower() != ".wav":
        raise HTTPException(status_code=404, detail="Audio file not found")
    return FileResponse(str(path), media_type="audio/wav")


@router.get("/spectrogram/{filename}")
async def serve_spectrogram(filename: str):
    """Return a PNG mel-spectrogram for a WAV clip (LRU-cached)."""
    path = DETECTIONS_DIR / filename
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")
    try:
        png = _render_spectrogram(str(path))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Spectrogram error: {exc}") from exc
    return Response(content=png, media_type="image/png")

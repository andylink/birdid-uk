"""
spectrogram.py — mel-spectrogram rendering and on-disk persistence.

Spectrograms are rendered as PNG images using librosa and matplotlib with a
dark background that matches the dashboard theme.

save_spectrogram() is called at detection time so a PNG is persisted alongside
(but separately from) the FLAC clip.  This means spectrograms remain available
in the dashboard even after the source audio clip has been removed by the
retention policy.

PNG filename convention:
    <clip_stem>.png  →  e.g. 20260519_143000_European_Robin.png

render_spectrogram() is also used directly by the dashboard's media route for
the on-the-fly fallback path (e.g. during initial population or if saving fails).
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)


@lru_cache(maxsize=256)
def render_spectrogram(filepath: str) -> bytes:
    """Render a mel-spectrogram for the given audio file and return PNG bytes.

    Imports are deferred so librosa/matplotlib are not loaded unless a
    spectrogram is actually needed.  Results are LRU-cached (up to 256 entries)
    so repeated requests for the same file are free after the first render.
    """
    import librosa
    import librosa.display
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    y, sr = librosa.load(filepath, sr=None, mono=True)
    S     = librosa.feature.melspectrogram(y=y, sr=sr, n_mels=80, fmax=sr // 2)
    S_db  = librosa.power_to_db(S, ref=np.max)

    fig, ax = plt.subplots(figsize=(6, 1.2))
    fig.patch.set_facecolor("#0f172a")  # slate-900, matches dashboard theme
    ax.set_facecolor("#0f172a")

    librosa.display.specshow(S_db, sr=sr, ax=ax, cmap="viridis",
                             x_axis=None, y_axis=None)
    ax.set_axis_off()
    plt.tight_layout(pad=0)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=100, bbox_inches="tight",
                pad_inches=0, facecolor="#0f172a")
    plt.close(fig)
    buf.seek(0)
    return buf.read()


def save_spectrogram(clip_path: Path, spectrograms_dir: Path) -> Path | None:
    """Render the spectrogram for *clip_path* and write it to *spectrograms_dir*.

    The output filename is the clip stem with a .png extension, e.g.::

        20260519_143000_European_Robin.flac  →  20260519_143000_European_Robin.png

    Returns the saved :class:`~pathlib.Path` on success, or ``None`` if the
    render or write fails (error is logged but never re-raised so a rendering
    failure never prevents the detection from being saved).
    """
    try:
        spectrograms_dir.mkdir(parents=True, exist_ok=True)
        png_path  = spectrograms_dir / (clip_path.stem + ".png")
        png_bytes = render_spectrogram(str(clip_path))
        png_path.write_bytes(png_bytes)
        logger.debug("Saved spectrogram %s", png_path.name)
        return png_path
    except Exception:
        logger.exception("Failed to save spectrogram for %s", clip_path.name)
        return None

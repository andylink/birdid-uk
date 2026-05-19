"""
Audio I/O helpers used by the detector and inference pipeline.

Covers: writing WAV/FLAC files, sanitising filenames, saving detection clips,
and optionally filtering audio before inference.
"""

from __future__ import annotations

import re
import wave
from datetime import datetime
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.signal import butter, sosfilt

from config import cfg


# ── Low-level helpers ─────────────────────────────────────────────────────────

def save_wav(audio: np.ndarray, path: Path) -> None:
    """Write a mono int16 array to a WAV file.

    WAV is used for BirdNET inference temp files. Persistent detection clips
    use FLAC (see save_flac).
    """
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(cfg.audio.sample_rate)
        wf.writeframes(audio.astype(np.int16).tobytes())


def save_flac(audio: np.ndarray, path: Path) -> None:
    """Write a mono int16 array to a FLAC file."""
    sf.write(str(path), audio.astype(np.int16), cfg.audio.sample_rate, subtype="PCM_16")


def safe_name(s: str) -> str:
    """Replace characters that are unsafe in filenames with underscores."""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", s)


# ── High-pass filter ──────────────────────────────────────────────────────────

def apply_highpass(
    audio: np.ndarray,
    sample_rate: int,
    cutoff_hz: float,
    order: int,
) -> np.ndarray:
    """Apply a Butterworth high-pass filter and return a new int16 array.

    The input array is not modified. SOS (second-order sections) form is used
    for numerical stability, which matters most at higher filter orders.
    """
    sos      = butter(order, cutoff_hz, btype="highpass", fs=sample_rate, output="sos")
    filtered = sosfilt(sos, audio.astype(np.float32))
    return np.clip(filtered, -32768, 32767).astype(np.int16)


# ── Clip saving ───────────────────────────────────────────────────────────────

def save_clip(
    audio:       np.ndarray,
    ts:          datetime,
    species:     str,
    source_name: str | None = None,
) -> Path:
    """Save a detection clip as a normalised FLAC file.

    The audio is normalised to the full int16 range so clips are audible
    regardless of microphone gain. The original array passed to inference is
    not affected.

    Args:
        audio:       1-D int16 PCM array to save.
        ts:          Detection timestamp, used in the filename.
        species:     Species common name, used in the filename.
        source_name: Optional microphone label inserted into the filename so
                     clips from different sources can be told apart, e.g.
                     ``20260518_143000_garden_north_European_Robin.flac``.
                     Omit for the legacy format:
                     ``20260518_143000_European_Robin.flac``.

    Returns the path of the saved file.
    """
    cfg.paths.detections_dir.mkdir(parents=True, exist_ok=True)
    if source_name:
        filename = (
            f"{ts.strftime('%Y%m%d_%H%M%S')}"
            f"_{safe_name(source_name)}"
            f"_{safe_name(species)}.flac"
        )
    else:
        filename = f"{ts.strftime('%Y%m%d_%H%M%S')}_{safe_name(species)}.flac"
    path = cfg.paths.detections_dir / filename

    peak = int(np.abs(audio).max())
    if peak > 0:
        scale      = 32767.0 / peak
        normalised = np.clip(
            audio.astype(np.float32) * scale, -32768, 32767
        ).astype(np.int16)
    else:
        normalised = audio

    save_flac(normalised, path)
    return path

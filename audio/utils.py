"""
audio/utils.py — audio I/O and clip utilities.

Handles:
  - Writing PCM audio arrays to WAV files (inference temp files)
  - Writing PCM audio arrays to FLAC files (persistent detection clips)
  - Sanitising strings for use in filenames
  - Saving normalised detection clips
  - Applying a high-pass filter before inference (optional)
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
    """Write a mono int16 PCM array to *path* as a WAV file.

    Used exclusively for BirdNET inference temp files, which require WAV.
    Persistent detection clips are saved as FLAC via save_flac().
    """
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(cfg.audio.sample_rate)
        wf.writeframes(audio.astype(np.int16).tobytes())


def save_flac(audio: np.ndarray, path: Path) -> None:
    """Write a mono int16 PCM array to *path* as a FLAC file."""
    sf.write(str(path), audio.astype(np.int16), cfg.audio.sample_rate, subtype="PCM_16")


def safe_name(s: str) -> str:
    """Strip characters that are unsafe in filenames."""
    return re.sub(r"[^A-Za-z0-9_\-]", "_", s)


# ── High-pass filter ──────────────────────────────────────────────────────────

def apply_highpass(
    audio: np.ndarray,
    sample_rate: int,
    cutoff_hz: float,
    order: int,
) -> np.ndarray:
    """
    Apply a Butterworth high-pass filter to *audio* and return a new int16
    array.  The input array is never modified.

    Uses second-order sections (SOS) for numerical stability, which matters
    especially at higher filter orders.
    """
    sos      = butter(order, cutoff_hz, btype="highpass", fs=sample_rate, output="sos")
    filtered = sosfilt(sos, audio.astype(np.float32))
    return np.clip(filtered, -32768, 32767).astype(np.int16)


# ── Clip saving ───────────────────────────────────────────────────────────────

def save_clip(audio: np.ndarray, ts: datetime, species: str) -> Path:
    """
    Save a normalised FLAC clip to the detections directory.

    The audio is normalised to the full int16 range so clips are audible
    regardless of the microphone gain.  The raw audio passed to inference
    is never modified.

    Returns the path of the saved file.
    """
    cfg.paths.detections_dir.mkdir(parents=True, exist_ok=True)
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

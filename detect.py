"""
Entry point for running the bird classifier directly (python detect.py).

All the real logic lives in the supporting modules:
  config.py    — configuration loaded from config.toml
  audio.py     — WAV I/O and clip saving
  inference.py — BirdNET analysis and label-map loading
  database.py  — SQLite persistence
  detector.py  — recording thread, classify loop, and main()
"""

from detector import main

if __name__ == "__main__":
    main()

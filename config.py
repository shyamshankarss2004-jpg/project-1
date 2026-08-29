"""
config.py
---------
Centralised application constants for the Virtual Personal Trainer.
Import from this module instead of hard-coding values elsewhere.
"""

# ── Application Window ─────────────────────────────────────────────────────────
APP_TITLE = "Virtual Personal Trainer"
MIN_WINDOW_WIDTH = 1200
MIN_WINDOW_HEIGHT = 800

# ── Database ───────────────────────────────────────────────────────────────────
DB_RELATIVE_PATH = "data/database.db"

# ── User Settings Defaults ─────────────────────────────────────────────────────
DEFAULT_SETTINGS = {
    "mode": "auto",       # "auto" | "manual"
    "prepare": 5,         # Preparation countdown (seconds)
    "rep": 2,             # Seconds per automatic repetition
    "volume": 50,         # Audio volume (0–100)
    "camera": "",         # Camera device name (empty = first available)
}

# ── Validation ─────────────────────────────────────────────────────────────────
MAX_USERNAME_LENGTH = 15
PIN_DIGIT_COUNT = 4

# ── Training ───────────────────────────────────────────────────────────────────
CAMERA_TIMER_INTERVAL_MS = 30    # Camera frame refresh rate
GIF_TIMER_INTERVAL_MS = 10       # GIF animation refresh rate
MAX_REP_SOUND_COUNT = 20         # Highest rep sound available

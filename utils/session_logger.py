"""
utils/session_logger.py
------------------------
Saves completed workout sessions to a local JSON file.

Log location: workout_logs/session_data.json (relative to project root).
Each session is appended as one entry in a JSON array so the full history
is preserved across runs.

Usage:
    from utils.session_logger import SessionLogger
    logger = SessionLogger()
    logger.log_session("Squats", reps=20, start_time=t0, end_time=t1)
"""

import json
import os
import time
from datetime import datetime

from utils.logger import get_logger

_log = get_logger(__name__)

_LOG_DIR  = "workout_logs"
_LOG_FILE = os.path.join(_LOG_DIR, "session_data.json")


class SessionLogger:
    """Appends workout session records to a local JSON log file."""

    def __init__(self, log_dir: str = _LOG_DIR):
        self.log_file = os.path.join(log_dir, "session_data.json")
        try:
            os.makedirs(log_dir, exist_ok=True)
        except OSError as e:
            _log.error("Could not create log directory '%s': %s", log_dir, e)

    # ── Public API ─────────────────────────────────────────────────────────────

    def log_session(self, exercise: str, reps: int,
                    start_time: float, end_time: float) -> dict:
        """
        Build a session record and append it to the JSON log.

        Args:
            exercise:   Name of the exercise performed.
            reps:       Total repetitions completed.
            start_time: Session start (Unix timestamp from time.time()).
            end_time:   Session end  (Unix timestamp from time.time()).

        Returns:
            The session record dict that was written.
        """
        elapsed = max(0, int(end_time - start_time))
        mins, secs = divmod(elapsed, 60)
        record = {
            "exercise": exercise,
            "reps": reps,
            "duration": f"{mins} min {secs:02d} sec",
            "date": datetime.now().strftime("%Y-%m-%d"),
            "time": datetime.now().strftime("%H:%M:%S"),
        }
        self._append(record)
        _log.info("Session saved: %s reps=%d duration=%s", exercise, reps, record["duration"])
        return record

    # ── Private ────────────────────────────────────────────────────────────────

    def _append(self, record: dict) -> None:
        """Read existing records, append the new one, and write back."""
        records: list = []
        if os.path.exists(self.log_file):
            try:
                with open(self.log_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    records = data if isinstance(data, list) else [data]
            except (json.JSONDecodeError, OSError) as e:
                _log.warning("Could not read existing log: %s. Starting fresh.", e)

        records.append(record)
        try:
            with open(self.log_file, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2, ensure_ascii=False)
        except OSError as e:
            _log.error("Could not write session log: %s", e)

    def get_all_sessions(self) -> list:
        """
        Return all saved session records.

        Returns:
            A list of session record dicts, or an empty list on error.
        """
        if not os.path.exists(self.log_file):
            return []
        try:
            with open(self.log_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, list) else [data]
        except (json.JSONDecodeError, OSError) as e:
            _log.error("Could not read session log: %s", e)
            return []

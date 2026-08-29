"""
utils/logger.py
---------------
Provides a single, pre-configured logger for the entire application.

Usage:
    from utils.logger import get_logger
    logger = get_logger(__name__)
    logger.info("Application started.")
    logger.warning("Setting not found, using default.")
    logger.error("Database error: %s", exc)
"""

import logging
import sys


def get_logger(name: str) -> logging.Logger:
    """
    Return a named logger with a consistent format.

    All loggers share the same root handler so output is unified.
    Only the first call configures the root handler; subsequent calls
    simply return a child logger.

    Args:
        name: Typically __name__ of the calling module.

    Returns:
        A configured logging.Logger instance.
    """
    logger = logging.getLogger(name)

    # Avoid adding multiple handlers if the function is called repeatedly
    if not logging.root.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(logging.DEBUG)
        formatter = logging.Formatter(
            fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        logging.root.addHandler(handler)
        logging.root.setLevel(logging.DEBUG)

    return logger

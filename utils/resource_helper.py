"""
utils/resource_helper.py
-------------------------
Provides a portable file-path resolver that works both when the application
is run directly as a Python script and when it is packaged into a standalone
executable with PyInstaller.
"""

import os
import sys


def resource_path(relative_path: str) -> str:
    """
    Resolve a resource path that works in both development and packaged modes.

    When PyInstaller bundles the application into a single executable, it
    extracts files to a temporary directory stored in ``sys._MEIPASS``.
    This helper abstracts that detail so the rest of the codebase can always
    use simple relative paths.

    Args:
        relative_path: A path relative to the project root (e.g. "ui/login.ui").

    Returns:
        An absolute path to the requested resource.
    """
    if hasattr(sys, "_MEIPASS"):
        # Running as a PyInstaller-packaged executable
        base_path = sys._MEIPASS
    else:
        # Running as a normal Python script
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

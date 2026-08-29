"""
main.py
-------
Application entry point for the Virtual Personal Trainer.

Creates the top-level QApplication, instantiates the main controller
window that manages the login / account-creation / main-app stack,
and starts the Qt event loop.
"""

import sys

from PyQt5.QtWidgets import QApplication, QMainWindow, QStackedWidget

from config import APP_TITLE, MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT
from utils.logger import get_logger
from windows.login_window import LoginWindow
from windows.new_account_window import NewAccountWindow
from windows.main_window import MainWindow

logger = get_logger(__name__)


class MainApp(QMainWindow):
    """
    Root controller that owns the QStackedWidget used for screen navigation.

    Screens (Login, NewAccount, Main) are pushed onto / popped off the stack
    as the user moves through the application.
    """

    def __init__(self):
        super().__init__()
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)
        self._init_window()
        self.show_login_window()

    # ── Window Setup ───────────────────────────────────────────────────────────

    def _init_window(self):
        """Configure the main window title and minimum size."""
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(MIN_WINDOW_WIDTH, MIN_WINDOW_HEIGHT)

    # ── Screen Navigation ──────────────────────────────────────────────────────

    def show_login_window(self):
        """Push the login screen onto the stack and make it current."""
        self.login_window = LoginWindow(self)
        self.stack.addWidget(self.login_window)
        self.stack.setCurrentWidget(self.login_window)
        logger.info("Showing login screen.")

    def show_new_account_window(self):
        """Push the account-creation screen onto the stack and make it current."""
        self.new_account_window = NewAccountWindow(self)
        self.stack.addWidget(self.new_account_window)
        self.stack.setCurrentWidget(self.new_account_window)
        logger.info("Showing new account screen.")

    def show_main_window(self, username: str):
        """
        Push the main application window onto the stack.

        Args:
            username: The authenticated user's username.
        """
        self.main_window = MainWindow(self, username)
        self.stack.addWidget(self.main_window)
        self.stack.setCurrentWidget(self.main_window)
        logger.info("User '%s' logged in. Showing main window.", username)

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        """Stop any active training session before the window closes."""
        current_widget = self.stack.currentWidget()
        if isinstance(current_widget, MainWindow):
            current_page = current_widget.stacked_main_window.currentWidget()
            if hasattr(current_page, "stop_training_if_any"):
                current_page.stop_training_if_any()
        event.accept()


def main():
    """Initialise the Qt application and start the event loop."""
    app = QApplication(sys.argv)
    window = MainApp()
    window.show()
    logger.info("Virtual Personal Trainer started.")
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()

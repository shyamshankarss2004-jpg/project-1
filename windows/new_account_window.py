"""
windows/new_account_window.py
------------------------------
Account-creation screen: lets a new user choose a username and set
their 4-digit PIN.
"""

from PyQt5.QtWidgets import QMainWindow, QMessageBox
from PyQt5.uic import loadUi
from PyQt5.QtGui import QIntValidator

from data.database_manager import create_user, check_if_user_exist
from utils.resource_helper import resource_path
from utils.validators import (
    is_pin_complete,
    get_pin_string,
    handle_pin_focus,
    is_valid_username,
)


class NewAccountWindow(QMainWindow):
    """Screen for registering a new user account with a username and PIN."""

    def __init__(self, main_window):
        super().__init__()
        loadUi(resource_path("ui/login_new.ui"), self)

        self.main_window = main_window
        self._pin_fields = [self.pin_edit_1, self.pin_edit_2, self.pin_edit_3, self.pin_edit_4]

        self._setup_fields()
        self._connect_signals()

    # ── Initialisation ─────────────────────────────────────────────────────────

    def _setup_fields(self):
        """Configure the username field and PIN digit validators."""
        from config import MAX_USERNAME_LENGTH
        self.userEdit.setMaxLength(MAX_USERNAME_LENGTH)

        validator = QIntValidator(0, 9, self)
        for field in self._pin_fields:
            field.setValidator(validator)

    def _connect_signals(self):
        """Wire up buttons and PIN field auto-advance signals."""
        fields = self._pin_fields
        fields[0].textChanged.connect(lambda: handle_pin_focus(fields[0], None, fields[1]))
        fields[1].textChanged.connect(lambda: handle_pin_focus(fields[1], fields[0], fields[2]))
        fields[2].textChanged.connect(lambda: handle_pin_focus(fields[2], fields[1], fields[3]))
        fields[3].textChanged.connect(lambda: handle_pin_focus(fields[3], fields[2], None))

        self.goBackButton.clicked.connect(self.main_window.show_login_window)
        self.newUserButton.clicked.connect(self._add_new_user)

    # ── Account Creation ───────────────────────────────────────────────────────

    def _clear_fields(self):
        """Reset all input fields to empty."""
        self.userEdit.clear()
        for field in self._pin_fields:
            field.clear()

    def _add_new_user(self):
        """Validate all inputs and create the new account if the data is valid."""
        username = self.userEdit.text().strip()

        # Username validation
        valid, error_msg = is_valid_username(username)
        if not valid:
            QMessageBox.warning(self, "Error", error_msg)
            return

        if check_if_user_exist(username):
            QMessageBox.warning(self, "Error", "A user with this name already exists.")
            return

        # PIN validation
        if not is_pin_complete(self._pin_fields):
            QMessageBox.warning(self, "Error", "Please enter a complete 4-digit PIN!")
            return

        pin = get_pin_string(self._pin_fields)

        # Create the account
        if create_user(username, pin):
            QMessageBox.information(self, "Success", "Account created successfully!")
            self.main_window.login_window.reload_users()
            self.main_window.show_login_window()
        else:
            QMessageBox.warning(self, "Error", "Failed to create account. Please try again.")

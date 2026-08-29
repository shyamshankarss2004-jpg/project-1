"""
windows/login_window.py
-----------------------
Login screen: user selects their account from a drop-down and enters
their 4-digit PIN to authenticate.
"""

from PyQt5.QtWidgets import QMainWindow, QMessageBox
from PyQt5.QtGui import QIntValidator
from PyQt5.uic import loadUi

from data.database_manager import authenticate_user, get_all_users
from utils.resource_helper import resource_path
from utils.validators import is_pin_complete, get_pin_string, handle_pin_focus


class LoginWindow(QMainWindow):
    """Login screen that authenticates users via username + 4-digit PIN."""

    def __init__(self, main_window):
        super().__init__()
        loadUi(resource_path("ui/login.ui"), self)

        self.main_window = main_window
        self._pin_fields = [self.pin_edit_1, self.pin_edit_2, self.pin_edit_3, self.pin_edit_4]

        self._setup_pin_fields()
        self._connect_signals()
        self.reload_users()

    # ── Initialisation ─────────────────────────────────────────────────────────

    def _setup_pin_fields(self):
        """Restrict each PIN field to a single digit (0–9)."""
        validator = QIntValidator(0, 9, self)
        for field in self._pin_fields:
            field.setValidator(validator)

    def _connect_signals(self):
        """Wire up button clicks and PIN field auto-advance signals."""
        fields = self._pin_fields
        fields[0].textChanged.connect(lambda: handle_pin_focus(fields[0], None, fields[1]))
        fields[1].textChanged.connect(lambda: handle_pin_focus(fields[1], fields[0], fields[2]))
        fields[2].textChanged.connect(lambda: handle_pin_focus(fields[2], fields[1], fields[3]))
        fields[3].textChanged.connect(lambda: handle_pin_focus(fields[3], fields[2], None))

        self.newAccount.clicked.connect(self.main_window.show_new_account_window)
        self.loginButton.clicked.connect(self._login)

    # ── User Management ────────────────────────────────────────────────────────

    def reload_users(self):
        """
        Populate the username drop-down from the database.

        If no users exist the PIN fields and login button are hidden to
        guide the user towards creating an account first.
        """
        self.userBox.clear()
        users = get_all_users()
        if users:
            for user in users:
                self.userBox.addItem(user)
        else:
            self.loginButton.hide()
            self.label_3.hide()
            for field in self._pin_fields:
                field.hide()
            self.userBox.addItem("No users available")
            self.userBox.setEnabled(False)

    def clear_fields(self):
        """Clear all PIN digit fields."""
        for field in self._pin_fields:
            field.clear()

    # ── Authentication ─────────────────────────────────────────────────────────

    def _login(self):
        """Validate input and attempt to authenticate the selected user."""
        username = self.userBox.currentText()
        if not username:
            QMessageBox.warning(self, "Error", "Please create a user first!")
            return

        if not is_pin_complete(self._pin_fields):
            QMessageBox.warning(self, "Error", "Please enter a valid 4-digit PIN!")
            return

        pin = get_pin_string(self._pin_fields)

        if authenticate_user(username, pin):
            QMessageBox.information(self, "Success", "Login successful!")
            self.main_window.show_main_window(username)
        else:
            QMessageBox.warning(self, "Error", "Incorrect PIN. Please try again.")
            self.clear_fields()

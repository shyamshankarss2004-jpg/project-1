"""
windows/main_pages/settings_page.py
-------------------------------------
Settings page: lets the user configure training mode, timing, volume,
camera device, and account details (username change / deletion).
"""

from PyQt5.QtWidgets import QWidget, QMessageBox
from PyQt5.uic import loadUi
from PyQt5.QtMultimedia import QCameraInfo

from data.database_manager import set_setting, get_setting, check_if_user_exist, update_username, delete_user_account
from utils.resource_helper import resource_path
from utils.logger import get_logger

logger = get_logger(__name__)


class SettingsPage(QWidget):
    """
    User settings page.

    Reads current settings from the database on load and writes any
    changes back immediately when controls are interacted with.
    """

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        loadUi(resource_path("ui/pages/settings_page.ui"), self)

        self.main_window = main_window
        self.user = self.main_window.current_userid

        self._load_settings()
        self._connect_signals()

        saved_camera = get_setting(self.user, "camera")
        self._init_video_devices(saved_camera)

    # ── Initialisation ─────────────────────────────────────────────────────────

    def _get_setting_int(self, key: str, default: int) -> int:
        """
        Read an integer setting, falling back to *default* if absent.

        Args:
            key: Settings column name.
            default: Value to use when the setting is not found.

        Returns:
            The setting value as an integer.
        """
        value = get_setting(self.user, key)
        return int(value) if value is not None else default

    def _load_settings(self):
        """Populate all controls with the values stored in the database."""
        self.new_user_line.setMaxLength(15)

        # --- Training mode ---
        mode = get_setting(self.user, "mode") or "auto"
        if mode == "manual":
            self.radioButton_manual.setChecked(True)
            self.spinBox_rep.setEnabled(False)
            self.label_rep.setStyleSheet("QLabel { color : grey; }")
        else:
            self.radioButton_auto.setChecked(True)
            self.spinBox_rep.setEnabled(True)
            self.label_rep.setStyleSheet("QLabel {}")

        # --- Numeric settings ---
        self.spinBox_prepare.setValue(self._get_setting_int("prepare", 5))
        self.spinBox_rep.setValue(self._get_setting_int("rep", 3))

        volume = self._get_setting_int("volume", 50)
        self.volume_slider.setValue(volume)
        self.volume_label.setText(f"{volume}%")

    def _init_video_devices(self, saved_camera: str = None):
        """
        Populate the camera combo box with all available video devices.

        If the previously saved camera is still available it is pre-selected.
        Otherwise the first available camera is selected and saved.

        Args:
            saved_camera: Device name from the database (may be empty or None).
        """
        available_cameras = QCameraInfo.availableCameras()
        self.video_device_combo.clear()

        if not available_cameras:
            self.video_device_combo.addItem("No cameras available", "")
            self.video_device_combo.setEnabled(False)
            QMessageBox.warning(self, "Warning", "No video devices found.")
            return

        for camera in available_cameras:
            self.video_device_combo.addItem(camera.description(), camera.deviceName())

        if saved_camera:
            index = self.video_device_combo.findData(saved_camera)
            if index != -1:
                self.video_device_combo.setCurrentIndex(index)
                return

        # First available camera becomes the default
        first_device = available_cameras[0].deviceName()
        self.video_device_combo.setCurrentIndex(0)
        set_setting(self.user, "camera", first_device)

    def _connect_signals(self):
        """Wire up all settings controls to their save handlers."""
        self.radioButton_manual.toggled.connect(self._update_mode)
        self.radioButton_auto.toggled.connect(self._update_mode)
        self.spinBox_prepare.valueChanged.connect(
            lambda v: set_setting(self.user, "prepare", str(v))
        )
        self.spinBox_rep.valueChanged.connect(
            lambda v: set_setting(self.user, "rep", str(v))
        )
        self.volume_slider.valueChanged.connect(self._update_volume)
        self.new_user_button.clicked.connect(self._change_username)
        self.video_device_combo.currentIndexChanged.connect(self._update_video_device)
        self.delete_button.clicked.connect(self._delete_account)

    # ── Settings Handlers ──────────────────────────────────────────────────────

    def _update_mode(self):
        """Persist the selected training mode and update the UI accordingly."""
        if self.radioButton_manual.isChecked():
            set_setting(self.user, "mode", "manual")
            self.spinBox_rep.setEnabled(False)
            self.label_rep.setStyleSheet("QLabel { color : grey; }")
        else:
            set_setting(self.user, "mode", "auto")
            self.spinBox_rep.setEnabled(True)
            self.label_rep.setStyleSheet("QLabel {}")

    def _update_volume(self, value: int):
        """
        Persist the audio volume setting and update the label.

        Args:
            value: New volume level (0–100).
        """
        set_setting(self.user, "volume", str(value))
        self.volume_label.setText(f"{value}%")

    def _update_video_device(self):
        """Persist the currently selected camera device name."""
        device_name = self.video_device_combo.currentData()
        set_setting(self.user, "camera", device_name)

    # ── Account Management ─────────────────────────────────────────────────────

    def _change_username(self):
        """Validate and apply a username change."""
        new_username = self.new_user_line.text().strip()

        if not new_username:
            QMessageBox.warning(self, "Error", "Username cannot be empty.")
            return
        if check_if_user_exist(new_username):
            QMessageBox.warning(self, "Error", f"The username '{new_username}' is already taken.")
            return

        if update_username(self.user, new_username):
            QMessageBox.information(self, "Success", f"Username changed to '{new_username}'.")
            self.main_window.current_username = new_username
            self.main_window.hello_label.setText(new_username)
            logger.info("Username updated to '%s' for user id=%s.", new_username, self.user)
        else:
            QMessageBox.critical(self, "Error", "An error occurred while changing the username.")

    def _delete_account(self):
        """Prompt for confirmation then permanently delete the user account."""
        reply = QMessageBox.question(
            self,
            "Confirm Deletion",
            "Are you sure you want to delete your account? This action is irreversible.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            if delete_user_account(self.user):
                QMessageBox.information(self, "Success", "Your account has been deleted.")
                logger.info("User account id=%s deleted.", self.user)
                self.main_window.go_to_login_page()
            else:
                QMessageBox.critical(self, "Error", "An error occurred while deleting the account.")
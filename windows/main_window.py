"""
windows/main_window.py
-----------------------
The authenticated user's main application shell.

Owns the per-page stacked widget and handles navigation between the
Home, Workouts, Exercises, History, Settings, and Demo Mode pages.
"""

from PyQt5.QtWidgets import QMainWindow, QPushButton
from PyQt5.QtGui import QFont
from PyQt5.uic import loadUi

from data.database_manager import get_user_id, get_setting, set_setting

# Qt resource file – registers icons for the sidebar buttons
import ui.images.resources_rc  # noqa: F401

from windows.main_pages.exercises_page import ExercisesPage
from windows.main_pages.workout_page import WorkoutsPage
from windows.main_pages.home_page import HomePage
from windows.main_pages.settings_page import SettingsPage
from windows.main_pages.history_page import HistoryPage
from windows.main_pages.demo_mode_page import DemoModePage

from utils.resource_helper import resource_path
from utils.logger import get_logger

logger = get_logger(__name__)


class MainWindow(QMainWindow):
    """
    Primary application window displayed after a successful login.

    Contains a collapsible sidebar (icon-only and full-width variants)
    and a QStackedWidget that displays the currently active page.
    """

    def __init__(self, main_window, username_in: str):
        super().__init__()
        loadUi(resource_path("ui/main_window.ui"), self)

        self.main_window = main_window
        self.icon_only_widget.setHidden(True)
        self.home_button_2.setChecked(True)

        self._set_current_username(username_in)
        self._connect_signals()
        self._inject_demo_button()
        self.switch_to_home_page()

    # ── Initialisation ─────────────────────────────────────────────────────────

    def _set_current_username(self, username: str):
        """
        Cache the logged-in username and resolve the corresponding user id.

        Args:
            username: The authenticated account username.
        """
        self.current_username = username
        self.current_userid = get_user_id(username)
        self.hello_label.setText(username)

    def _connect_signals(self):
        """Wire up all sidebar button signals to page-switching slots."""
        self.exit_button_1.clicked.connect(self.go_to_login_page)
        self.exit_button_2.clicked.connect(self.go_to_login_page)

        self.home_button_1.clicked.connect(self.switch_to_home_page)
        self.home_button_2.clicked.connect(self.switch_to_home_page)

        self.workout_button_1.clicked.connect(self.switch_to_workout_page)
        self.workout_button_2.clicked.connect(self.switch_to_workout_page)

        self.history_button_1.clicked.connect(self.switch_to_history_page)
        self.history_button_2.clicked.connect(self.switch_to_history_page)

        self.exercises_button_1.clicked.connect(self.switch_to_exercises_page)
        self.exercises_button_2.clicked.connect(self.switch_to_exercises_page)

        self.settings_button_1.clicked.connect(self.switch_to_settings_page)
        self.settings_button_2.clicked.connect(self.switch_to_settings_page)

    def _inject_demo_button(self):
        """
        Programmatically add a 'Demo Mode' button to both sidebars.

        The .ui file only has Home / History / Exercises / Workouts / Settings.
        We insert a Demo Mode button before the spacer in each sidebar's
        VBoxLayout so it appears without modifying the .ui file.
        """
        _DEMO_STYLE = """
            QPushButton {
                color: white;
                text-align: left;
                height: 50px;
                padding-left: 12px;
                border: none;
                border-top-left-radius: 10px;
                border-bottom-left-radius: 10px;
                font: 12pt 'Segoe UI Symbol';
                background-color: transparent;
            }
            QPushButton:checked  { background-color: rgb(160,160,160); }
            QPushButton:hover:!checked { background-color: rgba(160,160,160,80); }
        """
        _DEMO_STYLE_ICON = """
            QPushButton {
                color: white;
                height: 50px;
                border: none;
                border-radius: 10px;
                background-color: transparent;
                font: 14pt 'Segoe UI Symbol';
            }
            QPushButton:checked  { background-color: rgb(160,160,160); }
            QPushButton:hover:!checked { background-color: rgba(160,160,160,80); }
        """

        # ── Full sidebar (icon + name) ──────────────────────────────────────────
        self._demo_btn_full = QPushButton(" 🎬 Demo Mode")
        self._demo_btn_full.setCheckable(True)
        self._demo_btn_full.setAutoExclusive(True)
        self._demo_btn_full.setStyleSheet(_DEMO_STYLE)
        self._demo_btn_full.setFont(QFont("Segoe UI Symbol", 11))
        self._demo_btn_full.clicked.connect(self.switch_to_demo_mode_page)

        # Insert before the spacer (second-to-last item) in verticalLayout_2
        layout_full = self.icon_name_widget.layout().itemAt(2).layout()   # verticalLayout_2
        layout_full.insertWidget(layout_full.count() - 1, self._demo_btn_full)

        # ── Icon-only sidebar ──────────────────────────────────────────────────
        self._demo_btn_icon = QPushButton("🎬")
        self._demo_btn_icon.setCheckable(True)
        self._demo_btn_icon.setAutoExclusive(True)
        self._demo_btn_icon.setStyleSheet(_DEMO_STYLE_ICON)
        self._demo_btn_icon.setFont(QFont("Segoe UI Symbol", 14))
        self._demo_btn_icon.clicked.connect(self.switch_to_demo_mode_page)
        self._demo_btn_icon.toggled.connect(self._demo_btn_full.setChecked)
        self._demo_btn_full.toggled.connect(self._demo_btn_icon.setChecked)

        layout_icon = self.icon_only_widget.layout().itemAt(2).layout()   # verticalLayout_3
        layout_icon.insertWidget(layout_icon.count() - 1, self._demo_btn_icon)

    # ── Session Controls ───────────────────────────────────────────────────────

    def go_to_login_page(self):
        """Log out the current user and return to the login screen."""
        self.switch_to_home_page()
        self.home_button_2.setChecked(True)
        self.current_username = None
        self.current_userid = None
        logger.info("User logged out.")
        self.main_window.show_login_window()

    # ── Training Guard ─────────────────────────────────────────────────────────

    def _stop_training_if_active(self):
        """
        Safely stop any in-progress training/demo session before switching pages.

        Checks both HomePage (live camera) and DemoModePage (video upload).
        """
        current_widget = self.stacked_main_window.currentWidget()
        if isinstance(current_widget, (HomePage, DemoModePage)):
            current_widget.stop_training_if_any()

    # ── Page Navigation ────────────────────────────────────────────────────────

    def switch_to_home_page(self):
        """Navigate to the Home page."""
        self._stop_training_if_active()
        self.home_page = HomePage(main_window=self)
        self.stacked_main_window.addWidget(self.home_page)
        self.stacked_main_window.setCurrentWidget(self.home_page)

    def switch_to_workout_page(self):
        """Navigate to the Workouts page."""
        self._stop_training_if_active()
        self.workouts_page = WorkoutsPage(main_window=self)
        self.stacked_main_window.addWidget(self.workouts_page)
        self.stacked_main_window.setCurrentWidget(self.workouts_page)

    def switch_to_history_page(self):
        """Navigate to the History page."""
        self._stop_training_if_active()
        self.history_page = HistoryPage(main_window=self)
        self.stacked_main_window.addWidget(self.history_page)
        self.stacked_main_window.setCurrentWidget(self.history_page)

    def switch_to_exercises_page(self):
        """Navigate to the Exercises page."""
        self._stop_training_if_active()
        self.exercises_page = ExercisesPage(main_window=self)
        self.stacked_main_window.addWidget(self.exercises_page)
        self.stacked_main_window.setCurrentWidget(self.exercises_page)

    def switch_to_settings_page(self):
        """Navigate to the Settings page."""
        self._stop_training_if_active()
        self.settings_page = SettingsPage(main_window=self)
        self.stacked_main_window.addWidget(self.settings_page)
        self.stacked_main_window.setCurrentWidget(self.settings_page)

    def switch_to_demo_mode_page(self):
        """Navigate to the Demo Mode (video upload) page."""
        self._stop_training_if_active()
        self.demo_mode_page = DemoModePage(main_window=self)
        self.stacked_main_window.addWidget(self.demo_mode_page)
        self.stacked_main_window.setCurrentWidget(self.demo_mode_page)
        logger.info("Switched to Demo Mode page.")

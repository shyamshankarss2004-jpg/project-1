"""
windows/main_pages/home_page.py
--------------------------------
Home page: lets the user pick a workout plan and start a training session.
"""

from PyQt5.QtWidgets import QWidget, QMessageBox
from PyQt5.uic import loadUi

from windows.main_pages.main_training.training_start import Training
from data.database_manager import get_all_workouts, get_workout_exercises
from utils.resource_helper import resource_path


class HomePage(QWidget):
    """
    Home page that shows a workout plan selector and starts training sessions.

    Displays the list of exercises in the chosen plan before the user
    confirms by clicking Start.
    """

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        loadUi(resource_path("ui/pages/home_page.ui"), self)

        self.main_window = main_window
        self.stackedWidget.hide()

        self._load_workouts()
        self._load_exercises(self.list_workouts.currentText())

        self.list_workouts.currentTextChanged.connect(self._load_exercises)
        self.start_button.clicked.connect(self._start_training)

    # ── Data Loading ───────────────────────────────────────────────────────────

    def _load_workouts(self):
        """Populate the workout plan drop-down from the database."""
        user = self.main_window.current_userid
        workouts = get_all_workouts(user)
        self.list_workouts.clear()
        for workout in workouts:
            self.list_workouts.addItem(workout[2])

    def _load_exercises(self, workout_name: str):
        """
        Display the exercises belonging to the selected workout plan.

        Shows a placeholder message and hides the Start button if the plan
        has no exercises configured.

        Args:
            workout_name: The name of the currently selected workout plan.
        """
        user = self.main_window.current_userid
        exercises = get_workout_exercises(workout_name, user)
        self.list_exercises.clear()

        for index, exercise in enumerate(exercises, start=1):
            emoji = "🎦" if exercise[2] == 1 else " "
            entry = f"{index}.{emoji}{exercise[0]} × {exercise[1]}"
            self.list_exercises.addItem(entry)

        if self.list_exercises.count() == 0:
            self.start_button.hide()
            self.list_exercises.addItem("No exercises in this workout plan.")
        else:
            self.start_button.show()

    # ── Training ───────────────────────────────────────────────────────────────

    def _start_training(self):
        """Hide the plan preview and launch the training widget."""
        self.list_workouts.hide()
        self.list_exercises.hide()
        self.start_button.hide()

        user = self.main_window.current_userid
        workout = self.list_workouts.currentText()

        self.stackedWidget.show()
        self.training_widget = Training(self, user, workout)
        self.stackedWidget.addWidget(self.training_widget)
        self.stackedWidget.setCurrentWidget(self.training_widget)

    def stop_training_if_any(self):
        """
        Safely stop an active training session if one is running.

        Called by the main window before navigating away from this page,
        ensuring the camera and MediaPipe resources are released cleanly.
        """
        if not hasattr(self, "training_widget") or self.training_widget is None:
            return
        if self.stackedWidget.currentWidget() is self.training_widget:
            self.training_widget.stop_all()
            self.stackedWidget.removeWidget(self.training_widget)
            self.training_widget.deleteLater()
            self.training_widget = None

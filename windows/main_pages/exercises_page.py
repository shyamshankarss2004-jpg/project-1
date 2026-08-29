"""
windows/main_pages/exercises_page.py
-------------------------------------
Displays the exercise library with search, filtering, GIF preview,
and options to add or delete user-created exercises.
"""

from PyQt5.QtWidgets import QWidget, QMessageBox
from PyQt5.QtGui import QMovie
from PyQt5.QtCore import Qt, QTimer
from PyQt5.uic import loadUi

from data.database_manager import (
    get_all_muscle_group,
    search_exercises,
    add_exercise,
    check_if_exercise_exist,
    get_exercise,
    check_if_exercise_is_created_by_user,
    delete_exercise_and_links,
)
from utils.resource_helper import resource_path

# Map of exercise names to their corresponding GIF filenames
_EXERCISE_GIF_MAP = {
    "Jumping Jacks": "jumps.gif",
    "Squats": "squat.gif",
    "Bicep Curls": "curl.gif",
    "Overhead Press": "ohp.gif",
}


class ExercisesPage(QWidget):
    """
    Exercise library page.

    Allows users to browse, search, and filter exercises by muscle group.
    User-created exercises can be added and deleted. Camera-tracked
    exercises display an animated GIF preview.
    """

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        loadUi(resource_path("ui/pages/exercises_page.ui"), self)

        self.main_window = main_window
        self.selected_exercise = None
        self.user_exercise = None
        self.movie = None

        self._setup_ui()
        self._connect_signals()
        self.load_muscles()
        self.update_exercises()

    # ── Initialisation ─────────────────────────────────────────────────────────

    def _setup_ui(self):
        """Hide widgets that should only appear after user interaction."""
        self.delete_exercise_button.hide()
        self.widget_description.hide()
        self.add_exercise_widget.hide()
        self.gif_label.hide()

    def _connect_signals(self):
        """Wire up all interactive widget signals."""
        self.muscle_Box_1.currentIndexChanged.connect(self.update_exercises)
        self.searchExercise.textChanged.connect(self.update_exercises)
        self.addExercise.clicked.connect(self._add_exercise)
        self.listExercises.itemClicked.connect(self._exercise_clicked)
        self.listExercises.itemClicked.connect(self.add_exercise_widget.hide)
        self.listExercises.itemClicked.connect(self.addExercise1_button.show)
        self.delete_exercise_button.clicked.connect(self._delete_exercise)
        self.addExercise1_button.clicked.connect(self.add_exercise_widget.show)
        self.addExercise1_button.clicked.connect(self.addExercise1_button.hide)

        # Timer keeps the GIF scaled to the label's current size
        self._gif_timer = QTimer(self)
        self._gif_timer.setInterval(10)
        self._gif_timer.timeout.connect(self._update_scaled_gif)
        self._gif_timer.start()

    # ── Data Loading ───────────────────────────────────────────────────────────

    def load_muscles(self):
        """Populate both muscle-group combo boxes from the database."""
        self.muscle_Box_1.clear()
        self.muscle_Box_2.clear()
        self.muscle_Box_1.addItem("Any")
        for muscle in get_all_muscle_group():
            self.muscle_Box_1.addItem(muscle)
            self.muscle_Box_2.addItem(muscle)

    def update_exercises(self):
        """Refresh the exercise list based on the current search term and filter."""
        name = self.searchExercise.text()
        muscle_type = self.muscle_Box_1.currentText()
        if muscle_type == "Any":
            muscle_type = None
        user = self.main_window.current_userid

        exercises = search_exercises(name, muscle_type, user)
        self.listExercises.clear()
        for exercise in exercises:
            exercise_name = exercise[1]
            has_video = exercise[3]
            display_name = f"🎦{exercise_name}" if has_video == 1 else exercise_name
            self.listExercises.addItem(display_name)

    # ── User Actions ───────────────────────────────────────────────────────────

    def _add_exercise(self):
        """Validate input and add a new exercise to the database."""
        name = self.addExerciseLineEdit.text().strip()
        muscle_type = self.muscle_Box_2.currentText()
        user = self.main_window.current_userid

        if not name:
            QMessageBox.warning(self, "Error", "Please enter the exercise name!")
            return
        if check_if_exercise_exist(name, user):
            QMessageBox.warning(self, "Error", "An exercise with this name already exists.")
            return

        if add_exercise(name, muscle_type, user):
            self.add_exercise_widget.hide()
            self.addExercise1_button.show()
            self.update_exercises()
        else:
            QMessageBox.warning(self, "Error", "Failed to add the exercise. Please try again.")

    def _exercise_clicked(self, item):
        """
        Display details and a GIF preview for the selected exercise.

        Args:
            item: The QListWidgetItem that was clicked.
        """
        self.widget_description.show()
        raw_name = item.text()
        self.selected_exercise = raw_name

        # Strip camera-tracking emoji prefix to get the plain name
        exercise_name = raw_name.lstrip("🎦").strip()

        if check_if_exercise_is_created_by_user(exercise_name):
            self.delete_exercise_button.show()
            self.user_exercise = True
        else:
            self.delete_exercise_button.hide()
            self.user_exercise = False

        exercise = get_exercise(exercise_name)
        if exercise:
            name = str(exercise[3])
            camera = int(exercise[4])
            description = str(exercise[5])
            self._update_description(name, description)
            self._show_gif(camera, name)

    def _delete_exercise(self):
        """Confirm and delete the currently selected user-created exercise."""
        exercise_name = self.selected_exercise
        if exercise_name and exercise_name.startswith("🎦"):
            exercise_name = exercise_name[1:].strip()

        user = self.main_window.current_userid

        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Question)
        confirm.setWindowTitle("Confirm Deletion")
        confirm.setText(
            f"Are you sure you want to delete '{exercise_name}'?\n"
            "This will also remove it from all workout plans."
        )
        confirm.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        confirm.button(QMessageBox.Yes).setText("Yes")
        confirm.button(QMessageBox.No).setText("No")

        if confirm.exec() == QMessageBox.Yes:
            try:
                if delete_exercise_and_links(exercise_name, user):
                    self.update_exercises()
                    self.exercises_textEdit.clear()
                    self.selected_exercise = None
                    self.delete_exercise_button.hide()
                    self.widget_description.hide()
                else:
                    QMessageBox.warning(self, "Error", "Failed to delete the exercise.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"An unexpected error occurred: {e}")

    # ── Description & GIF ──────────────────────────────────────────────────────

    def _update_description(self, exercise_name: str, description: str):
        """
        Populate the description text box.

        Args:
            exercise_name: Display name of the exercise.
            description: Exercise description text.
        """
        self.exercises_textEdit.setPlainText(
            f"Exercise name: {exercise_name}\n\nDescription:\n{description}\n"
        )

    def _show_gif(self, camera: int, exercise_name: str):
        """
        Show an animated GIF preview for camera-tracked exercises.

        Args:
            camera: 1 if the exercise supports pose tracking, 0 otherwise.
            exercise_name: Name used to look up the correct GIF file.
        """
        if camera == 0 or exercise_name not in _EXERCISE_GIF_MAP:
            self.gif_label.hide()
            return

        self.gif_label.show()
        gif_path = resource_path(f"ui/gifs/{_EXERCISE_GIF_MAP[exercise_name]}")
        self.movie = QMovie(gif_path)
        self.gif_label.setMovie(self.movie)
        self.movie.start()

    def _update_scaled_gif(self):
        """Scale the current GIF frame to fit the label while preserving aspect ratio."""
        if self.movie is not None:
            frame = self.movie.currentPixmap()
            if not frame.isNull():
                scaled = frame.scaled(
                    self.gif_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
                self.gif_label.setPixmap(scaled)
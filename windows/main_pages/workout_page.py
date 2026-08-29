"""
windows/main_pages/workout_page.py
-----------------------------------
Workout plan management page.

Users can create, view, and delete custom workout plans and manage
the exercises within each plan with configurable rep counts.
"""

from PyQt5.QtWidgets import QWidget, QMessageBox
from PyQt5.uic import loadUi

from data.database_manager import (
    check_if_workout_exist,
    add_workout,
    get_all_workouts,
    get_workout_exercises,
    delete_exercise_from_workout,
    check_if_workout_is_created_by_user,
    get_unused_exercises,
    add_workout_exercise,
    delete_workout_and_exercises,
)
from utils.resource_helper import resource_path


class WorkoutsPage(QWidget):
    """
    Workout plan management page.

    Displays all workout plans (global + user-created) in a list.
    When a user-owned plan is selected, its exercises are shown on the
    right and the user can add or remove exercises.
    """

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        loadUi(resource_path("ui/pages/workouts_page.ui"), self)

        self.main_window = main_window
        self.selected_workout = None
        self.user_workout = None

        self._setup_ui()
        self._connect_signals()
        self.update_workouts()

    # ── Initialisation ─────────────────────────────────────────────────────────

    def _setup_ui(self):
        """Hide panels that only appear after a workout plan is selected."""
        self.new_workout_widget.hide()
        self.delete_workout_button.hide()
        self.delete_exercise_button.hide()
        self.new_exercise_widget.hide()
        self.new_exercise_widget_2.hide()
        self.widget_right.hide()

    def _connect_signals(self):
        """Wire up all interactive widget signals."""
        self.add_workout_button_2.clicked.connect(self.new_workout_widget.show)
        self.add_workout_button_2.clicked.connect(self.new_workout_widget_2.hide)
        self.add_workout_button.clicked.connect(self._add_workout)

        self.add_workout_exercise_button_2.clicked.connect(self.new_exercise_widget.show)
        self.add_workout_exercise_button_2.clicked.connect(self._refresh_exercise_box)
        self.add_workout_exercise_button_2.clicked.connect(self.new_exercise_widget_2.hide)
        self.add_workout_exercise_button.clicked.connect(self._add_exercise)

        self.delete_workout_button.clicked.connect(self._delete_workout)
        self.list_workouts.itemClicked.connect(self._workout_item_clicked)

        self.delete_exercise_button.clicked.connect(self._delete_exercise)
        self.list_workout_exercises.itemClicked.connect(self._exercise_item_clicked)

    # ── Data Loading ───────────────────────────────────────────────────────────

    def update_workouts(self):
        """Reload the workout plan list from the database."""
        user = self.main_window.current_userid
        workouts = get_all_workouts(user)
        self.list_workouts.clear()
        for workout in workouts:
            self.list_workouts.addItem(workout[2])

    def _update_exercises(self, workout_name: str):
        """
        Reload the exercise list for the selected workout plan.

        Args:
            workout_name: The name of the currently selected workout plan.
        """
        user = self.main_window.current_userid
        exercises = get_workout_exercises(workout_name, user)
        self.list_workout_exercises.clear()
        for index, exercise in enumerate(exercises, start=1):
            emoji = "🎦" if exercise[2] == 1 else " "
            entry = f"{index}.{emoji}{exercise[0]} × {exercise[1]}"
            self.list_workout_exercises.addItem(entry)

    def _refresh_exercise_box(self):
        """Populate the 'add exercise' combo box with exercises not yet in the plan."""
        user = self.main_window.current_userid
        exercises = get_unused_exercises(self.selected_workout, user)
        self.exercises_box.clear()
        if exercises:
            for exercise in exercises:
                name, has_video = exercise[0], exercise[1]
                display = f"🎦{name}" if has_video == 1 else name
                self.exercises_box.addItem(display, userData=name)
        else:
            self.exercises_box.addItem("No exercises")

    # ── User Actions ───────────────────────────────────────────────────────────

    def _add_workout(self):
        """Validate and create a new user workout plan."""
        workout_name = self.workout_name_line.text().strip()
        user = self.main_window.current_userid

        if not workout_name:
            QMessageBox.warning(self, "Error", "Please enter the workout name!")
            return
        if check_if_workout_exist(workout_name, user):
            QMessageBox.warning(self, "Error", "A workout plan with this name already exists.")
            return

        if add_workout(workout_name, user):
            self.widget_right.hide()
            self.delete_workout_button.hide()
            self.new_workout_widget.hide()
            self.new_workout_widget_2.show()
            self.update_workouts()
        else:
            QMessageBox.warning(self, "Error", "Failed to add the workout plan.")

    def _add_exercise(self):
        """Add the selected exercise to the current workout plan."""
        index = self.exercises_box.currentIndex()
        exercise_name = self.exercises_box.itemData(index)
        reps = self.rep_box.text()

        if not exercise_name or exercise_name == "No exercises":
            QMessageBox.warning(
                self, "Error", "Please create new exercises or remove some from the plan."
            )
            return

        if add_workout_exercise(self.selected_workout, exercise_name, self.main_window.current_userid, int(reps)):
            self._update_exercises(self.selected_workout)
            self.new_exercise_widget.hide()
            self.new_exercise_widget_2.show()
        else:
            QMessageBox.warning(self, "Error", "Failed to add the exercise.")

    def _workout_item_clicked(self, item):
        """
        Handle workout plan selection: show exercises and update action buttons.

        Args:
            item: The QListWidgetItem that was clicked.
        """
        self.widget_right.show()
        self.new_exercise_widget.hide()
        self.delete_exercise_button.hide()
        workout_name = item.text()
        self.selected_workout = workout_name

        is_user_owned = check_if_workout_is_created_by_user(workout_name)
        self.user_workout = is_user_owned
        self.new_exercise_widget_2.setVisible(is_user_owned)
        self.delete_workout_button.setVisible(is_user_owned)

        self._update_exercises(workout_name)

    def _delete_workout(self):
        """Confirm and delete the selected user workout plan with all its exercises."""
        selected_item = self.list_workouts.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "Error", "No workout plan selected!")
            return

        workout_name = selected_item.text()
        user = self.main_window.current_userid

        confirm = QMessageBox(self)
        confirm.setIcon(QMessageBox.Question)
        confirm.setWindowTitle("Delete Confirmation")
        confirm.setText(
            f"Are you sure you want to delete '{workout_name}' along with its exercises?"
        )
        confirm.setStandardButtons(QMessageBox.Yes | QMessageBox.No)
        confirm.button(QMessageBox.Yes).setText("Yes")
        confirm.button(QMessageBox.No).setText("No")

        if confirm.exec() == QMessageBox.Yes:
            try:
                if delete_workout_and_exercises(workout_name, user):
                    self.update_workouts()
                    self.list_workout_exercises.clear()
                    self.delete_workout_button.hide()
                    self.selected_workout = None
                    self.widget_right.hide()
                else:
                    QMessageBox.warning(self, "Error", "Failed to delete the workout plan.")
            except Exception as e:
                QMessageBox.warning(self, "Error", f"An unexpected error occurred: {e}")

    def _delete_exercise(self):
        """Remove the selected exercise from the current workout plan."""
        selected_item = self.list_workout_exercises.currentItem()
        if not selected_item:
            QMessageBox.warning(self, "Error", "Please select an exercise to remove.")
            return

        exercise_text = selected_item.text()
        try:
            # Format: "1.🎦Exercise Name × 10"
            name_part = exercise_text.split(" × ")[0].split(".", 1)[1].strip()
            exercise_name = name_part.lstrip("🎦").strip()
        except IndexError:
            QMessageBox.warning(self, "Error", "Could not identify the selected exercise.")
            return

        workout_item = self.list_workouts.currentItem()
        if not workout_item:
            QMessageBox.warning(self, "Error", "No workout plan selected.")
            return

        user = self.main_window.current_userid
        try:
            if delete_exercise_from_workout(workout_item.text(), user, exercise_name):
                self.delete_exercise_button.hide()
                self._refresh_exercise_box()
                self._update_exercises(workout_item.text())
            else:
                QMessageBox.warning(self, "Error", "Default workout plans cannot be modified.")
        except Exception as e:
            QMessageBox.warning(self, "Error", f"An unexpected error occurred: {e}")

    def _exercise_item_clicked(self, item):
        """Show the delete button only for user-owned workout plans."""
        self.delete_exercise_button.setVisible(bool(self.user_workout))
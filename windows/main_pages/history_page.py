"""
windows/main_pages/history_page.py
------------------------------------
History page: displays a calendar with workout days highlighted and
allows the user to view the exercises performed on any selected day.
"""

from PyQt5.QtWidgets import QWidget, QListWidgetItem, QCalendarWidget
from PyQt5.uic import loadUi
from PyQt5.QtCore import Qt, QDate
from PyQt5.QtGui import QTextCharFormat, QBrush, QColor

from data.database_manager import get_day_history, get_history_workouts
from utils.resource_helper import resource_path

# Highlight format for calendar days that have workout history
_WORKOUT_DAY_FORMAT = QTextCharFormat()
_WORKOUT_DAY_FORMAT.setForeground(QBrush(QColor("white")))
_WORKOUT_DAY_FORMAT.setBackground(QBrush(QColor("red")))


class HistoryPage(QWidget):
    """
    Workout history page.

    Shows a monthly calendar with days highlighted that have recorded
    training sessions. Selecting a day lists the workouts done that day,
    and clicking a workout reveals the individual exercises performed.
    """

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        loadUi(resource_path("ui/pages/history_page.ui"), self)

        self.main_window = main_window
        self.user = self.main_window.current_userid

        self._setup_calendar()
        self._connect_signals()

        # Populate highlights and list for the current date immediately
        self._on_calendar_page_changed()
        self._on_date_changed()

    # ── Initialisation ─────────────────────────────────────────────────────────

    def _setup_calendar(self):
        """Configure the calendar widget appearance."""
        self.calendarWidget.setGridVisible(True)
        self.calendarWidget.setVerticalHeaderFormat(QCalendarWidget.NoVerticalHeader)

    def _connect_signals(self):
        """Wire up calendar and list signals."""
        self.calendarWidget.currentPageChanged.connect(self._on_calendar_page_changed)
        self.calendarWidget.selectionChanged.connect(self._on_date_changed)
        self.workouts_list.itemClicked.connect(self._on_workout_clicked)

    # ── Event Handlers ─────────────────────────────────────────────────────────

    def _on_date_changed(self):
        """Reload the workout list whenever the selected calendar date changes."""
        self.exercises_list.hide()
        selected_date = self.calendarWidget.selectedDate()

        year = selected_date.toString("yyyy")
        month = selected_date.toString("MM")
        day = selected_date.toString("dd")

        history_rows = get_history_workouts(self.user, year, month, day)
        self.workouts_list.clear()
        self.exercises_list.clear()

        if history_rows:
            self.history_label.setText(f"History for {year}-{month}-{day}")
            for workout_name, hour, minute, exercises_str in history_rows:
                time_str = f"{int(hour):02d}:{int(minute):02d}"
                item = QListWidgetItem(f"{time_str} - {workout_name}")
                item.setData(Qt.UserRole, exercises_str)
                self.workouts_list.addItem(item)
        else:
            self.history_label.setText("No history for the selected day.")

    def _on_calendar_page_changed(self):
        """Highlight all days in the displayed month that have workout history."""
        self.exercises_list.hide()
        year = self.calendarWidget.yearShown()
        month = self.calendarWidget.monthShown()
        days = get_day_history(self.user, year, month)
        for day in days:
            self.calendarWidget.setDateTextFormat(
                QDate(year, month, day), _WORKOUT_DAY_FORMAT
            )

    def _on_workout_clicked(self, item):
        """
        Show the exercise breakdown for the clicked workout session.

        Args:
            item: The QListWidgetItem carrying a semicolon-delimited exercise string.
        """
        exercises_str = item.data(Qt.UserRole)
        exercises = self._parse_exercises(exercises_str)
        self.exercises_list.show()
        self.exercises_list.clear()
        for idx, exercise in enumerate(exercises, start=1):
            self.exercises_list.addItem(f"{idx}. {exercise}")

    # ── Helpers ────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse_exercises(exercises_str: str) -> list:
        """
        Parse a semicolon-delimited exercise history string into readable lines.

        The stored format is: ``name1;reps1;name2;reps2;…``

        Args:
            exercises_str: The raw semicolon-delimited string from the database.

        Returns:
            A list of human-readable strings such as ``"Squats x 10"``.
        """
        exercises = []
        parts = exercises_str.strip(";").split(";")
        for i in range(0, len(parts) - 1, 2):
            name = parts[i].strip()
            reps = parts[i + 1].strip()
            exercises.append(f"{name} x {reps}")
        return exercises
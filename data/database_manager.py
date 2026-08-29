"""
data/database_manager.py
-------------------------
Data access layer for the Virtual Personal Trainer application.

All database operations are centralised here. Each function opens its
own short-lived connection using a context manager so resources are
always released promptly.
"""

import sqlite3

from utils.logger import get_logger
from utils.resource_helper import resource_path

logger = get_logger(__name__)

# ── Private helper ─────────────────────────────────────────────────────────────

def _get_db_path() -> str:
    """Return the absolute path to the application database."""
    return resource_path("data/database.db")


# ── Authentication ─────────────────────────────────────────────────────────────

def authenticate_user(username: str, password: str) -> bool:
    """
    Verify that a username/password combination exists in the database.

    Args:
        username: The account username.
        password: The 4-digit PIN as a string.

    Returns:
        True if the credentials are valid, False otherwise.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM users WHERE username = ? AND password = ?",
                (username, password),
            )
            return cursor.fetchone() is not None
    except sqlite3.Error as e:
        logger.error("Database error during authentication: %s", e)
        return False


def check_if_user_exist(username: str) -> bool:
    """
    Check whether a username is already taken.

    Args:
        username: The username to look up.

    Returns:
        True if the username is in use, False otherwise.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM users WHERE username = ?", (username,))
            return cursor.fetchone() is not None
    except sqlite3.Error as e:
        logger.error("Database error checking user existence: %s", e)
        return False


# ── User CRUD ──────────────────────────────────────────────────────────────────

def create_user(username: str, password: str):
    """
    Create a new user account with default settings.

    Args:
        username: Desired username.
        password: 4-digit PIN as a string.

    Returns:
        The new user's id (int) on success, or None on failure.
    """
    default_settings = {"mode": "auto", "prepare": 5, "rep": 2, "volume": 50, "camera": ""}
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password) VALUES (?, ?)",
                (username, password),
            )
            user_id = cursor.lastrowid
            cursor.execute(
                "INSERT INTO settings (user_id, mode, prepare, rep, volume, camera) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    user_id,
                    default_settings["mode"],
                    default_settings["prepare"],
                    default_settings["rep"],
                    default_settings["volume"],
                    default_settings["camera"],
                ),
            )
            conn.commit()
            logger.info("Created user '%s' (id=%s).", username, user_id)
            return user_id
    except sqlite3.Error as e:
        logger.error("Database error creating user '%s': %s", username, e)
        return None


def delete_user_account(user_id: int) -> bool:
    """
    Permanently delete a user account and all related data.

    Relies on foreign-key cascades in the schema.

    Args:
        user_id: The id of the account to delete.

    Returns:
        True on success, False on failure.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            conn.execute("PRAGMA foreign_keys = ON;")
            cursor = conn.cursor()
            cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
            conn.commit()
            logger.info("Deleted user account id=%s.", user_id)
            return True
    except sqlite3.Error as e:
        logger.error("Database error deleting user id=%s: %s", user_id, e)
        return False


def get_all_users() -> list:
    """
    Retrieve a list of all registered usernames.

    Returns:
        A list of username strings.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT username FROM users")
            return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error("Database error fetching users: %s", e)
        return []


def get_user_id(username: str):
    """
    Look up the numeric id of a user by username.

    Args:
        username: The account username.

    Returns:
        The user id (int), or None if not found.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM users WHERE username = ?", (username,))
            result = cursor.fetchone()
            return result[0] if result else None
    except sqlite3.Error as e:
        logger.error("Database error fetching user id for '%s': %s", username, e)
        return None


def get_user_name(user_id: int):
    """
    Look up the display name of a user by id.

    Args:
        user_id: The numeric user id.

    Returns:
        The name string, or None if not found.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM users WHERE id = ?", (user_id,))
            result = cursor.fetchone()
            return result[0] if result else None
    except sqlite3.Error as e:
        logger.error("Database error fetching name for user id=%s: %s", user_id, e)
        return None


def update_username(user_id: int, new_username: str) -> bool:
    """
    Change the username of an existing account.

    Args:
        user_id: The id of the account to update.
        new_username: The new desired username.

    Returns:
        True if the row was updated, False otherwise.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE users SET username = ? WHERE id = ?", (new_username, user_id)
            )
            conn.commit()
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error("Database error updating username for user id=%s: %s", user_id, e)
        return False


# ── Settings ───────────────────────────────────────────────────────────────────

def get_setting(user_id: int, setting_name: str):
    """
    Retrieve a single setting value for a user.

    Args:
        user_id: The user's numeric id.
        setting_name: Column name in the settings table.

    Returns:
        The setting value, or None if not found / on error.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"SELECT {setting_name} FROM settings WHERE user_id = ?", (user_id,)
            )
            result = cursor.fetchone()
            return result[0] if result else None
    except sqlite3.Error as e:
        logger.error("Database error reading setting '%s' for user id=%s: %s", setting_name, user_id, e)
        return None


def set_setting(user_id: int, setting_name: str, value) -> bool:
    """
    Update a single setting value for a user.

    Args:
        user_id: The user's numeric id.
        setting_name: Column name in the settings table.
        value: The new value to store.

    Returns:
        True on success, False on failure.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                f"UPDATE settings SET {setting_name} = ? WHERE user_id = ?",
                (value, user_id),
            )
            conn.commit()
            return True
    except sqlite3.Error as e:
        logger.error("Database error updating setting '%s' for user id=%s: %s", setting_name, user_id, e)
        return False


# ── Muscle Groups ──────────────────────────────────────────────────────────────

def get_all_muscle_group() -> list:
    """
    Retrieve all muscle group names.

    Returns:
        A list of muscle group name strings.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM muscle_group")
            return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error("Database error fetching muscle groups: %s", e)
        return []


# ── Exercises ──────────────────────────────────────────────────────────────────

def get_exercise(name: str):
    """
    Fetch a single exercise row by name.

    Args:
        name: The exercise name.

    Returns:
        The full row tuple, or None if not found.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM exercises WHERE name = ?", (name,))
            return cursor.fetchone()
    except sqlite3.Error as e:
        logger.error("Database error fetching exercise '%s': %s", name, e)
        return None


def search_exercises(search_term: str = "", muscle_group_name=None, user_id=None) -> list:
    """
    Search exercises by name substring and optional muscle group filter.

    Args:
        search_term: Partial name to match (case-insensitive LIKE).
        muscle_group_name: Optional muscle group to filter by.
        user_id: Show only global exercises and exercises created by this user.

    Returns:
        A list of exercise row tuples.
    """
    query = """
        SELECT e.id, e.name, mg.name, e.camera AS muscle_group
        FROM exercises e
        LEFT JOIN muscle_group mg ON e.muscle_id = mg.id
        WHERE e.name LIKE ?
          AND (? IS NULL OR mg.name = ?)
          AND (? IS NULL OR e.created_by_user_id = ? OR e.created_by_user_id IS NULL)
        ORDER BY e.name ASC
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                query,
                (f"%{search_term}%", muscle_group_name, muscle_group_name, user_id, user_id),
            )
            return cursor.fetchall()
    except sqlite3.Error as e:
        logger.error("Database error searching exercises: %s", e)
        return []


def get_all_exercises(user_id: int) -> list:
    """
    Retrieve all exercises visible to the given user (global + user-created).

    Args:
        user_id: The user's numeric id.

    Returns:
        A list of exercise row tuples.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM exercises WHERE (created_by_user_id = ? OR created_by_user_id IS NULL)",
                (user_id,),
            )
            return cursor.fetchall()
    except sqlite3.Error as e:
        logger.error("Database error fetching exercises for user id=%s: %s", user_id, e)
        return []


def add_exercise(exercise_name: str, muscle_group_name: str, user_id: int) -> bool:
    """
    Insert a new custom exercise for a user.

    Args:
        exercise_name: Name for the new exercise.
        muscle_group_name: Must match an existing muscle group name.
        user_id: Owner of the new exercise.

    Returns:
        True on success, False if the muscle group is not found or on error.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM muscle_group WHERE name = ?", (muscle_group_name,))
            result = cursor.fetchone()
            if result is None:
                logger.warning("Muscle group '%s' not found.", muscle_group_name)
                return False
            muscle_id = result[0]
            cursor.execute(
                "INSERT INTO exercises (name, muscle_id, created_by_user_id, camera) VALUES (?, ?, ?, ?)",
                (exercise_name, muscle_id, user_id, 0),
            )
            conn.commit()
            return True
    except sqlite3.Error as e:
        logger.error("Database error adding exercise '%s': %s", exercise_name, e)
        return False


def check_if_exercise_exist(exercise: str, username) -> bool:
    """
    Check whether an exercise with the given name already exists for a user.

    Args:
        exercise: Exercise name to look up.
        username: User id or username used for ownership check.

    Returns:
        True if the exercise exists, False otherwise.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM exercises "
                "WHERE (name = ? AND (created_by_user_id = ? OR created_by_user_id IS NULL))",
                (exercise, username),
            )
            return cursor.fetchone() is not None
    except sqlite3.Error as e:
        logger.error("Database error checking exercise existence: %s", e)
        return False


def check_if_exercise_is_created_by_user(exercise_name: str) -> bool:
    """
    Determine whether an exercise was created by a user (vs. system default).

    Args:
        exercise_name: The exercise name to look up.

    Returns:
        True if user-created, False if a global default (or on error).
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT created_by_user_id FROM exercises WHERE name = ?",
                (exercise_name,),
            )
            result = cursor.fetchone()
            return result is not None and result[0] is not None
    except sqlite3.Error as e:
        logger.error("Database error checking exercise ownership for '%s': %s", exercise_name, e)
        return False


def delete_exercise_and_links(exercise_name: str, user_id: int) -> bool:
    """
    Delete a user-created exercise and remove it from all workout plans.

    Args:
        exercise_name: Name of the exercise to delete.
        user_id: Owner's user id.

    Returns:
        True on success, False on failure.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM id_exercises_id_workout "
                "WHERE id_exercise = (SELECT id FROM exercises WHERE name = ? AND created_by_user_id = ?)",
                (exercise_name, user_id),
            )
            cursor.execute(
                "DELETE FROM exercises WHERE name = ? AND created_by_user_id = ?",
                (exercise_name, user_id),
            )
            conn.commit()
            return True
    except sqlite3.Error as e:
        logger.error("Database error deleting exercise '%s': %s", exercise_name, e)
        return False


def get_unused_exercises(workout_name: str, user_id: int) -> list:
    """
    Return exercises not yet added to a specific workout plan.

    Args:
        workout_name: Name of the workout plan.
        user_id: The user's numeric id.

    Returns:
        A list of (name, camera) tuples.
    """
    query = """
        SELECT name, camera
        FROM exercises
        WHERE id NOT IN (
            SELECT id_exercise
            FROM id_exercises_id_workout
            WHERE id_workout = (
                SELECT id FROM workout_plans
                WHERE name = ? AND created_by_user_id = ?
            )
        ) AND (created_by_user_id IS NULL OR created_by_user_id = ?)
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (workout_name, user_id, user_id))
            return cursor.fetchall()
    except sqlite3.Error as e:
        logger.error("Database error fetching unused exercises: %s", e)
        return []


# ── Workout Plans ──────────────────────────────────────────────────────────────

def get_all_workouts(user_id: int) -> list:
    """
    Retrieve all workout plans visible to a user (global + user-created).

    Args:
        user_id: The user's numeric id.

    Returns:
        A list of workout plan row tuples.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM workout_plans "
                "WHERE (created_by_user_id = ? OR created_by_user_id IS NULL)",
                (user_id,),
            )
            return cursor.fetchall()
    except sqlite3.Error as e:
        logger.error("Database error fetching workouts for user id=%s: %s", user_id, e)
        return []


def add_workout(workout_name: str, user_id: int) -> bool:
    """
    Create a new user workout plan.

    Args:
        workout_name: Name for the new plan.
        user_id: Owner's user id.

    Returns:
        True on success, False on failure.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO workout_plans (name, created_by_user_id) VALUES (?, ?)",
                (workout_name, user_id),
            )
            conn.commit()
            return True
    except sqlite3.Error as e:
        logger.error("Database error adding workout '%s': %s", workout_name, e)
        return False


def check_if_workout_exist(workout: str, user_id: int) -> bool:
    """
    Check whether a workout plan with the given name already exists for a user.

    Args:
        workout: Workout plan name.
        user_id: The user's numeric id.

    Returns:
        True if it exists, False otherwise.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT 1 FROM workout_plans "
                "WHERE name = ? AND (created_by_user_id = ? OR created_by_user_id IS NULL)",
                (workout, user_id),
            )
            return cursor.fetchone() is not None
    except sqlite3.Error as e:
        logger.error("Database error checking workout existence: %s", e)
        return False


def check_if_workout_is_created_by_user(workout_name: str) -> bool:
    """
    Determine whether a workout plan was created by a user (vs. system default).

    Args:
        workout_name: The workout plan name.

    Returns:
        True if user-created, False if a global default (or on error).
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT created_by_user_id FROM workout_plans WHERE name = ?",
                (workout_name,),
            )
            result = cursor.fetchone()
            return result is not None and result[0] is not None
    except sqlite3.Error as e:
        logger.error("Database error checking workout ownership for '%s': %s", workout_name, e)
        return False


def get_workout_id_by_name(user_id: int, workout_name: str):
    """
    Resolve a workout plan name to its numeric id.

    First checks user-owned plans, then falls back to global plans.

    Args:
        user_id: The user's numeric id.
        workout_name: The workout plan name.

    Returns:
        The workout id (int), or None if not found.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            # User-owned first
            cursor.execute(
                "SELECT id FROM workout_plans "
                "WHERE created_by_user_id = ? AND name = ? LIMIT 1",
                (user_id, workout_name),
            )
            result = cursor.fetchone()
            if result:
                return result[0]
            # Fall back to global
            cursor.execute(
                "SELECT id FROM workout_plans "
                "WHERE created_by_user_id IS NULL AND name = ? LIMIT 1",
                (workout_name,),
            )
            result = cursor.fetchone()
            return result[0] if result else None
    except sqlite3.Error as e:
        logger.error("Database error resolving workout id for '%s': %s", workout_name, e)
        return None


def get_workout_exercises(workout_name: str, user_id: int) -> list:
    """
    Retrieve all exercises belonging to a named workout plan.

    Args:
        workout_name: The workout plan name.
        user_id: The user's numeric id (used for ownership filtering).

    Returns:
        A list of (exercise_name, reps, camera, id, muscle_id) tuples.
    """
    query = """
        SELECT exercises.name, id_exercises_id_workout.reps,
               exercises.camera, id_exercises_id_workout.id, exercises.muscle_id
        FROM workout_plans
        JOIN id_exercises_id_workout ON workout_plans.id = id_exercises_id_workout.id_workout
        JOIN exercises ON id_exercises_id_workout.id_exercise = exercises.id
        WHERE workout_plans.name = ?
          AND (workout_plans.created_by_user_id = ? OR workout_plans.created_by_user_id IS NULL)
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (workout_name, user_id))
            return cursor.fetchall()
    except sqlite3.Error as e:
        logger.error("Database error fetching exercises for workout '%s': %s", workout_name, e)
        return []


def add_workout_exercise(workout_name: str, exercise_name: str, user_id: int, reps: int) -> bool:
    """
    Add an exercise to an existing user workout plan.

    Args:
        workout_name: Target workout plan name.
        exercise_name: Name of the exercise to add.
        user_id: Owner's user id.
        reps: Number of repetitions / seconds.

    Returns:
        True on success, False on failure.
    """
    query = """
        INSERT INTO id_exercises_id_workout (id_workout, id_exercise, reps)
        VALUES (
            (SELECT id FROM workout_plans WHERE name = ? AND created_by_user_id = ?),
            (SELECT id FROM exercises WHERE name = ?),
            ?
        )
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (workout_name, user_id, exercise_name, reps))
            conn.commit()
            return True
    except sqlite3.Error as e:
        logger.error("Database error adding exercise to workout: %s", e)
        return False


def delete_exercise_from_workout(workout_name: str, user_id: int, exercise_name: str) -> bool:
    """
    Remove a single exercise from a user workout plan.

    Args:
        workout_name: The workout plan name.
        user_id: Owner's user id.
        exercise_name: Name of the exercise to remove.

    Returns:
        True if a row was deleted, False otherwise.
    """
    query = """
        DELETE FROM id_exercises_id_workout
        WHERE id_workout = (
            SELECT id FROM workout_plans WHERE name = ? AND created_by_user_id = ?
        )
        AND id_exercise = (SELECT id FROM exercises WHERE name = ?)
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(query, (workout_name, user_id, exercise_name))
            conn.commit()
            return cursor.rowcount > 0
    except sqlite3.Error as e:
        logger.error("Database error removing exercise from workout: %s", e)
        return False


def delete_workout_and_exercises(workout_name: str, user_id: int) -> bool:
    """
    Delete a user workout plan and all its exercise associations.

    Args:
        workout_name: The workout plan name.
        user_id: Owner's user id.

    Returns:
        True on success, False on failure.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "DELETE FROM id_exercises_id_workout "
                "WHERE id_workout = (SELECT id FROM workout_plans WHERE name = ? AND created_by_user_id = ?)",
                (workout_name, user_id),
            )
            cursor.execute(
                "DELETE FROM workout_plans WHERE name = ? AND created_by_user_id = ?",
                (workout_name, user_id),
            )
            conn.commit()
            return True
    except sqlite3.Error as e:
        logger.error("Database error deleting workout '%s': %s", workout_name, e)
        return False


# ── Training History ───────────────────────────────────────────────────────────

def insert_history_record(
    user_id: int, workout_name: str,
    year: int, month: int, day: int,
    hour: int, minute: int,
    exercises_str: str,
) -> bool:
    """
    Save a completed training session to the history table.

    Args:
        user_id: The user's numeric id.
        workout_name: Name of the completed workout plan.
        year, month, day, hour, minute: Timestamp components.
        exercises_str: Semicolon-delimited exercise summary string.

    Returns:
        True on success, False on failure.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO history (user_id, workout_name, year, month, day, hour, minute, exercises) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (user_id, workout_name, year, month, day, hour, minute, exercises_str),
            )
            conn.commit()
            logger.info("History record saved for user id=%s, workout='%s'.", user_id, workout_name)
            return True
    except sqlite3.Error as e:
        logger.error("Database error saving history record: %s", e)
        return False


def get_history_workouts(user_id: int, year: str, month: str, day: str) -> list:
    """
    Fetch all workout sessions for a specific calendar day.

    Args:
        user_id: The user's numeric id.
        year, month, day: Date components as zero-padded strings.

    Returns:
        A list of (workout_name, hour, minute, exercises_str) tuples.
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT h.workout_name, h.hour, h.minute, h.exercises "
                "FROM history h "
                "WHERE h.user_id = ? AND h.year = ? AND h.month = ? AND h.day = ? "
                "ORDER BY h.hour, h.minute ASC",
                (user_id, year, month, day),
            )
            return cursor.fetchall()
    except sqlite3.Error as e:
        logger.error("Database error fetching history workouts: %s", e)
        return []


def get_day_history(user_id: int, year: int, month: int) -> list:
    """
    Retrieve distinct days in a month that have training history.

    Args:
        user_id: The user's numeric id.
        year: Four-digit year.
        month: Month number (1–12).

    Returns:
        A sorted list of day numbers (ints).
    """
    try:
        with sqlite3.connect(_get_db_path()) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT DISTINCT day FROM history "
                "WHERE user_id = ? AND year = ? AND month = ? "
                "ORDER BY day ASC",
                (user_id, year, month),
            )
            return [row[0] for row in cursor.fetchall()]
    except sqlite3.Error as e:
        logger.error("Database error fetching history days: %s", e)
        return []

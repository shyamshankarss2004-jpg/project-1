"""
utils/validators.py
--------------------
Reusable input-validation helpers shared across window classes.

Centralising validation here eliminates the duplicated inline checks
that previously appeared in LoginWindow and NewAccountWindow.
"""

from config import MAX_USERNAME_LENGTH, PIN_DIGIT_COUNT


def is_pin_complete(pin_fields: list) -> bool:
    """
    Check that every PIN digit field contains exactly one character.

    Args:
        pin_fields: A list of QLineEdit widgets representing PIN digits.

    Returns:
        True if all fields are non-empty, False otherwise.
    """
    return all(field.text() != "" for field in pin_fields)


def get_pin_string(pin_fields: list) -> str:
    """
    Concatenate PIN digit fields into a single string.

    Args:
        pin_fields: A list of QLineEdit widgets representing PIN digits.

    Returns:
        The PIN as a concatenated string (e.g. "1234").
    """
    return "".join(field.text() for field in pin_fields)


def is_valid_username(username: str) -> tuple[bool, str]:
    """
    Validate a username string against application rules.

    Rules:
        - Must not be empty.
        - Must not exceed MAX_USERNAME_LENGTH characters.

    Args:
        username: The username string to validate (should be stripped).

    Returns:
        A (is_valid, error_message) tuple.
        error_message is an empty string when is_valid is True.
    """
    if not username:
        return False, "Please enter a username!"
    if len(username) > MAX_USERNAME_LENGTH:
        return False, f"The maximum username length is {MAX_USERNAME_LENGTH} characters."
    return True, ""


def handle_pin_focus(current_field, previous_field, next_field) -> None:
    """
    Auto-advance or retreat focus between PIN digit fields.

    Should be connected to each field's textChanged signal:
        field.textChanged.connect(
            lambda: handle_pin_focus(field, prev_field, next_field)
        )

    Args:
        current_field: The QLineEdit that just changed.
        previous_field: The QLineEdit before current (or None if first).
        next_field: The QLineEdit after current (or None if last).
    """
    text = current_field.text()
    if len(text) == 1 and next_field:
        next_field.setFocus()
    elif len(text) == 0 and previous_field:
        previous_field.setFocus()

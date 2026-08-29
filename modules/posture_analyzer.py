"""
modules/posture_analyzer.py
----------------------------
Rule-based posture feedback for each supported exercise.

Each public function takes joint angles and positions and returns a
feedback dictionary with three keys:
    message   (str)   – human-readable correction or confirmation
    is_correct (bool) – True when form is acceptable
    color      (tuple) – BGR colour for on-frame text (green / red)
"""

# ── Colour constants (BGR) ─────────────────────────────────────────────────────
_GREEN = (0, 200, 0)
_RED   = (0, 0, 220)


def _feedback(message: str, is_correct: bool) -> dict:
    """Build a standardised feedback dictionary."""
    return {
        "message": message,
        "is_correct": is_correct,
        "color": _GREEN if is_correct else _RED,
    }


# ── Squat ──────────────────────────────────────────────────────────────────────

def analyze_squat_form(
    avg_knee_angle: float,
    in_squat: bool,
    knee_over_toe: bool = False,
) -> dict:
    """
    Evaluate squat posture from bilateral knee angles.

    Args:
        avg_knee_angle: Average of left and right knee angles (degrees).
        in_squat:       True when the user is in the lowered position.
        knee_over_toe:  True when a knee has passed noticeably over its ankle.

    Returns:
        Feedback dict (message, is_correct, color).
    """
    if not in_squat:
        return _feedback("Stand tall, then squat.", True)
    if knee_over_toe:
        return _feedback("Keep Knees Behind Toes!", False)
    if avg_knee_angle > 90:
        return _feedback("Go Lower!", False)
    return _feedback("Good Form \u2713", True)


# ── Overhead Press ─────────────────────────────────────────────────────────────

def analyze_ohp_form(l_forearm_angle: float, r_forearm_angle: float,
                     tolerance: float = 20) -> dict:
    """
    Evaluate overhead press posture via forearm perpendicularity.

    Args:
        l_forearm_angle: Left forearm angle from horizontal (degrees).
        r_forearm_angle: Right forearm angle from horizontal (degrees).
        tolerance:       Acceptable deviation from 90° (degrees).

    Returns:
        Feedback dict.
    """
    l_ok = abs(l_forearm_angle - 90) <= tolerance
    r_ok = abs(r_forearm_angle - 90) <= tolerance
    if not l_ok or not r_ok:
        return _feedback("Keep Forearms Perpendicular!", False)
    return _feedback("Good Form \u2713", True)


# ── Bicep Curl ─────────────────────────────────────────────────────────────────

def analyze_curl_form(avg_angle: float, stage: str) -> dict:
    """
    Evaluate bicep curl posture from average elbow angle.

    Args:
        avg_angle: Average of left and right elbow angles (degrees).
        stage:     Current movement stage ("up" = extended, "down" = curled).

    Returns:
        Feedback dict.
    """
    if stage == "down":          # Fully curled position
        if avg_angle < 50:
            return _feedback("Good Form \u2713", True)
        return _feedback("Curl Higher!", False)
    if stage == "up":            # Fully extended position
        if avg_angle > 155:
            return _feedback("Full Extension \u2713", True)
        return _feedback("Extend Arms Fully!", False)
    return _feedback("Keep Going...", True)


# ── Jumping Jacks ──────────────────────────────────────────────────────────────

def analyze_jumping_jack_form(l_arm: float, r_arm: float,
                               feet_wide: bool, stage: str) -> dict:
    """
    Evaluate jumping jack form from arm angles and foot spread.

    Args:
        l_arm, r_arm: Left and right arm angle from hip (degrees).
        feet_wide:    True when feet are spread past shoulder width.
        stage:        "down" = arms up feet wide, "up" = arms down feet close.

    Returns:
        Feedback dict.
    """
    if stage == "down":
        if l_arm > 140 and r_arm > 140 and feet_wide:
            return _feedback("Good Form \u2713", True)
        if not feet_wide:
            return _feedback("Spread Feet Wider!", False)
        return _feedback("Raise Arms Higher!", False)
    return _feedback("Keep Going...", True)


# ── Lunge ──────────────────────────────────────────────────────────────────────

def analyze_lunge_form(min_knee_angle: float, is_asymmetric: bool,
                        in_lunge: bool) -> dict:
    """
    Evaluate lunge posture.

    Args:
        min_knee_angle: Smaller of the two knee angles (degrees).
        is_asymmetric:  True when one knee is significantly more bent (lunge vs squat).
        in_lunge:       True when the lunge-down position is detected.

    Returns:
        Feedback dict.
    """
    if not in_lunge:
        return _feedback("Step forward and lunge down.", True)
    if not is_asymmetric:
        return _feedback("That looks like a squat \u2014 step one foot forward!", False)
    if min_knee_angle < 95:
        return _feedback("Good Form \u2713", True)
    return _feedback("Bend Your Front Knee More!", False)

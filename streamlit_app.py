"""
streamlit_app.py
----------------
Standalone Streamlit demo for the Virtual Personal Trainer.

This app runs independently of the PyQt5 application and requires only
OpenCV, MediaPipe, and Streamlit.  It is designed for live demonstration
at a final year project review.

Run with:
    streamlit run streamlit_app.py
"""

import math
import time
import datetime

import cv2
import numpy as np
import mediapipe as mp
import streamlit as st

from modules.posture_analyzer import (
    analyze_squat_form,
    analyze_ohp_form,
    analyze_curl_form,
    analyze_jumping_jack_form,
    analyze_lunge_form,
)
from utils.session_logger import SessionLogger

# ── Page configuration ─────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Virtual Personal Trainer",
    page_icon="💪",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS styling ────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    .stApp { background-color: #0d1117; }
    div[data-testid="metric-container"] {
        background: #161b22;
        border: 1px solid #30363d;
        border-radius: 8px;
        padding: 12px;
    }
    .feedback-good  { color: #3fb950; font-size: 1.2rem; font-weight: 700; }
    .feedback-bad   { color: #f85149; font-size: 1.2rem; font-weight: 700; }
    .section-title  { color: #58a6ff; font-size: 1rem;
                      text-transform: uppercase; letter-spacing: 2px;
                      border-bottom: 1px solid #21262d; padding-bottom: 6px; }
    .stButton > button {
        border-radius: 6px; font-weight: 600;
        padding: 0.5rem 1.5rem;
    }
</style>
""", unsafe_allow_html=True)

# ── Constants ──────────────────────────────────────────────────────────────────
_MIN_VIS       = 0.5
_EXERCISES     = ["Squats", "Overhead Press", "Bicep Curls", "Jumping Jacks", "Lunges"]
_GREEN_BGR     = (0, 200, 0)
_RED_BGR       = (0, 0, 220)
_FONT          = cv2.FONT_HERSHEY_SIMPLEX

# ── Session-state initialisation ───────────────────────────────────────────────
_DEFAULTS = {
    "running":    False,
    "cap":        None,
    "pose":       None,
    "mp_pose":    None,
    "mp_draw":    None,
    "counter":    0,
    "stage":      None,
    "form_msg":   "Press ▶ Start Workout to begin",
    "form_ok":    True,
    "start_time": None,
    "exercise":   "Squats",
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v


# ── Helper: angle calculation ──────────────────────────────────────────────────

def _angle(a, b, c) -> float:
    """Compute the angle at joint *b* from three MediaPipe landmarks."""
    ba = np.array([a.x - b.x, a.y - b.y])
    bc = np.array([c.x - b.x, c.y - b.y])
    cosine = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8)
    return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))


def _vis_ok(lm, *ids) -> bool:
    return all(lm[i.value].visibility > _MIN_VIS for i in ids)


def _put_text(frame, text, pos, color_bgr):
    cv2.putText(frame, text, pos, _FONT, 0.75, color_bgr, 2, cv2.LINE_AA)


# ── Frame processing ───────────────────────────────────────────────────────────

def _process_frame(frame, exercise: str):
    """
    Run MediaPipe Pose on one frame and update session state counters.

    Args:
        frame:    BGR NumPy frame captured from the webcam.
        exercise: Currently selected exercise name.

    Returns:
        Annotated BGR frame.
    """
    pose_obj  = st.session_state.pose
    mp_pose   = st.session_state.mp_pose
    mp_draw   = st.session_state.mp_draw

    frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results   = pose_obj.process(frame_rgb)

    if not results or not results.pose_landmarks:
        _put_text(frame, "No pose detected", (30, 60), (0, 165, 255))
        return frame

    mp_draw.draw_landmarks(frame, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
    lm = results.pose_landmarks.landmark
    PL = mp_pose.PoseLandmark

    try:
        if   exercise == "Squats":        _run_squats(lm, PL, frame)
        elif exercise == "Overhead Press": _run_ohp(lm, PL, frame)
        elif exercise == "Bicep Curls":   _run_curls(lm, PL, frame)
        elif exercise == "Jumping Jacks": _run_jacks(lm, PL, frame)
        elif exercise == "Lunges":        _run_lunges(lm, PL, frame)
    except Exception as exc:
        _put_text(frame, f"Processing error: {exc}", (10, 30), (0, 0, 220))

    # Draw posture feedback overlay
    fb_color = _GREEN_BGR if st.session_state.form_ok else _RED_BGR
    _put_text(frame, st.session_state.form_msg, (10, frame.shape[0] - 20), fb_color)

    return frame


def _update_feedback(fb: dict):
    st.session_state.form_msg = fb["message"]
    st.session_state.form_ok  = fb["is_correct"]


# ── Per-exercise counters ──────────────────────────────────────────────────────

def _run_squats(lm, PL, frame):
    lh, lk, la = lm[PL.LEFT_HIP.value], lm[PL.LEFT_KNEE.value], lm[PL.LEFT_ANKLE.value]
    rh, rk, ra = lm[PL.RIGHT_HIP.value], lm[PL.RIGHT_KNEE.value], lm[PL.RIGHT_ANKLE.value]
    if not _vis_ok(lm, PL.LEFT_HIP, PL.LEFT_KNEE, PL.LEFT_ANKLE,
                       PL.RIGHT_HIP, PL.RIGHT_KNEE, PL.RIGHT_ANKLE):
        return

    la_ang = _angle(lh, lk, la)
    ra_ang = _angle(rh, rk, ra)
    avg    = (la_ang + ra_ang) / 2.0
    knee_over_toe = (lk.x > la.x + 0.04) or (rk.x < ra.x - 0.04)

    prev_stage = st.session_state.stage
    stage = prev_stage
    if la_ang < 90 and ra_ang < 90:    stage = "up"
    elif la_ang > 170 and ra_ang > 170: stage = "down"

    if prev_stage == "up" and stage == "down":
        st.session_state.counter += 1
    st.session_state.stage = stage

    _update_feedback(analyze_squat_form(avg, in_squat=(stage == "up"),
                                         knee_over_toe=knee_over_toe))

    fh, fw = frame.shape[:2]
    _put_text(frame, f"L:{int(la_ang)}",
              (int(lk.x * fw) + 15, int(lk.y * fh)), _GREEN_BGR)
    _put_text(frame, f"R:{int(ra_ang)}",
              (int(rk.x * fw) + 15, int(rk.y * fh)), _GREEN_BGR)


def _run_ohp(lm, PL, frame):
    ls, le, lw, lh = (lm[PL.LEFT_SHOULDER.value], lm[PL.LEFT_ELBOW.value],
                       lm[PL.LEFT_WRIST.value], lm[PL.LEFT_HIP.value])
    rs, re, rw, rh = (lm[PL.RIGHT_SHOULDER.value], lm[PL.RIGHT_ELBOW.value],
                       lm[PL.RIGHT_WRIST.value], lm[PL.RIGHT_HIP.value])
    if not _vis_ok(lm, PL.LEFT_SHOULDER, PL.LEFT_ELBOW, PL.LEFT_WRIST,
                       PL.RIGHT_SHOULDER, PL.RIGHT_ELBOW, PL.RIGHT_WRIST):
        return

    le_ang = _angle(ls, le, lw);  ls_ang = _angle(lh, ls, le)
    re_ang = _angle(rs, re, rw);  rs_ang = _angle(rh, rs, re)
    l_fa = abs(math.degrees(math.atan2(lw.y - le.y, lw.x - le.x)))
    r_fa = abs(math.degrees(math.atan2(rw.y - re.y, rw.x - re.x)))

    prev_stage = st.session_state.stage
    stage = prev_stage
    if le_ang > 160 and ls_ang > 160 and re_ang > 160 and rs_ang > 160:
        stage = "down"
    elif le_ang < 90 and ls_ang < 90 and re_ang < 90 and rs_ang < 90:
        stage = "up"

    if prev_stage == "up" and stage == "down":
        st.session_state.counter += 1
    st.session_state.stage = stage

    _update_feedback(analyze_ohp_form(l_fa, r_fa))

    fh, fw = frame.shape[:2]
    _put_text(frame, f"{int(le_ang)}", (int(le.x * fw) + 15, int(le.y * fh)), _GREEN_BGR)
    _put_text(frame, f"{int(re_ang)}", (int(re.x * fw) + 15, int(re.y * fh)), _GREEN_BGR)


def _run_curls(lm, PL, frame):
    ls, le, lw = lm[PL.LEFT_SHOULDER.value], lm[PL.LEFT_ELBOW.value], lm[PL.LEFT_WRIST.value]
    rs, re, rw = lm[PL.RIGHT_SHOULDER.value], lm[PL.RIGHT_ELBOW.value], lm[PL.RIGHT_WRIST.value]
    if not _vis_ok(lm, PL.LEFT_SHOULDER, PL.LEFT_ELBOW, PL.LEFT_WRIST,
                       PL.RIGHT_SHOULDER, PL.RIGHT_ELBOW, PL.RIGHT_WRIST):
        return

    la = _angle(ls, le, lw);  ra = _angle(rs, re, rw)
    avg = (la + ra) / 2.0

    prev_stage = st.session_state.stage
    stage = prev_stage
    if la > 170 and ra > 170: stage = "up"
    elif la < 30 and ra < 30:  stage = "down"

    if prev_stage == "down" and stage == "up":
        st.session_state.counter += 1
    st.session_state.stage = stage

    _update_feedback(analyze_curl_form(avg, stage))

    fh, fw = frame.shape[:2]
    _put_text(frame, f"{int(la)}", (int(le.x * fw) + 15, int(le.y * fh)), _GREEN_BGR)
    _put_text(frame, f"{int(ra)}", (int(re.x * fw) + 15, int(re.y * fh)), _GREEN_BGR)


def _run_jacks(lm, PL, frame):
    ls, rs = lm[PL.LEFT_SHOULDER.value], lm[PL.RIGHT_SHOULDER.value]
    le, re = lm[PL.LEFT_ELBOW.value],   lm[PL.RIGHT_ELBOW.value]
    lh, rh = lm[PL.LEFT_HIP.value],    lm[PL.RIGHT_HIP.value]
    la, ra = lm[PL.LEFT_ANKLE.value],  lm[PL.RIGHT_ANKLE.value]
    if not _vis_ok(lm, PL.LEFT_SHOULDER, PL.RIGHT_SHOULDER,
                       PL.LEFT_ELBOW, PL.RIGHT_ELBOW,
                       PL.LEFT_ANKLE, PL.RIGHT_ANKLE):
        return

    l_arm = _angle(lh, ls, le);  r_arm = _angle(rh, rs, re)
    feet_wide  = la.x > ls.x and ra.x < rs.x
    feet_close = la.x < ls.x and ra.x > rs.x

    prev_stage = st.session_state.stage
    stage = prev_stage
    if l_arm > 150 and r_arm > 150 and feet_wide:  stage = "down"
    elif l_arm < 30  and r_arm < 30  and feet_close: stage = "up"

    if prev_stage == "down" and stage == "up":
        st.session_state.counter += 1
    st.session_state.stage = stage

    _update_feedback(analyze_jumping_jack_form(l_arm, r_arm, feet_wide, stage))


def _run_lunges(lm, PL, frame):
    lh, lk, la = lm[PL.LEFT_HIP.value], lm[PL.LEFT_KNEE.value], lm[PL.LEFT_ANKLE.value]
    rh, rk, ra = lm[PL.RIGHT_HIP.value], lm[PL.RIGHT_KNEE.value], lm[PL.RIGHT_ANKLE.value]
    if not _vis_ok(lm, PL.LEFT_HIP, PL.LEFT_KNEE, PL.LEFT_ANKLE,
                       PL.RIGHT_HIP, PL.RIGHT_KNEE, PL.RIGHT_ANKLE):
        return

    l_ang = _angle(lh, lk, la);  r_ang = _angle(rh, rk, ra)
    min_ang = min(l_ang, r_ang);  max_ang = max(l_ang, r_ang)
    is_asym  = (max_ang - min_ang) > 30
    in_lunge = min_ang < 110 and is_asym

    prev_stage = st.session_state.stage
    stage = prev_stage
    if in_lunge:                         stage = "lunge"
    elif l_ang > 160 and r_ang > 160:    stage = "stand"

    if prev_stage == "lunge" and stage == "stand":
        st.session_state.counter += 1
    st.session_state.stage = stage

    _update_feedback(analyze_lunge_form(min_ang, is_asym, in_lunge=(stage == "lunge")))

    fh, fw = frame.shape[:2]
    _put_text(frame, f"L:{int(l_ang)}", (int(lk.x * fw) + 15, int(lk.y * fh)), _GREEN_BGR)
    _put_text(frame, f"R:{int(r_ang)}", (int(rk.x * fw) + 15, int(rk.y * fh)), _GREEN_BGR)


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://img.icons8.com/?size=80&id=67466&format=png", width=60)
    st.title("Virtual Personal Trainer")
    st.markdown("---")

    st.markdown('<p class="section-title">Select Exercise</p>', unsafe_allow_html=True)
    selected_exercise = st.selectbox(
        label="Exercise",
        options=_EXERCISES,
        index=_EXERCISES.index(st.session_state.exercise),
        label_visibility="collapsed",
    )
    if selected_exercise != st.session_state.exercise:
        st.session_state.exercise = selected_exercise
        st.session_state.counter  = 0
        st.session_state.stage    = None
        st.session_state.form_msg = "Exercise changed — ready!"
        st.session_state.form_ok  = True

    st.markdown("---")
    st.markdown('<p class="section-title">Session Controls</p>', unsafe_allow_html=True)

    col_s, col_t = st.columns(2)
    start_clicked = col_s.button("▶ Start", use_container_width=True, type="primary")
    stop_clicked  = col_t.button("⏹ Stop",  use_container_width=True)

    if start_clicked and not st.session_state.running:
        cap = cv2.VideoCapture(0)
        if not cap.isOpened():
            st.error("❌ Webcam not detected. Please connect a camera and try again.")
        else:
            st.session_state.cap        = cap
            st.session_state.mp_pose   = mp.solutions.pose
            st.session_state.mp_draw   = mp.solutions.drawing_utils
            st.session_state.pose      = mp.solutions.pose.Pose(
                static_image_mode=False, model_complexity=1,
                enable_segmentation=False,
                min_detection_confidence=_MIN_VIS,
                min_tracking_confidence=_MIN_VIS,
            )
            st.session_state.counter   = 0
            st.session_state.stage     = None
            st.session_state.start_time= time.time()
            st.session_state.running   = True
            st.session_state.form_msg  = "Workout started!"
            st.session_state.form_ok   = True

    if stop_clicked and st.session_state.running:
        # Save JSON session log
        if st.session_state.start_time:
            try:
                sl = SessionLogger()
                sl.log_session(
                    exercise=st.session_state.exercise,
                    reps=st.session_state.counter,
                    start_time=st.session_state.start_time,
                    end_time=time.time(),
                )
                st.sidebar.success("✅ Session saved to workout_logs/session_data.json")
            except Exception as e:
                st.sidebar.warning(f"Could not save session: {e}")
        if st.session_state.cap:
            st.session_state.cap.release()
        if st.session_state.pose:
            st.session_state.pose.close()
        st.session_state.running = False
        st.session_state.cap     = None
        st.session_state.pose    = None

    st.markdown("---")
    st.caption("Powered by MediaPipe BlazePose · OpenCV · Streamlit")


# ── Main layout ────────────────────────────────────────────────────────────────

st.markdown("# 💪 Virtual Personal Trainer")
st.markdown("*Real-time AI-powered exercise tracking and posture correction*")
st.markdown("---")

left_col, right_col = st.columns([2, 1], gap="large")

# ── Left: Camera feed ──────────────────────────────────────────────────────────
with left_col:
    st.markdown('<p class="section-title">📷 Live Camera Feed</p>', unsafe_allow_html=True)
    frame_placeholder = st.empty()

    if not st.session_state.running:
        frame_placeholder.info("Camera is off. Press **▶ Start** in the sidebar to begin.")

# ── Right: Stats panel ─────────────────────────────────────────────────────────
with right_col:
    st.markdown('<p class="section-title">📊 Live Workout Stats</p>', unsafe_allow_html=True)

    exercise_placeholder = st.empty()
    reps_placeholder     = st.empty()
    form_placeholder     = st.empty()

    st.markdown("---")
    st.markdown('<p class="section-title">⏱️ Session Info</p>', unsafe_allow_html=True)

    time_placeholder  = st.empty()
    total_placeholder = st.empty()


def _render_stats():
    """Refresh the right-column stats widgets."""
    exercise_placeholder.metric("Exercise", st.session_state.exercise)
    reps_placeholder.metric("Reps Completed", st.session_state.counter)

    fb_class   = "feedback-good" if st.session_state.form_ok else "feedback-bad"
    fb_icon    = "✅" if st.session_state.form_ok else "⚠️"
    form_placeholder.markdown(
        f'<div class="{fb_class}">{fb_icon} {st.session_state.form_msg}</div>',
        unsafe_allow_html=True,
    )

    if st.session_state.start_time:
        elapsed = int(time.time() - st.session_state.start_time)
        mins, secs = divmod(elapsed, 60)
        time_placeholder.metric("Workout Time", f"{mins:02d}:{secs:02d}")
    else:
        time_placeholder.metric("Workout Time", "00:00")

    total_placeholder.metric("Total Reps", st.session_state.counter)


_render_stats()


# ── Live frame loop ────────────────────────────────────────────────────────────
if st.session_state.running:
    cap = st.session_state.cap
    if cap is None or not cap.isOpened():
        st.error("❌ Camera disconnected. Please restart the workout.")
        st.session_state.running = False
    else:
        ret, frame = cap.read()
        if not ret:
            st.warning("⚠️ Could not read camera frame. Check your webcam.")
        else:
            frame = cv2.flip(frame, 1)
            try:
                frame = _process_frame(frame, st.session_state.exercise)
            except Exception as exc:
                _put_text(frame, f"Error: {exc}", (10, 30), (0, 0, 220))

            # Display the annotated frame
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_placeholder.image(frame_rgb, channels="RGB", use_column_width=True)

        # Refresh stats and trigger next frame via rerun
        _render_stats()
        time.sleep(0.03)      # ~30 fps cap
        st.rerun()

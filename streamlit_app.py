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

import os
import sys
import tempfile
import math
import time
import datetime
import threading
import base64

import cv2
import numpy as np
import mediapipe as mp
import streamlit as st

try:
    from streamlit_webrtc import (
        webrtc_streamer,
        VideoProcessorBase,
        RTCConfiguration,
        WebRtcMode,
    )
    import av
    HAS_WEBRTC = True
except Exception:
    HAS_WEBRTC = False

try:
    import mediapipe.python.solutions.pose as mp_pose
    import mediapipe.python.solutions.drawing_utils as mp_draw
except Exception:
    try:
        mp_pose = mp.solutions.pose
        mp_draw = mp.solutions.drawing_utils
    except Exception:
        mp_pose = None
        mp_draw = None

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

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

# ── Camera Probe Helper ────────────────────────────────────────────────────────

def check_camera_devices(force_refresh=False):
    """Probe camera devices and return available camera indexes and resolutions."""
    if not force_refresh and "camera_list" in st.session_state and st.session_state.camera_list is not None:
        return st.session_state.camera_list

    if st.session_state.get("running", False):
        return st.session_state.get("camera_list", [])

    available = []
    for idx in range(2):
        cap = None
        try:
            if sys.platform == "win32":
                cap = cv2.VideoCapture(idx, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(idx)
            else:
                cap = cv2.VideoCapture(idx)

            if cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    h, w = frame.shape[:2]
                    available.append({"index": idx, "res": f"{w}x{h}"})
        except Exception:
            pass
        finally:
            if cap is not None:
                try:
                    cap.release()
                except Exception:
                    pass

    st.session_state["camera_list"] = available
    return available


# ── Session-state initialisation ───────────────────────────────────────────────
_INPUT_OPTIONS = [
    "🎬 Sample Workout Video",
    "📁 Upload Workout Video",
    "📸 Live Web Camera (Browser)",
    "💻 Local PC Camera (OpenCV)",
]
_IS_CLOUD = os.path.exists("/mount/src") or "STREAMLIT_SHARING_HOST" in os.environ
_INITIAL_CAMS = check_camera_devices()
_DEFAULT_INPUT = "🎬 Sample Workout Video" if _IS_CLOUD else ("💻 Local PC Camera (OpenCV)" if _INITIAL_CAMS else "🎬 Sample Workout Video")

_DEFAULTS = {
    "running":        False,
    "cap":            None,
    "pose":           None,
    "mp_pose":        None,
    "mp_draw":        None,
    "counter":        0,
    "stage":          None,
    "form_msg":       "Press ▶ Start to begin workout tracking",
    "form_ok":        True,
    "start_time":     None,
    "exercise":       "Squats",
    "input_mode":     _DEFAULT_INPUT,
    "selected_cam":   0,
    "video_path":     os.path.join(BASE_DIR, "demo", "How-to-do-SnapYT.App.mp4"),
    "is_video_file":  False,
    "camera_list":    _INITIAL_CAMS,
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

# ── Per-exercise evaluator ─────────────────────────────────────────────────────

def evaluate_exercise_step(exercise: str, lm, PL, stage, counter: int, frame):
    """
    Evaluate one frame of pose landmarks for the selected exercise.
    Returns: (new_stage, new_counter, feedback_dict)
    """
    fb = {"is_correct": True, "message": "Posture ready"}
    fh, fw = frame.shape[:2]

    if exercise == "Squats":
        lh, lk, la = lm[PL.LEFT_HIP.value], lm[PL.LEFT_KNEE.value], lm[PL.LEFT_ANKLE.value]
        rh, rk, ra = lm[PL.RIGHT_HIP.value], lm[PL.RIGHT_KNEE.value], lm[PL.RIGHT_ANKLE.value]
        if not _vis_ok(lm, PL.LEFT_HIP, PL.LEFT_KNEE, PL.LEFT_ANKLE,
                           PL.RIGHT_HIP, PL.RIGHT_KNEE, PL.RIGHT_ANKLE):
            return stage, counter, fb

        la_ang = _angle(lh, lk, la)
        ra_ang = _angle(rh, rk, ra)
        avg    = (la_ang + ra_ang) / 2.0
        knee_over_toe = (lk.x > la.x + 0.04) or (rk.x < ra.x - 0.04)

        prev_stage = stage
        if la_ang < 90 and ra_ang < 90:      stage = "up"
        elif la_ang > 170 and ra_ang > 170:  stage = "down"

        if prev_stage == "up" and stage == "down":
            counter += 1

        fb = analyze_squat_form(avg, in_squat=(stage == "up"), knee_over_toe=knee_over_toe)
        _put_text(frame, f"L:{int(la_ang)}", (int(lk.x * fw) + 15, int(lk.y * fh)), _GREEN_BGR)
        _put_text(frame, f"R:{int(ra_ang)}", (int(rk.x * fw) + 15, int(rk.y * fh)), _GREEN_BGR)

    elif exercise == "Overhead Press":
        ls, le, lw, lh = (lm[PL.LEFT_SHOULDER.value], lm[PL.LEFT_ELBOW.value],
                           lm[PL.LEFT_WRIST.value], lm[PL.LEFT_HIP.value])
        rs, re, rw, rh = (lm[PL.RIGHT_SHOULDER.value], lm[PL.RIGHT_ELBOW.value],
                           lm[PL.RIGHT_WRIST.value], lm[PL.RIGHT_HIP.value])
        if not _vis_ok(lm, PL.LEFT_SHOULDER, PL.LEFT_ELBOW, PL.LEFT_WRIST,
                           PL.RIGHT_SHOULDER, PL.RIGHT_ELBOW, PL.RIGHT_WRIST):
            return stage, counter, fb

        le_ang = _angle(ls, le, lw);  ls_ang = _angle(lh, ls, le)
        re_ang = _angle(rs, re, rw);  rs_ang = _angle(rh, rs, re)
        l_fa = abs(math.degrees(math.atan2(lw.y - le.y, lw.x - le.x)))
        r_fa = abs(math.degrees(math.atan2(rw.y - re.y, rw.x - re.x)))

        prev_stage = stage
        if le_ang > 160 and ls_ang > 160 and re_ang > 160 and rs_ang > 160:
            stage = "down"
        elif le_ang < 90 and ls_ang < 90 and re_ang < 90 and rs_ang < 90:
            stage = "up"

        if prev_stage == "up" and stage == "down":
            counter += 1

        fb = analyze_ohp_form(l_fa, r_fa)
        _put_text(frame, f"{int(le_ang)}", (int(le.x * fw) + 15, int(le.y * fh)), _GREEN_BGR)
        _put_text(frame, f"{int(re_ang)}", (int(re.x * fw) + 15, int(re.y * fh)), _GREEN_BGR)

    elif exercise == "Bicep Curls":
        ls, le, lw = lm[PL.LEFT_SHOULDER.value], lm[PL.LEFT_ELBOW.value], lm[PL.LEFT_WRIST.value]
        rs, re, rw = lm[PL.RIGHT_SHOULDER.value], lm[PL.RIGHT_ELBOW.value], lm[PL.RIGHT_WRIST.value]
        if not _vis_ok(lm, PL.LEFT_SHOULDER, PL.LEFT_ELBOW, PL.LEFT_WRIST,
                           PL.RIGHT_SHOULDER, PL.RIGHT_ELBOW, PL.RIGHT_WRIST):
            return stage, counter, fb

        la = _angle(ls, le, lw);  ra = _angle(rs, re, rw)
        avg = (la + ra) / 2.0

        prev_stage = stage
        if la > 170 and ra > 170: stage = "up"
        elif la < 30 and ra < 30:  stage = "down"

        if prev_stage == "down" and stage == "up":
            counter += 1

        fb = analyze_curl_form(avg, stage)
        _put_text(frame, f"{int(la)}", (int(le.x * fw) + 15, int(le.y * fh)), _GREEN_BGR)
        _put_text(frame, f"{int(ra)}", (int(re.x * fw) + 15, int(re.y * fh)), _GREEN_BGR)

    elif exercise == "Jumping Jacks":
        ls, rs = lm[PL.LEFT_SHOULDER.value], lm[PL.RIGHT_SHOULDER.value]
        le, re = lm[PL.LEFT_ELBOW.value],   lm[PL.RIGHT_ELBOW.value]
        lh, rh = lm[PL.LEFT_HIP.value],    lm[PL.RIGHT_HIP.value]
        la, ra = lm[PL.LEFT_ANKLE.value],  lm[PL.RIGHT_ANKLE.value]
        if not _vis_ok(lm, PL.LEFT_SHOULDER, PL.RIGHT_SHOULDER,
                           PL.LEFT_ELBOW, PL.RIGHT_ELBOW,
                           PL.LEFT_ANKLE, PL.RIGHT_ANKLE):
            return stage, counter, fb

        l_arm = _angle(lh, ls, le);  r_arm = _angle(rh, rs, re)
        feet_wide  = la.x > ls.x and ra.x < rs.x
        feet_close = la.x < ls.x and ra.x > rs.x

        prev_stage = stage
        if l_arm > 150 and r_arm > 150 and feet_wide:    stage = "down"
        elif l_arm < 30  and r_arm < 30  and feet_close:  stage = "up"

        if prev_stage == "down" and stage == "up":
            counter += 1

        fb = analyze_jumping_jack_form(l_arm, r_arm, feet_wide, stage)

    elif exercise == "Lunges":
        lh, lk, la = lm[PL.LEFT_HIP.value], lm[PL.LEFT_KNEE.value], lm[PL.LEFT_ANKLE.value]
        rh, rk, ra = lm[PL.RIGHT_HIP.value], lm[PL.RIGHT_KNEE.value], lm[PL.RIGHT_ANKLE.value]
        if not _vis_ok(lm, PL.LEFT_HIP, PL.LEFT_KNEE, PL.LEFT_ANKLE,
                           PL.RIGHT_HIP, PL.RIGHT_KNEE, PL.RIGHT_ANKLE):
            return stage, counter, fb

        l_ang = _angle(lh, lk, la);  r_ang = _angle(rh, rk, ra)
        min_ang = min(l_ang, r_ang);  max_ang = max(l_ang, r_ang)
        is_asym  = (max_ang - min_ang) > 30
        in_lunge = min_ang < 110 and is_asym

        prev_stage = stage
        if in_lunge:                         stage = "lunge"
        elif l_ang > 160 and r_ang > 160:    stage = "stand"

        if prev_stage == "lunge" and stage == "stand":
            counter += 1

        fb = analyze_lunge_form(min_ang, is_asym, in_lunge=(stage == "lunge"))
        _put_text(frame, f"L:{int(l_ang)}", (int(lk.x * fw) + 15, int(lk.y * fh)), _GREEN_BGR)
        _put_text(frame, f"R:{int(r_ang)}", (int(rk.x * fw) + 15, int(rk.y * fh)), _GREEN_BGR)

    return stage, counter, fb


def _update_feedback(fb: dict):
    st.session_state.form_msg = fb["message"]
    st.session_state.form_ok  = fb["is_correct"]


def _process_frame(frame, exercise: str):
    """Run MediaPipe Pose on one frame and update session state counters."""
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
        new_stage, new_counter, fb = evaluate_exercise_step(
            exercise, lm, PL,
            st.session_state.stage,
            st.session_state.counter,
            frame
        )
        st.session_state.stage = new_stage
        st.session_state.counter = new_counter
        _update_feedback(fb)
    except Exception as exc:
        _put_text(frame, f"Processing error: {exc}", (10, 30), (0, 0, 220))

    fb_color = _GREEN_BGR if st.session_state.form_ok else _RED_BGR
    _put_text(frame, st.session_state.form_msg, (10, frame.shape[0] - 20), fb_color)
    return frame


if HAS_WEBRTC:
    class WorkoutVideoProcessor(VideoProcessorBase):
        """WebRTC continuous video frame processor running in background thread."""
        def __init__(self):
            self.lock = threading.Lock()
            self.exercise = "Squats"
            self.counter = 0
            self.stage = None
            self.form_msg = "Get into starting position"
            self.form_ok = True
            self.start_time = time.time()
            if mp_pose is not None:
                self.pose = mp_pose.Pose(
                    static_image_mode=False,
                    model_complexity=0,
                    enable_segmentation=False,
                    min_detection_confidence=_MIN_VIS,
                    min_tracking_confidence=_MIN_VIS,
                )
            else:
                self.pose = None

        def update_exercise(self, new_exercise: str):
            with self.lock:
                if self.exercise != new_exercise:
                    self.exercise = new_exercise
                    self.counter = 0
                    self.stage = None
                    self.form_msg = f"Changed to {new_exercise} — ready!"
                    self.form_ok = True

        def reset(self):
            with self.lock:
                self.counter = 0
                self.stage = None
                self.form_msg = "Workout stats reset — ready!"
                self.form_ok = True
                self.start_time = time.time()

        def recv(self, frame: av.VideoFrame) -> av.VideoFrame:
            img = frame.to_ndarray(format="bgr24")
            # Natural mirror flip
            img = cv2.flip(img, 1)

            # Downscale frame if larger than 640px to ensure smooth 30 FPS inference
            fh, fw = img.shape[:2]
            if fw > 640:
                scale = 640.0 / fw
                img = cv2.resize(img, (640, int(fh * scale)))

            if self.pose is None or mp_pose is None or mp_draw is None:
                _put_text(img, "MediaPipe not available", (30, 80), (0, 0, 255))
                return av.VideoFrame.from_ndarray(img, format="bgr24")

            with self.lock:
                cur_exercise = self.exercise
                cur_stage = self.stage
                cur_counter = self.counter

            frame_rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            results = self.pose.process(frame_rgb)

            if not results or not results.pose_landmarks:
                _put_text(img, "No pose detected", (30, 80), (0, 165, 255))
            else:
                mp_draw.draw_landmarks(img, results.pose_landmarks, mp_pose.POSE_CONNECTIONS)
                lm = results.pose_landmarks.landmark
                PL = mp_pose.PoseLandmark

                try:
                    new_stage, new_counter, fb = evaluate_exercise_step(
                        cur_exercise, lm, PL, cur_stage, cur_counter, img
                    )
                    with self.lock:
                        self.stage = new_stage
                        self.counter = new_counter
                        self.form_msg = fb["message"]
                        self.form_ok = fb["is_correct"]
                except Exception as exc:
                    _put_text(img, f"Processing error: {exc}", (10, 80), (0, 0, 220))

            with self.lock:
                display_reps = self.counter
                display_msg = self.form_msg
                is_ok = self.form_ok

            fh, fw = img.shape[:2]
            # HUD Top Bar: Exercise & Rep Count
            cv2.rectangle(img, (0, 0), (fw, 55), (15, 20, 25), -1)
            cv2.line(img, (0, 55), (fw, 55), (88, 166, 255), 2)
            cv2.putText(img, f"{cur_exercise.upper()} | REPS: {display_reps}", (20, 38), _FONT, 1.0, (255, 255, 255), 2, cv2.LINE_AA)

            # HUD Bottom Bar: Posture Guidance
            bg_color = (15, 60, 25) if is_ok else (25, 25, 80)
            line_color = _GREEN_BGR if is_ok else _RED_BGR
            cv2.rectangle(img, (0, fh - 50), (fw, fh), bg_color, -1)
            cv2.line(img, (0, fh - 50), (fw, fh - 50), line_color, 2)
            _put_text(img, display_msg, (20, fh - 18), line_color)

            return av.VideoFrame.from_ndarray(img, format="bgr24")
else:
    WorkoutVideoProcessor = None

if HAS_WEBRTC:
    _ice_servers = [
        {"urls": ["stun:stun.l.google.com:19302"]},
        {"urls": ["stun:openrelay.metered.ca:80"]},
        {
            "urls": [
                "turn:openrelay.metered.ca:80",
                "turn:openrelay.metered.ca:443",
                "turn:openrelay.metered.ca:443?transport=tcp",
            ],
            "username": "openrelayproject",
            "credential": "openrelayproject",
        },
    ]
    try:
        if "TURN_URL" in st.secrets:
            _ice_servers.append({
                "urls": [st.secrets["TURN_URL"]],
                "username": st.secrets.get("TURN_USERNAME", ""),
                "credential": st.secrets.get("TURN_CREDENTIAL", ""),
            })
    except Exception:
        pass

    RTC_CONFIGURATION = RTCConfiguration({"iceServers": _ice_servers})
else:
    RTC_CONFIGURATION = None


# ── Sidebar ────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.image("https://img.icons8.com/?size=80&id=67466&format=png", width=60)
    st.title("Virtual Personal Trainer")
    st.markdown("---")

    # 1. Exercise selection
    st.markdown('<p class="section-title">1. Select Exercise</p>', unsafe_allow_html=True)
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

    # 2. Input Source & Verification
    st.markdown('<p class="section-title">2. Video Input Source</p>', unsafe_allow_html=True)
    input_mode = st.radio(
        "Choose Input Source",
        options=_INPUT_OPTIONS,
        index=_INPUT_OPTIONS.index(st.session_state.get("input_mode", _DEFAULT_INPUT)) if st.session_state.get("input_mode", _DEFAULT_INPUT) in _INPUT_OPTIONS else 0,
        label_visibility="collapsed",
    )
    st.session_state.input_mode = input_mode

    # Camera Verification & Status Card
    cams = check_camera_devices()

    col_stat, col_btn = st.columns([4, 1])
    with col_stat:
        if cams:
            cam_info = ", ".join([f"Device #{c['index']} ({c['res']})" for c in cams])
            st.markdown(
                f"""
                <div style="background: rgba(46, 160, 67, 0.15); border: 1px solid #2ea043; border-radius: 8px; padding: 10px; margin-top: 6px; margin-bottom: 8px;">
                    <div style="color: #3fb950; font-weight: 700; font-size: 0.92rem;">🟢 Local Camera Detected</div>
                    <div style="color: #8b949e; font-size: 0.78rem; margin-top: 3px;">{cam_info}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            env_label = "Streamlit Cloud Container" if _IS_CLOUD else "Local Host"
            st.markdown(
                f"""
                <div style="background: rgba(88, 166, 255, 0.12); border: 1px solid #388bfd; border-radius: 8px; padding: 10px; margin-top: 6px; margin-bottom: 8px;">
                    <div style="color: #58a6ff; font-weight: 700; font-size: 0.92rem;">🌐 Browser Web Camera Ready</div>
                    <div style="color: #8b949e; font-size: 0.78rem; margin-top: 3px;">Live webcam ready via browser ({env_label}).</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    with col_btn:
        st.write("")
        if st.button("🔄", help="Re-scan connected cameras"):
            st.session_state.camera_list = None
            check_camera_devices(force_refresh=True)
            st.rerun()

    with st.expander("🔍 Camera Verification & Setup Help", expanded=False):
        if cams:
            st.success(f"Hardware camera ready! Detected {len(cams)} device(s):")
            for c in cams:
                st.write(f"- **Camera #{c['index']}**: Resolution {c['res']}")
        else:
            if _IS_CLOUD:
                st.info(
                    "🌐 **How Camera Works in Cloud vs Local:**\n\n"
                    "1. **Live in Browser (Cloud):** Select **'📸 Live Web Camera (Browser)'** to open your webcam directly inside the webpage.\n\n"
                    "2. **Pre-recorded Video:** Select **'🎬 Sample Workout Video'** or **'📁 Upload Workout Video'** to test exercise counting.\n\n"
                    "3. **Continuous OpenCV Stream:** Run locally on your laptop: `streamlit run streamlit_app.py`"
                )
            else:
                st.warning(
                    "⚠️ **No camera detected on this PC:**\n"
                    "- Ensure your USB camera is plugged in.\n"
                    "- Verify another app (Zoom, Teams, Camera app) is not occupying it.\n"
                    "- Click the 🔄 button above to re-scan."
                )

    if input_mode == "💻 Local PC Camera (OpenCV)":
        if cams:
            cam_indices = [c["index"] for c in cams]
            selected_cam = st.selectbox(
                "Select Camera",
                options=cam_indices,
                format_func=lambda i: f"Camera #{i} ({next(c['res'] for c in cams if c['index'] == i)})",
            )
            st.session_state.selected_cam = selected_cam
        else:
            if _IS_CLOUD:
                st.warning("⚠️ Local OpenCV camera requires running locally. In Cloud, use '📸 Live Web Camera (Browser)' or '🎬 Sample Workout Video' above.")
            else:
                st.warning("⚠️ No camera detected. Plug in a webcam and click 🔄 above.")

    elif input_mode == "🎬 Sample Workout Video":
        sample_dict = {
            "Squats Demo Video": os.path.join(BASE_DIR, "demo", "How-to-do-SnapYT.App.mp4"),
            "Squats Demo Video #2": os.path.join(BASE_DIR, "demo", "How-to-do-SnapYT.App (1).mp4"),
            "Pull-up Demo Video": os.path.join(BASE_DIR, "demo", "Pullup-Exercise-SnapYT.App.mp4"),
        }
        chosen_sample_name = st.selectbox("Select Sample Video", options=list(sample_dict.keys()))
        st.session_state.video_path = sample_dict[chosen_sample_name]
        st.caption(f"📁 Source: `{os.path.basename(st.session_state.video_path)}`")

    elif input_mode == "📁 Upload Workout Video":
        st.info("📂 Upload your video in the center panel to begin analysis.")
        if st.session_state.get("video_path") and os.path.exists(st.session_state.video_path):
            st.caption(f"📁 Video ready: `{os.path.basename(st.session_state.video_path)}`")

    elif input_mode == "📸 Live Web Camera (Browser)":
        st.caption("📸 Your web camera opens directly in the center panel below.")

    st.markdown("---")
    st.markdown('<p class="section-title">3. Session Controls</p>', unsafe_allow_html=True)

    def _start_video_session(video_path: str):
        if not video_path or not os.path.exists(video_path):
            st.error("❌ Please select or upload a valid video file first.")
            return False
        if mp_pose is None or mp_draw is None:
            st.error("❌ MediaPipe Pose is not available.")
            return False
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            st.error(f"❌ Could not open video file: {os.path.basename(video_path)}")
            return False

        st.session_state.cap = cap
        st.session_state.is_video_file = True
        st.session_state.mp_pose = mp_pose
        st.session_state.mp_draw = mp_draw
        st.session_state.pose = mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            enable_segmentation=False,
            min_detection_confidence=_MIN_VIS,
            min_tracking_confidence=_MIN_VIS,
        )
        st.session_state.counter = 0
        st.session_state.stage = None
        st.session_state.start_time = time.time()
        st.session_state.running = True
        st.session_state.form_msg = "Video analysis running!"
        st.session_state.form_ok = True
        return True

    def _start_cam_session(cam_idx: int = 0):
        if mp_pose is None or mp_draw is None:
            st.error("❌ MediaPipe Pose is not available.")
            return False
        if sys.platform == "win32":
            cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(cam_idx)
        else:
            cap = cv2.VideoCapture(cam_idx)
        if not cap.isOpened():
            st.error(f"❌ Camera #{cam_idx} could not be opened.")
            return False

        st.session_state.cap = cap
        st.session_state.is_video_file = False
        st.session_state.mp_pose = mp_pose
        st.session_state.mp_draw = mp_draw
        st.session_state.pose = mp_pose.Pose(
            static_image_mode=False,
            model_complexity=1,
            enable_segmentation=False,
            min_detection_confidence=_MIN_VIS,
            min_tracking_confidence=_MIN_VIS,
        )
        st.session_state.counter = 0
        st.session_state.stage = None
        st.session_state.start_time = time.time()
        st.session_state.running = True
        st.session_state.form_msg = "Webcam tracking running!"
        st.session_state.form_ok = True
        return True

    def _stop_current_session():
        if st.session_state.get("start_time"):
            try:
                sl = SessionLogger()
                sl.log_session(
                    exercise=st.session_state.exercise,
                    reps=st.session_state.counter,
                    start_time=st.session_state.start_time,
                    end_time=time.time(),
                )
                st.sidebar.success("✅ Workout session saved to logs!")
            except Exception:
                pass
        if st.session_state.get("cap"):
            try:
                st.session_state.cap.release()
            except Exception:
                pass
        if st.session_state.get("pose"):
            try:
                st.session_state.pose.close()
            except Exception:
                pass
        st.session_state.running = False
        st.session_state.cap = None
        st.session_state.pose = None

    if input_mode == "📸 Live Web Camera (Browser)":
        if st.button("⏹ Reset Workout Stats", use_container_width=True):
            st.session_state.counter = 0
            st.session_state.stage = None
            st.session_state.form_msg = "Stats reset — ready!"
            st.session_state.form_ok = True
            st.rerun()
    else:
        col_s, col_t = st.columns(2)
        if col_s.button("▶ Start", use_container_width=True, type="primary", disabled=st.session_state.running):
            if input_mode == "💻 Local PC Camera (OpenCV)":
                _start_cam_session(st.session_state.get("selected_cam", 0))
            elif input_mode in ("🎬 Sample Workout Video", "📁 Upload Workout Video"):
                _start_video_session(st.session_state.get("video_path"))
            st.rerun()

        if col_t.button("⏹ Stop", use_container_width=True, disabled=not st.session_state.running):
            _stop_current_session()
            st.rerun()

    st.markdown("---")
    st.caption("Powered by MediaPipe BlazePose · OpenCV · Streamlit")


# ── Main layout ────────────────────────────────────────────────────────────────

st.markdown("# 💪 Virtual Personal Trainer")
st.markdown("*Real-time AI-powered exercise tracking and posture correction*")
st.markdown("---")

left_col, right_col = st.columns([2, 1], gap="large")

# ── Left: Camera / Video feed ──────────────────────────────────────────────────
with left_col:
    st.markdown('<p class="section-title">📷 Workout Feed</p>', unsafe_allow_html=True)

    if input_mode == "🎬 Sample Workout Video":
        sample_dict = {
            "Squats Demo Video": os.path.join(BASE_DIR, "demo", "How-to-do-SnapYT.App.mp4"),
            "Squats Demo Video #2": os.path.join(BASE_DIR, "demo", "How-to-do-SnapYT.App (1).mp4"),
            "Pull-up Demo Video": os.path.join(BASE_DIR, "demo", "Pullup-Exercise-SnapYT.App.mp4"),
        }
        chosen_sample = st.selectbox("Choose Sample Video", options=list(sample_dict.keys()), key="main_sample_sel")
        st.session_state.video_path = sample_dict[chosen_sample]

        if not st.session_state.running:
            col_v1, col_v2 = st.columns(2)
            if col_v1.button("▶ Play Sample Video", type="primary", use_container_width=True):
                _start_video_session(sample_dict[chosen_sample])
                st.rerun()
            if col_v2.button("⏹ Stop Video", use_container_width=True, disabled=True):
                pass
        else:
            if st.button("⏹ Stop Workout Video", type="secondary", use_container_width=True):
                _stop_current_session()
                st.rerun()

    elif input_mode == "📁 Upload Workout Video":
        uploaded_file = st.file_uploader(
            "📂 Upload an exercise video (.mp4, .mov, .avi)",
            type=["mp4", "mov", "avi"],
            key="center_file_uploader",
        )
        if uploaded_file is not None:
            if st.session_state.get("_last_uploaded_name") != uploaded_file.name:
                tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                tfile.write(uploaded_file.read())
                tfile.flush()
                st.session_state.video_path = tfile.name
                st.session_state._last_uploaded_name = uploaded_file.name
                st.success(f"✅ Video ready: **{uploaded_file.name}**")
            else:
                st.caption(f"📁 Active video: `{uploaded_file.name}`")

        has_file = bool(st.session_state.get("video_path") and os.path.exists(st.session_state.video_path))
        if not has_file:
            st.info("👆 Please select and upload an exercise video file above to begin AI analysis.")
        elif not st.session_state.running:
            col_v1, col_v2 = st.columns(2)
            if col_v1.button("▶ Start Video Analysis", type="primary", use_container_width=True):
                _start_video_session(st.session_state.video_path)
                st.rerun()
            if col_v2.button("⏹ Stop Video", use_container_width=True, disabled=True):
                pass
        else:
            if st.button("⏹ Stop Video Analysis", type="secondary", use_container_width=True):
                _stop_current_session()
                st.rerun()

    elif input_mode == "💻 Local PC Camera (OpenCV)":
        if not st.session_state.running:
            col_v1, col_v2 = st.columns(2)
            if col_v1.button("▶ Start Webcam", type="primary", use_container_width=True):
                _start_cam_session(st.session_state.get("selected_cam", 0))
                st.rerun()
            if col_v2.button("⏹ Stop Webcam", use_container_width=True, disabled=True):
                pass
        else:
            if st.button("⏹ Stop Webcam", type="secondary", use_container_width=True):
                _stop_current_session()
                st.rerun()

    elif input_mode == "📸 Live Web Camera (Browser)":
        cam_view_mode = st.radio(
            "Browser Camera Mode",
            options=["🎥 Continuous Live WebRTC Stream", "📸 Instant Photo Snapshot"],
            horizontal=True,
            label_visibility="collapsed",
        )
        if cam_view_mode == "🎥 Continuous Live WebRTC Stream":
            if not HAS_WEBRTC:
                st.error("❌ WebRTC streamer is unavailable in this environment.")
            else:
                st.markdown(
                    """
                    <div style="background: rgba(46, 160, 67, 0.12); border: 1px solid #2ea043; border-radius: 8px; padding: 10px 14px; margin-bottom: 10px;">
                        <div style="color: #3fb950; font-weight: 700; font-size: 0.95rem;">🎥 Continuous Live WebRTC Stream</div>
                        <div style="color: #c9d1d9; font-size: 0.82rem; margin-top: 3px;">
                            Click <b>START</b> on the camera feed below to stream your webcam continuously with real-time pose tracking HUD.
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
                webrtc_ctx = webrtc_streamer(
                    key="live-workout-streamer",
                    mode=WebRtcMode.SENDRECV,
                    rtc_configuration=RTC_CONFIGURATION,
                    video_processor_factory=WorkoutVideoProcessor,
                    media_stream_constraints={
                        "video": True,
                        "audio": False,
                    },
                    async_processing=True,
                )
                if webrtc_ctx and webrtc_ctx.video_processor:
                    webrtc_ctx.video_processor.update_exercise(st.session_state.exercise)
                    with webrtc_ctx.video_processor.lock:
                        st.session_state.counter = webrtc_ctx.video_processor.counter
                        st.session_state.form_msg = webrtc_ctx.video_processor.form_msg
                        st.session_state.form_ok = webrtc_ctx.video_processor.form_ok
                        if st.session_state.start_time is None and webrtc_ctx.state.playing:
                            st.session_state.start_time = webrtc_ctx.video_processor.start_time

                st.caption("💡 *If your browser asks for camera permission, click **Allow**. If connection takes long on your network, switch to **Instant Photo Snapshot** above.*")
        else:
            st.markdown(
                """
                <div style="background: rgba(88, 166, 255, 0.12); border: 1px solid #388bfd; border-radius: 8px; padding: 10px 14px; margin-bottom: 10px;">
                    <div style="color: #58a6ff; font-weight: 700; font-size: 0.95rem;">📸 Instant Camera Snapshot</div>
                    <div style="color: #c9d1d9; font-size: 0.82rem; margin-top: 3px;">
                        Capture posture photos directly with your webcam for instant AI form analysis.
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            camera_photo = st.camera_input("Live Web Camera", label_visibility="collapsed")
            if camera_photo is not None:
                bytes_data = camera_photo.getvalue()
                cv2_img = cv2.imdecode(np.frombuffer(bytes_data, np.uint8), cv2.IMREAD_COLOR)
                if cv2_img is not None:
                    if st.session_state.pose is None:
                        if mp_pose is not None and mp_draw is not None:
                            st.session_state.mp_pose = mp_pose
                            st.session_state.mp_draw = mp_draw
                            st.session_state.pose = mp_pose.Pose(
                                static_image_mode=True, model_complexity=1,
                                enable_segmentation=False,
                                min_detection_confidence=_MIN_VIS,
                            )
                    annotated = _process_frame(cv2_img, st.session_state.exercise)
                    st.image(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB), caption="Analyzed Pose & Form Feedback", use_container_width=True)

    # ── Render active video stream fragment ──
    @st.fragment(run_every=0.04)
    def _render_video_feed():
        if not st.session_state.get("running", False):
            return

        cap = st.session_state.get("cap")
        if cap is None or not cap.isOpened():
            st.session_state.running = False
            return

        ret, frame = cap.read()
        if not ret:
            if st.session_state.get("is_video_file", False):
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
                if not ret:
                    st.session_state.running = False
                    return
            else:
                st.session_state.running = False
                return

        if not st.session_state.get("is_video_file", False):
            frame = cv2.flip(frame, 1)

        try:
            frame = _process_frame(frame, st.session_state.exercise)
        except Exception as exc:
            _put_text(frame, f"Error: {exc}", (10, 30), (0, 0, 220))

        # Encode frame to JPEG and render as base64 data URI to prevent Streamlit MediaFile 404s
        ret_enc, buf = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if ret_enc:
            b64_frame = base64.b64encode(buf).decode('utf-8')
            st.markdown(
                f'<div style="width:100%; text-align:center;"><img src="data:image/jpeg;base64,{b64_frame}" style="width:100%; border-radius:8px; border:1px solid #30363d;" /></div>',
                unsafe_allow_html=True,
            )
        else:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            st.image(frame_rgb, use_container_width=True)

    if input_mode != "📸 Live Web Camera (Browser)":
        if st.session_state.running:
            _render_video_feed()
        else:
            st.info("👆 Click **▶ Start** above to begin workout analysis!")


# ── Right: Stats panel ─────────────────────────────────────────────────────────
with right_col:
    @st.fragment(run_every=0.5)
    def _render_live_stats():
        st.markdown('<p class="section-title">📊 Live Workout Stats</p>', unsafe_allow_html=True)
        st.metric("Exercise", st.session_state.exercise)
        st.metric("Reps Completed", st.session_state.counter)

        fb_class = "feedback-good" if st.session_state.form_ok else "feedback-bad"
        fb_icon  = "✅" if st.session_state.form_ok else "⚠️"
        st.markdown(
            f'<div class="{fb_class}">{fb_icon} {st.session_state.form_msg}</div>',
            unsafe_allow_html=True,
        )

        st.markdown("---")
        st.markdown('<p class="section-title">⏱️ Session Info</p>', unsafe_allow_html=True)
        if st.session_state.start_time:
            elapsed = int(time.time() - st.session_state.start_time)
            mins, secs = divmod(elapsed, 60)
            st.metric("Workout Time", f"{mins:02d}:{secs:02d}")
        else:
            st.metric("Workout Time", "00:00")

        st.metric("Total Reps", st.session_state.counter)

    _render_live_stats()

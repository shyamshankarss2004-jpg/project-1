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

import cv2
import numpy as np
import mediapipe as mp
import streamlit as st

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
_IS_CLOUD = os.path.exists("/mount/src") or "STREAMLIT_SHARING_HOST" in os.environ
_INITIAL_CAMS = check_camera_devices()
_DEFAULT_INPUT = "Live Webcam" if _INITIAL_CAMS else "Sample Video"

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
        options=["Live Webcam", "Sample Video", "Upload Video", "Camera Snapshot"],
        index=["Live Webcam", "Sample Video", "Upload Video", "Camera Snapshot"].index(st.session_state.get("input_mode", _DEFAULT_INPUT)),
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
                    <div style="color: #3fb950; font-weight: 700; font-size: 0.92rem;">🟢 Camera Connected</div>
                    <div style="color: #8b949e; font-size: 0.78rem; margin-top: 3px;">{cam_info}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
        else:
            env_label = "Streamlit Cloud Container" if _IS_CLOUD else "Local Host"
            st.markdown(
                f"""
                <div style="background: rgba(248, 81, 73, 0.15); border: 1px solid #f85149; border-radius: 8px; padding: 10px; margin-top: 6px; margin-bottom: 8px;">
                    <div style="color: #f85149; font-weight: 700; font-size: 0.92rem;">🔴 Camera Not Connected</div>
                    <div style="color: #8b949e; font-size: 0.78rem; margin-top: 3px;">No hardware camera found on {env_label}.</div>
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
                    "🌐 **Why does it show 'Camera Not Connected' in Cloud?**\n\n"
                    "Streamlit Cloud runs inside a remote Linux container in a data center without physical USB webcam hardware.\n\n"
                    "👉 **To test right now on Streamlit Cloud:**\n"
                    "- Switch to **'🎬 Sample Video'** or **'📁 Upload Video'** above to see live skeleton tracking and rep counting.\n"
                    "- Or switch to **'📸 Camera Snapshot'** to test single-frame analysis with your browser webcam.\n\n"
                    "👉 **To use continuous live webcam:**\n"
                    "- Run the project on your laptop terminal:\n"
                    "```bash\nstreamlit run streamlit_app.py\n```\n"
                    "- Your local webcam will be automatically detected (🟢 Connected) and streamed live!"
                )
            else:
                st.warning(
                    "⚠️ **No camera detected on this PC:**\n"
                    "- Ensure your USB camera is plugged in.\n"
                    "- Verify another app (Zoom, Teams, Camera app) is not occupying it.\n"
                    "- Click the 🔄 button above to re-scan."
                )

    if input_mode == "Live Webcam":
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
                st.warning("⚠️ Live Webcam via OpenCV requires running locally. In Cloud, switch to '🎬 Sample Video' or '📁 Upload Video' above.")
            else:
                st.warning("⚠️ No camera detected. Plug in a webcam and click 🔄 above.")

    elif input_mode == "Sample Video":
        sample_dict = {
            "Squats Demo Video": os.path.join(BASE_DIR, "demo", "How-to-do-SnapYT.App.mp4"),
            "Squats Demo Video #2": os.path.join(BASE_DIR, "demo", "How-to-do-SnapYT.App (1).mp4"),
            "Pull-up Demo Video": os.path.join(BASE_DIR, "demo", "Pullup-Exercise-SnapYT.App.mp4"),
        }
        chosen_sample_name = st.selectbox("Select Sample Video", options=list(sample_dict.keys()))
        st.session_state.video_path = sample_dict[chosen_sample_name]
        st.caption(f"📁 Source: `{os.path.basename(st.session_state.video_path)}`")

    elif input_mode == "Upload Video":
        uploaded_file = st.file_uploader("Upload workout video (.mp4, .mov, .avi)", type=["mp4", "mov", "avi"])
        if uploaded_file is not None:
            tfile = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
            tfile.write(uploaded_file.read())
            tfile.flush()
            st.session_state.video_path = tfile.name
            st.success("✅ Video file ready for workout!")

    elif input_mode == "Camera Snapshot":
        st.caption("📸 Capture frames directly through your browser webcam below.")

    st.markdown("---")
    st.markdown('<p class="section-title">3. Session Controls</p>', unsafe_allow_html=True)

    col_s, col_t = st.columns(2)
    start_clicked = col_s.button("▶ Start", use_container_width=True, type="primary")
    stop_clicked  = col_t.button("⏹ Stop",  use_container_width=True)

    if start_clicked and not st.session_state.running:
        cap = None
        is_vid = False

        if input_mode == "Live Webcam":
            cam_idx = st.session_state.get("selected_cam", 0)
            if sys.platform == "win32":
                cap = cv2.VideoCapture(cam_idx, cv2.CAP_DSHOW)
                if not cap.isOpened():
                    cap = cv2.VideoCapture(cam_idx)
            else:
                cap = cv2.VideoCapture(cam_idx)

            if not cap.isOpened():
                if _IS_CLOUD:
                    st.error("❌ Camera not detected on cloud host. Please switch to '🎬 Sample Video' or '📁 Upload Video' above to run the AI tracker on Streamlit Cloud.")
                else:
                    st.error(f"❌ Camera #{cam_idx} could not be opened. Please verify it is connected and not in use by another app.")
                cap = None
        elif input_mode in ("Sample Video", "Upload Video"):
            vid_path = st.session_state.get("video_path")
            if not vid_path or not os.path.exists(vid_path):
                st.error("❌ Please choose or upload a valid video file first.")
            else:
                cap = cv2.VideoCapture(vid_path)
                if not cap.isOpened():
                    st.error(f"❌ Could not open video file: {os.path.basename(vid_path)}")
                    cap = None
                else:
                    is_vid = True

        if cap is not None and cap.isOpened():
            st.session_state.cap           = cap
            st.session_state.is_video_file = is_vid
            st.session_state.mp_pose      = mp.solutions.pose
            st.session_state.mp_draw      = mp.solutions.drawing_utils
            st.session_state.pose         = mp.solutions.pose.Pose(
                static_image_mode=False, model_complexity=1,
                enable_segmentation=False,
                min_detection_confidence=_MIN_VIS,
                min_tracking_confidence=_MIN_VIS,
            )
            st.session_state.counter      = 0
            st.session_state.stage        = None
            st.session_state.start_time   = time.time()
            st.session_state.running      = True
            st.session_state.form_msg     = "Workout tracking active!"
            st.session_state.form_ok      = True

    if stop_clicked and st.session_state.running:
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

# ── Left: Camera / Video feed ──────────────────────────────────────────────────
with left_col:
    st.markdown('<p class="section-title">📷 Workout Feed</p>', unsafe_allow_html=True)
    frame_placeholder = st.empty()

    if input_mode == "Camera Snapshot":
        camera_photo = st.camera_input("Take a snapshot with your browser camera to evaluate form")
        if camera_photo is not None:
            bytes_data = camera_photo.getvalue()
            cv2_img = cv2.imdecode(np.frombuffer(bytes_data, np.uint8), cv2.IMREAD_COLOR)
            if cv2_img is not None:
                if st.session_state.pose is None:
                    st.session_state.mp_pose = mp.solutions.pose
                    st.session_state.mp_draw = mp.solutions.drawing_utils
                    st.session_state.pose = mp.solutions.pose.Pose(
                        static_image_mode=True, model_complexity=1,
                        enable_segmentation=False,
                        min_detection_confidence=_MIN_VIS,
                    )
                annotated = _process_frame(cv2_img, st.session_state.exercise)
                st.image(cv2.cvtColor(annotated, cv2.COLOR_BGR2RGB), caption="Analyzed Pose", use_column_width=True)
    elif not st.session_state.running:
        if input_mode == "Live Webcam":
            frame_placeholder.info("Webcam feed is inactive. Verify camera connection in sidebar and press **▶ Start**.")
        elif input_mode in ("Sample Video", "Upload Video"):
            frame_placeholder.info(f"Ready to play **{input_mode}**. Press **▶ Start** in the sidebar to begin AI analysis.")

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
if st.session_state.running and input_mode != "Camera Snapshot":
    cap = st.session_state.cap
    if cap is None or not cap.isOpened():
        st.error("❌ Video source disconnected. Please restart the workout.")
        st.session_state.running = False
    else:
        ret, frame = cap.read()
        if not ret:
            if st.session_state.get("is_video_file", False):
                # Loop video seamlessly from the beginning
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ret, frame = cap.read()
            else:
                st.warning("⚠️ Could not read camera frame. Check your webcam connection.")
        if ret and frame is not None:
            if not st.session_state.get("is_video_file", False):
                frame = cv2.flip(frame, 1)
            try:
                frame = _process_frame(frame, st.session_state.exercise)
            except Exception as exc:
                _put_text(frame, f"Error: {exc}", (10, 30), (0, 0, 220))

            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            frame_placeholder.image(frame_rgb, channels="RGB", use_column_width=True)

        _render_stats()
        time.sleep(0.03)      # ~30 fps cap
        st.rerun()

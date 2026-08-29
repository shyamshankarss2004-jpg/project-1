"""
windows/main_pages/demo_mode_page.py
--------------------------------------
Demo Mode – Upload Video for Exercise Analysis.

Supported exercises: Squats | Push-up | Pull-up | Jumping Jacks | Bicep Curls

Rep counting:
  - Uses BEST-VISIBLE ARM for push-up / pull-up (solves side-view angle issues)
  - EMA smoothing (α = 0.45) per angle channel
  - 2-frame stage confirmation (keeps up with fast video)
  - 10-frame debounce (prevents double-count)
  - 4-frame feedback stabiliser (no flickering)
  - Audio rep count using existing audio/reps/rep_N.wav files

Camera angle guide (also shown in sidebar):
  Squats       → Side / diagonal view
  Push-up      → Side view (either side works)
  Pull-up      → Front view (arms overhead)
  Jumping Jacks→ Front view (full body)
  Bicep Curls  → Front or slight side
"""

import math
import os
import time

import cv2
import numpy as np
import mediapipe as mp

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QFileDialog, QMessageBox, QSizePolicy, QFrame,
    QProgressBar,
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent
from PyQt5.QtCore import QTimer, Qt, QUrl
from PyQt5.QtGui import QPixmap, QImage, QFont

from modules.posture_analyzer import (
    analyze_squat_form,
    analyze_curl_form,
    analyze_jumping_jack_form,
)
from utils.session_logger import SessionLogger
from utils.resource_helper import resource_path
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────
_EXERCISES    = ["Squats", "Push-up", "Pull-up", "Jumping Jacks", "Bicep Curls"]
_MIN_VIS      = 0.35          # lower = works with more partial views
_TIMER_MS     = 40            # ~25 fps
_ALPHA        = 0.45          # EMA smoothing factor
_STAGE_CONF   = 2             # frames needed to confirm a stage change
_DEBOUNCE     = 10            # frames locked after each rep
_FB_LOCK      = 4             # frames of same feedback before UI updates
_MAX_SOUNDS   = 20
_GREEN        = (0, 220, 0)
_RED          = (0, 0, 220)
_YELLOW       = (30, 200, 220)
_FONT         = cv2.FONT_HERSHEY_SIMPLEX


# ── EMA helper ─────────────────────────────────────────────────────────────────
class _EMA:
    """Exponential moving average for a single float value."""
    def __init__(self, alpha: float = _ALPHA):
        self._a, self._v = alpha, None

    def update(self, x: float) -> float:
        self._v = x if self._v is None else self._a * x + (1 - self._a) * self._v
        return self._v

    def reset(self):
        self._v = None


# ── Geometry helpers ───────────────────────────────────────────────────────────
def _angle(a, b, c) -> float:
    """Angle at joint b from three MediaPipe landmarks (degrees)."""
    ba = np.array([a.x - b.x, a.y - b.y])
    bc = np.array([c.x - b.x, c.y - b.y])
    cos = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8)
    return float(np.degrees(np.arccos(np.clip(cos, -1.0, 1.0))))


def _vis(lm, *ids, thr=_MIN_VIS) -> bool:
    return all(lm[i.value].visibility > thr for i in ids)


def _put(frame, text, pos, color=_GREEN, scale=0.65, thick=2):
    cv2.putText(frame, text, pos, _FONT, scale, color, thick, cv2.LINE_AA)


# ── DemoModePage ───────────────────────────────────────────────────────────────
class DemoModePage(QWidget):
    """
    Demo Mode page: upload an MP4, process frame-by-frame with MediaPipe,
    count reps, play audio feedback, display live stats.
    Integrated into the existing PyQt5 main window stack.
    """

    def __init__(self, main_window, parent=None):
        super().__init__(parent)
        self.main_window = main_window

        # ── Playback ───────────────────────────────────────────────────────────
        self._cap          = None
        self._pose         = None
        self._mp_pose      = None
        self._mp_draw      = None
        self._timer        = QTimer(self)
        self._timer.timeout.connect(self._next_frame)
        self._video_path   = None
        self._total_frames = 1
        self._running      = False
        self._start_time   = None

        # ── Rep / stage state machine ──────────────────────────────────────────
        self._counter      = 0
        self._stage        = None      # committed stage
        self._stage_cand   = None      # candidate (unconfirmed)
        self._stage_frames = 0
        self._prev_stage   = None      # previous committed stage
        self._deb          = 0         # debounce countdown

        # ── Angle smoothers ────────────────────────────────────────────────────
        self._ema: dict[str, _EMA] = {}

        # ── Feedback stabiliser ────────────────────────────────────────────────
        self._fb_msg      = "Select exercise and upload a video."
        self._fb_ok       = True
        self._cand_msg    = self._fb_msg
        self._cand_ok     = True
        self._fb_cnt      = 0

        # ── Audio ──────────────────────────────────────────────────────────────
        self._sounds: dict[int, QMediaPlayer] = {}
        self._init_audio()

        self._session_logger = SessionLogger()
        self._build_ui()

    # ── Audio setup ────────────────────────────────────────────────────────────
    def _init_audio(self):
        """Pre-load rep audio clips (rep_1.wav … rep_20.wav)."""
        try:
            vol = 70
            for i in range(1, _MAX_SOUNDS + 1):
                path = resource_path(f"audio/reps/rep_{i}.wav")
                if os.path.exists(path):
                    p = QMediaPlayer()
                    p.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
                    p.setVolume(vol)
                    self._sounds[i] = p
        except Exception as e:
            logger.warning("Audio init failed: %s", e)

    def _play_rep(self, n: int):
        """Play the rep count audio immediately (no delay)."""
        try:
            idx = min(n, _MAX_SOUNDS)
            if idx in self._sounds:
                self._sounds[idx].stop()
                self._sounds[idx].play()
        except Exception as e:
            logger.warning("Audio play failed: %s", e)

    # ──────────────────────────────────────────────────────────────────────────
    # UI construction
    # ──────────────────────────────────────────────────────────────────────────
    def _build_ui(self):
        self.setStyleSheet("""
            QWidget  { background:#0d1117; color:#e6edf3; font-family:'Segoe UI'; }
            QLabel   { color:#e6edf3; }
            QPushButton {
                background:#238636; color:#fff; border:none; border-radius:6px;
                padding:8px 16px; font-weight:bold; font-size:13px;
            }
            QPushButton:hover   { background:#2ea043; }
            QPushButton:pressed { background:#1a7f37; }
            QPushButton#stopBtn { background:#da3633; }
            QPushButton#stopBtn:hover { background:#f85149; }
            QPushButton#browseBtn { background:#1f6feb; }
            QPushButton#browseBtn:hover { background:#388bfd; }
            QComboBox {
                background:#161b22; border:1px solid #30363d;
                border-radius:6px; padding:6px 10px; color:#e6edf3; font-size:13px;
            }
            QComboBox::drop-down { border:none; width:22px; }
            QComboBox QAbstractItemView { background:#161b22; color:#e6edf3; }
            QFrame#card { background:#161b22; border:1px solid #30363d; border-radius:10px; }
            QProgressBar { background:#21262d; border-radius:4px; height:8px; }
            QProgressBar::chunk { background:#238636; border-radius:4px; }
        """)

        root = QHBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(14)

        # ── Controls panel ────────────────────────────────────────────────────
        ctrl = QFrame(); ctrl.setObjectName("card"); ctrl.setFixedWidth(268)
        cl = QVBoxLayout(ctrl); cl.setContentsMargins(14, 18, 14, 18); cl.setSpacing(12)

        t = QLabel("🎬 Demo Mode")
        t.setFont(QFont("Segoe UI", 15, QFont.Bold))
        t.setStyleSheet("color:#58a6ff;")
        cl.addWidget(t); cl.addWidget(self._sep())

        cl.addWidget(self._tag("Exercise"))
        self._ex_box = QComboBox()
        self._ex_box.addItems(_EXERCISES)
        self._ex_box.currentTextChanged.connect(self._reset_state)
        self._ex_box.currentTextChanged.connect(self._update_hint)
        cl.addWidget(self._ex_box)

        self._hint_lbl = QLabel()
        self._hint_lbl.setWordWrap(True)
        self._hint_lbl.setStyleSheet("color:#8b949e; font-size:11px;")
        cl.addWidget(self._hint_lbl)
        self._update_hint()

        cl.addWidget(self._sep())
        cl.addWidget(self._tag("Upload Video (MP4)"))
        self._file_lbl = QLabel("No file selected")
        self._file_lbl.setWordWrap(True)
        self._file_lbl.setStyleSheet("color:#8b949e; font-size:11px;")
        cl.addWidget(self._file_lbl)

        br = QPushButton("📁 Browse…"); br.setObjectName("browseBtn")
        br.clicked.connect(self._browse)
        cl.addWidget(br)

        cl.addWidget(self._sep())
        cl.addWidget(self._tag("Progress"))
        self._prog = QProgressBar(); self._prog.setRange(0, 100)
        cl.addWidget(self._prog)

        cl.addWidget(self._sep())
        cl.addWidget(self._tag("Controls"))
        br2 = QHBoxLayout()
        self._start_btn = QPushButton("▶  Start")
        self._stop_btn  = QPushButton("⏹  Stop"); self._stop_btn.setObjectName("stopBtn")
        self._stop_btn.setEnabled(False)
        self._start_btn.clicked.connect(self._start)
        self._stop_btn.clicked.connect(self._stop)
        br2.addWidget(self._start_btn); br2.addWidget(self._stop_btn)
        cl.addLayout(br2)
        cl.addStretch()

        cred = QLabel("Powered by MediaPipe · OpenCV · PyQt5")
        cred.setStyleSheet("color:#484f58; font-size:10px;")
        cred.setAlignment(Qt.AlignCenter)
        cl.addWidget(cred)
        root.addWidget(ctrl)

        # ── Video panel ───────────────────────────────────────────────────────
        vf = QFrame(); vf.setObjectName("card")
        vl = QVBoxLayout(vf); vl.setContentsMargins(8, 8, 8, 8); vl.setSpacing(4)
        fh2 = QLabel("📹 Processed Video Feed")
        fh2.setStyleSheet("color:#58a6ff; font-size:11px; letter-spacing:2px;")
        vl.addWidget(fh2)

        self._vid_lbl = QLabel("Load a video and press ▶ Start")
        self._vid_lbl.setAlignment(Qt.AlignCenter)
        self._vid_lbl.setMinimumSize(480, 360)
        self._vid_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._vid_lbl.setStyleSheet("background:#000; border-radius:8px; color:#484f58;")
        self._vid_lbl.setFont(QFont("Segoe UI", 11))
        vl.addWidget(self._vid_lbl)
        root.addWidget(vf, stretch=3)

        # ── Stats panel ───────────────────────────────────────────────────────
        sf = QFrame(); sf.setObjectName("card"); sf.setFixedWidth(210)
        sl = QVBoxLayout(sf); sl.setContentsMargins(12, 16, 12, 16); sl.setSpacing(10)

        st = QLabel("📊 Live Stats")
        st.setFont(QFont("Segoe UI", 13, QFont.Bold))
        st.setStyleSheet("color:#58a6ff;")
        sl.addWidget(st); sl.addWidget(self._sep())

        sl.addWidget(self._tag("Exercise"))
        self._s_ex = QLabel("—"); self._s_ex.setFont(QFont("Segoe UI", 12, QFont.Bold))
        sl.addWidget(self._s_ex); sl.addWidget(self._sep())

        sl.addWidget(self._tag("Reps"))
        self._s_reps = QLabel("0")
        self._s_reps.setFont(QFont("Segoe UI", 38, QFont.Bold))
        self._s_reps.setStyleSheet("color:#3fb950;")
        self._s_reps.setAlignment(Qt.AlignCenter)
        sl.addWidget(self._s_reps); sl.addWidget(self._sep())

        sl.addWidget(self._tag("Time"))
        self._s_time = QLabel("00:00")
        self._s_time.setFont(QFont("Segoe UI", 20, QFont.Bold))
        self._s_time.setStyleSheet("color:#58a6ff;")
        self._s_time.setAlignment(Qt.AlignCenter)
        sl.addWidget(self._s_time); sl.addWidget(self._sep())

        sl.addWidget(self._tag("Stage"))
        self._s_stage = QLabel("—"); self._s_stage.setFont(QFont("Segoe UI", 11))
        sl.addWidget(self._s_stage); sl.addWidget(self._sep())

        sl.addWidget(self._tag("Feedback"))
        self._s_fb = QLabel("Waiting…")
        self._s_fb.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._s_fb.setWordWrap(True)
        self._s_fb.setStyleSheet("color:#3fb950;")
        sl.addWidget(self._s_fb)

        sl.addStretch()
        root.addWidget(sf)

    # ── Static UI helpers ──────────────────────────────────────────────────────
    @staticmethod
    def _sep():
        f = QFrame(); f.setFrameShape(QFrame.HLine)
        f.setStyleSheet("color:#21262d;"); return f

    @staticmethod
    def _tag(text: str) -> QLabel:
        l = QLabel(text.upper())
        l.setStyleSheet("color:#8b949e; font-size:10px; letter-spacing:1.5px;")
        return l

    def _update_hint(self, *_):
        hints = {
            "Squats":       "📐 Side/diagonal — hip, knee & ankle visible",
            "Push-up":      "📐 Either side view — shoulder, elbow, wrist level",
            "Pull-up":      "📐 Front view — both arms visible overhead",
            "Jumping Jacks":"📐 Front view — full body & ankles visible",
            "Bicep Curls":  "📐 Front or slight side — elbows & wrists clear",
        }
        self._hint_lbl.setText(hints.get(self._ex_box.currentText(), ""))

    # ──────────────────────────────────────────────────────────────────────────
    # Controls
    # ──────────────────────────────────────────────────────────────────────────
    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video", "",
            "Video Files (*.mp4 *.avi *.mov *.mkv);;All Files (*)")
        if path:
            self._video_path = path
            self._file_lbl.setText("…" + path[-35:] if len(path) > 38 else path)
            self._prog.setValue(0)
            self._vid_lbl.setText("File loaded. Press ▶ Start to analyse.")

    def _start(self):
        if not self._video_path:
            QMessageBox.warning(self, "No Video", "Please select a video file first."); return
        try:
            self._cap = cv2.VideoCapture(self._video_path)
            if not self._cap.isOpened():
                raise IOError("Cannot open video file.")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Cannot open video:\n{e}"); return

        self._total_frames = max(1, int(self._cap.get(cv2.CAP_PROP_FRAME_COUNT)))

        try:
            self._mp_pose = mp.solutions.pose
            self._mp_draw = mp.solutions.drawing_utils
            self._pose    = self._mp_pose.Pose(
                static_image_mode=False, model_complexity=1,
                enable_segmentation=False,
                min_detection_confidence=_MIN_VIS,
                min_tracking_confidence=_MIN_VIS,
            )
        except Exception as e:
            QMessageBox.critical(self, "Error", f"MediaPipe failed:\n{e}")
            self._release(); return

        self._reset_state()
        self._start_time = time.time()
        self._running    = True
        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        self._ex_box.setEnabled(False)
        self._s_ex.setText(self._ex_box.currentText())
        self._timer.start(_TIMER_MS)

    def _stop(self):
        self._timer.stop()
        self._running = False
        if self._start_time and self._counter > 0:
            try:
                self._session_logger.log_session(
                    exercise=self._ex_box.currentText(),
                    reps=self._counter,
                    start_time=self._start_time,
                    end_time=time.time(),
                )
            except Exception as e:
                logger.warning("Session save error: %s", e)
        self._release()
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._ex_box.setEnabled(True)
        self._prog.setValue(0)
        self._set_fb("Stopped.", True)

    def _release(self):
        for obj in (self._cap, self._pose):
            if obj is None:
                continue
            try:
                if hasattr(obj, "release"):
                    obj.release()
                elif hasattr(obj, "close"):
                    obj.close()
            except Exception:
                pass
        self._cap  = None
        self._pose = None

    def _reset_state(self, *_):
        """Reset all per-exercise counters and smoothers."""
        self._counter      = 0
        self._stage        = None
        self._stage_cand   = None
        self._stage_frames = 0
        self._prev_stage   = None
        self._deb          = 0
        self._ema.clear()
        self._fb_msg       = "Waiting…"
        self._fb_ok        = True
        self._fb_cnt       = 0
        self._s_reps.setText("0")
        self._s_stage.setText("—")
        self._set_fb("Waiting…", True)

    # ──────────────────────────────────────────────────────────────────────────
    # Frame loop
    # ──────────────────────────────────────────────────────────────────────────
    def _next_frame(self):
        if not self._cap or not self._cap.isOpened() or not self._running:
            return
        try:
            ret, frame = self._cap.read()
        except Exception as e:
            logger.error("Frame read: %s", e); self._stop(); return

        if not ret:
            self._stop()
            QMessageBox.information(
                self, "Analysis Complete",
                f"✅ Done!\nExercise: {self._ex_box.currentText()}\nTotal Reps: {self._counter}"
            )
            return

        frame = cv2.resize(frame, (640, 480))

        pos = int(self._cap.get(cv2.CAP_PROP_POS_FRAMES))
        self._prog.setValue(min(int(pos / self._total_frames * 100), 100))

        try:
            frame = self._analyse(frame)
        except Exception as e:
            logger.error("Analysis: %s", e)
            _put(frame, f"Error: {e}", (10, 30), _RED)

        # Update stats panel
        self._s_reps.setText(str(self._counter))
        if self._start_time:
            e = int(time.time() - self._start_time)
            self._s_time.setText(f"{e//60:02d}:{e%60:02d}")
        if self._stage:
            self._s_stage.setText(self._stage.upper())

        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb.shape
            img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
            self._vid_lbl.setPixmap(
                QPixmap.fromImage(img).scaled(
                    self._vid_lbl.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as e:
            logger.error("Display: %s", e)

    # ──────────────────────────────────────────────────────────────────────────
    # Pose dispatch
    # ──────────────────────────────────────────────────────────────────────────
    def _analyse(self, frame):
        rgb     = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        results = self._pose.process(rgb)

        if not results or not results.pose_landmarks:
            _put(frame, "No pose — check camera angle (see sidebar hint)", (10, 50), _YELLOW)
            return frame

        self._mp_draw.draw_landmarks(
            frame, results.pose_landmarks, self._mp_pose.POSE_CONNECTIONS)

        lm = results.pose_landmarks.landmark
        PL = self._mp_pose.PoseLandmark
        fh, fw = frame.shape[:2]

        {
            "Squats":       self._do_squats,
            "Push-up":      self._do_pushup,
            "Pull-up":      self._do_pullup,
            "Jumping Jacks":self._do_jacks,
            "Bicep Curls":  self._do_curls,
        }.get(self._ex_box.currentText(), lambda *a: None)(lm, PL, frame, fh, fw)

        # Feedback overlay at bottom of frame
        _put(frame, self._fb_msg, (10, fh - 14),
             _GREEN if self._fb_ok else _RED, 0.6)
        return frame

    # ──────────────────────────────────────────────────────────────────────────
    # State machine helpers
    # ──────────────────────────────────────────────────────────────────────────
    def _sm(self, key: str, val: float) -> float:
        """EMA-smooth a named angle channel."""
        if key not in self._ema:
            self._ema[key] = _EMA()
        return self._ema[key].update(val)

    def _confirm(self, new: str) -> str:
        """
        Accept a stage change only after _STAGE_CONF consecutive frames.
        Decrements debounce each frame.
        """
        if self._deb > 0:
            self._deb -= 1

        if new == self._stage_cand:
            self._stage_frames += 1
        else:
            self._stage_cand   = new
            self._stage_frames = 1

        if self._stage_frames >= _STAGE_CONF and new != self._stage:
            self._stage        = new
            self._stage_frames = 0

        return self._stage if self._stage is not None else new

    def _count(self, from_s: str, to_s: str):
        """Count a rep on transition from_s → to_s (with debounce guard)."""
        if (self._prev_stage == from_s and
                self._stage == to_s and
                self._deb == 0):
            self._counter += 1
            self._deb      = _DEBOUNCE
            self._play_rep(self._counter)
            logger.debug("REP #%d  (%s→%s)", self._counter, from_s, to_s)

    def _push_fb(self, msg: str, ok: bool):
        """Stabilised feedback – only update UI after _FB_LOCK stable frames."""
        if msg == self._cand_msg and ok == self._cand_ok:
            self._fb_cnt += 1
        else:
            self._cand_msg = msg
            self._cand_ok  = ok
            self._fb_cnt   = 1
        if self._fb_cnt >= _FB_LOCK:
            self._fb_msg = msg
            self._fb_ok  = ok
            self._set_fb(msg, ok)

    def _set_fb(self, msg: str, ok: bool):
        self._s_fb.setStyleSheet(f"color:{'#3fb950' if ok else '#f85149'}; font-weight:bold;")
        self._s_fb.setText(msg)

    # ──────────────────────────────────────────────────────────────────────────
    # ── SQUATS ────────────────────────────────────────────────────────────────
    #  stand (>155°) → squat (<120°) → stand = 1 rep
    #  View: side / diagonal
    # ──────────────────────────────────────────────────────────────────────────
    def _do_squats(self, lm, PL, frame, fh, fw):
        if not _vis(lm, PL.LEFT_HIP, PL.LEFT_KNEE, PL.LEFT_ANKLE,
                        PL.RIGHT_HIP, PL.RIGHT_KNEE, PL.RIGHT_ANKLE):
            _put(frame, "Squats: side/diagonal view — show knees & hips", (10, 30), _YELLOW)
            return

        lh, lk, la = lm[PL.LEFT_HIP.value], lm[PL.LEFT_KNEE.value], lm[PL.LEFT_ANKLE.value]
        rh, rk, ra = lm[PL.RIGHT_HIP.value], lm[PL.RIGHT_KNEE.value], lm[PL.RIGHT_ANKLE.value]

        la_a = self._sm("sq_l", _angle(lh, lk, la))
        ra_a = self._sm("sq_r", _angle(rh, rk, ra))
        avg  = (la_a + ra_a) / 2.0

        if   la_a > 155 and ra_a > 155: raw = "stand"
        elif la_a < 120 or  ra_a < 120: raw = "squat"   # OR: either knee bent
        else:                            raw = self._stage or "stand"

        prev = self._stage
        self._confirm(raw)
        self._prev_stage = prev
        self._count("squat", "stand")

        kno = (lk.x > la.x + 0.04) or (rk.x < ra.x - 0.04)
        fb  = analyze_squat_form(avg, in_squat=(self._stage == "squat"), knee_over_toe=kno)
        self._push_fb(fb["message"], fb["is_correct"])

        _put(frame, f"L:{int(la_a)}", (int(lk.x*fw)+15, int(lk.y*fh)), _GREEN, 0.55)
        _put(frame, f"R:{int(ra_a)}", (int(rk.x*fw)+15, int(rk.y*fh)), _GREEN, 0.55)
        _put(frame, f"Stage:{self._stage or '?'}  Rep:{self._counter}",
             (10, 28), _YELLOW, 0.6)

    # ──────────────────────────────────────────────────────────────────────────
    # ── PUSH-UP ───────────────────────────────────────────────────────────────
    #  Uses the BEST-VISIBLE arm only (solves side-view + angle asymmetry)
    #  up  (arm >135°) → down (arm <100°) → up = 1 rep
    #  View: SIDE — either left or right side works
    # ──────────────────────────────────────────────────────────────────────────
    def _do_pushup(self, lm, PL, frame, fh, fw):
        ls = lm[PL.LEFT_SHOULDER.value];  le = lm[PL.LEFT_ELBOW.value];  lw = lm[PL.LEFT_WRIST.value]
        rs = lm[PL.RIGHT_SHOULDER.value]; re = lm[PL.RIGHT_ELBOW.value]; rw = lm[PL.RIGHT_WRIST.value]

        l_vis = min(ls.visibility, le.visibility, lw.visibility)
        r_vis = min(rs.visibility, re.visibility, rw.visibility)
        best_vis = max(l_vis, r_vis)

        if best_vis < _MIN_VIS:
            _put(frame, "Push-up: side view  (show shoulder → elbow → wrist)", (10, 30), _YELLOW)
            return

        # Pick the arm with the clearest visibility
        if l_vis >= r_vis:
            arm_angle = self._sm("pu", _angle(ls, le, lw))
            ex, ey    = int(le.x * fw), int(le.y * fh)
            side      = "L"
        else:
            arm_angle = self._sm("pu", _angle(rs, re, rw))
            ex, ey    = int(re.x * fw), int(re.y * fh)
            side      = "R"

        # Lenient thresholds: works across a wide range of camera angles
        #   up   = arm fairly extended  (>130°)
        #   down = arm clearly bent     (<100°)
        if   arm_angle > 130: raw = "up"
        elif arm_angle < 100: raw = "down"
        else:                  raw = self._stage or "up"

        prev = self._stage
        self._confirm(raw)
        self._prev_stage = prev
        self._count("down", "up")   # bottom of push-up → top = 1 rep

        # Posture feedback
        if   self._stage == "down" and arm_angle > 90:
            self._push_fb("Go Lower — bend elbows more!", False)
        elif self._stage == "up"   and arm_angle < 140:
            self._push_fb("Push up fully — lock out arms!", False)
        elif self._stage == "down":
            self._push_fb("Good depth ✓ — now push up!", True)
        else:
            self._push_fb("Good Form ✓", True)

        _put(frame, f"{side}:{int(arm_angle)}", (ex + 15, ey), _GREEN, 0.65)
        _put(frame, f"Stage:{self._stage or '?'}  Rep:{self._counter}",
             (10, 28), _YELLOW, 0.6)
        # Small threshold guide overlay
        _put(frame, "UP>130  DOWN<100", (10, 50), (200, 200, 200), 0.45, 1)

    # ──────────────────────────────────────────────────────────────────────────
    # ── PULL-UP ───────────────────────────────────────────────────────────────
    #  Uses best-visible arm (same logic as push-up)
    #  hang (>145°) → pull (<85°) → hang = 1 rep
    #  View: front — arms overhead
    # ──────────────────────────────────────────────────────────────────────────
    def _do_pullup(self, lm, PL, frame, fh, fw):
        ls = lm[PL.LEFT_SHOULDER.value];  le = lm[PL.LEFT_ELBOW.value];  lw = lm[PL.LEFT_WRIST.value]
        rs = lm[PL.RIGHT_SHOULDER.value]; re = lm[PL.RIGHT_ELBOW.value]; rw = lm[PL.RIGHT_WRIST.value]

        l_vis = min(ls.visibility, le.visibility, lw.visibility)
        r_vis = min(rs.visibility, re.visibility, rw.visibility)

        if max(l_vis, r_vis) < _MIN_VIS:
            _put(frame, "Pull-up: front view — arms fully visible overhead", (10, 30), _YELLOW)
            return

        if l_vis >= r_vis:
            arm_angle = self._sm("pl", _angle(ls, le, lw))
            ex, ey    = int(le.x * fw), int(le.y * fh)
            side      = "L"
        else:
            arm_angle = self._sm("pl", _angle(rs, re, rw))
            ex, ey    = int(re.x * fw), int(re.y * fh)
            side      = "R"

        if   arm_angle > 145: raw = "hang"
        elif arm_angle < 85:  raw = "pull"
        else:                  raw = self._stage or "hang"

        prev = self._stage
        self._confirm(raw)
        self._prev_stage = prev
        self._count("pull", "hang")   # top → bottom = 1 rep completed

        if   self._stage == "pull":  self._push_fb("Great Pull! ✓", True)
        elif self._stage == "hang":  self._push_fb("Pull up — engage lats!", True)
        else:                         self._push_fb("Keep going…",          True)

        _put(frame, f"{side}:{int(arm_angle)}", (ex + 15, ey), _GREEN, 0.65)
        _put(frame, f"Stage:{self._stage or '?'}  Rep:{self._counter}",
             (10, 28), _YELLOW, 0.6)
        _put(frame, "HANG>145  PULL<85", (10, 50), (200, 200, 200), 0.45, 1)

    # ──────────────────────────────────────────────────────────────────────────
    # ── JUMPING JACKS ─────────────────────────────────────────────────────────
    #  closed (arms down + feet close) → open (arms up + feet wide) → closed
    #  View: front (full body)
    # ──────────────────────────────────────────────────────────────────────────
    def _do_jacks(self, lm, PL, frame, fh, fw):
        if not _vis(lm, PL.LEFT_SHOULDER, PL.RIGHT_SHOULDER,
                        PL.LEFT_ELBOW, PL.RIGHT_ELBOW,
                        PL.LEFT_ANKLE, PL.RIGHT_ANKLE):
            _put(frame, "Jumping Jacks: front view — full body visible", (10, 30), _YELLOW)
            return

        ls, rs = lm[PL.LEFT_SHOULDER.value], lm[PL.RIGHT_SHOULDER.value]
        le, re = lm[PL.LEFT_ELBOW.value],    lm[PL.RIGHT_ELBOW.value]
        lh, rh = lm[PL.LEFT_HIP.value],      lm[PL.RIGHT_HIP.value]
        la, ra = lm[PL.LEFT_ANKLE.value],    lm[PL.RIGHT_ANKLE.value]

        l_arm = self._sm("jj_l", _angle(lh, ls, le))
        r_arm = self._sm("jj_r", _angle(rh, rs, re))
        fw_p  = la.x > ls.x and ra.x < rs.x   # feet wider than shoulders
        fc    = la.x < ls.x and ra.x > rs.x   # feet closer than shoulders

        if l_arm > 120 and r_arm > 120 and fw_p: raw = "open"
        elif l_arm < 50 and r_arm < 50 and fc:   raw = "closed"
        else:                                      raw = self._stage or "closed"

        prev = self._stage
        self._confirm(raw)
        self._prev_stage = prev
        self._count("open", "closed")   # open → closed = 1 rep

        fb = analyze_jumping_jack_form(l_arm, r_arm, fw_p, self._stage or raw)
        self._push_fb(fb["message"], fb["is_correct"])

        _put(frame, f"L:{int(l_arm)}", (int(ls.x*fw)+15, int(ls.y*fh)), _GREEN, 0.55)
        _put(frame, f"R:{int(r_arm)}", (int(rs.x*fw)+15, int(rs.y*fh)), _GREEN, 0.55)
        _put(frame, f"Stage:{self._stage or '?'}  Rep:{self._counter}",
             (10, 28), _YELLOW, 0.6)

    # ──────────────────────────────────────────────────────────────────────────
    # ── BICEP CURLS ───────────────────────────────────────────────────────────
    #  down (arms straight >155°) → up (curled <55°) → down = 1 rep
    #  View: front or slight side
    # ──────────────────────────────────────────────────────────────────────────
    def _do_curls(self, lm, PL, frame, fh, fw):
        if not _vis(lm, PL.LEFT_SHOULDER, PL.LEFT_ELBOW, PL.LEFT_WRIST,
                        PL.RIGHT_SHOULDER, PL.RIGHT_ELBOW, PL.RIGHT_WRIST):
            _put(frame, "Bicep Curls: front view — elbows & wrists visible", (10, 30), _YELLOW)
            return

        ls, le, lw = lm[PL.LEFT_SHOULDER.value], lm[PL.LEFT_ELBOW.value], lm[PL.LEFT_WRIST.value]
        rs, re, rw = lm[PL.RIGHT_SHOULDER.value], lm[PL.RIGHT_ELBOW.value], lm[PL.RIGHT_WRIST.value]

        la  = self._sm("cu_l", _angle(ls, le, lw))
        ra  = self._sm("cu_r", _angle(rs, re, rw))
        avg = (la + ra) / 2.0

        if   avg > 155: raw = "down"
        elif avg < 55:  raw = "up"
        else:           raw = self._stage or "down"

        prev = self._stage
        self._confirm(raw)
        self._prev_stage = prev
        self._count("up", "down")   # curled → extended = 1 rep

        fb = analyze_curl_form(avg, self._stage or raw)
        self._push_fb(fb["message"], fb["is_correct"])

        _put(frame, f"L:{int(la)}", (int(le.x*fw)+15, int(le.y*fh)), _GREEN, 0.55)
        _put(frame, f"R:{int(ra)}", (int(re.x*fw)+15, int(re.y*fh)), _GREEN, 0.55)
        _put(frame, f"Stage:{self._stage or '?'}  Rep:{self._counter}",
             (10, 28), _YELLOW, 0.6)

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────────
    def stop_training_if_any(self):
        """Called by main_window before navigating away."""
        if self._running:
            self._stop()

    def closeEvent(self, event):
        self.stop_training_if_any()
        event.accept()

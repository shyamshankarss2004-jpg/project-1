"""
windows/main_pages/main_training/training_start.py
----------------------------------------------------
Core training session widget.

Manages the live camera feed, MediaPipe pose estimation, rep counting
for all supported exercises (Squats, OHP, Bicep Curls, Jumping Jacks,
Lunges), real-time posture feedback, audio cues, and saving the
completed session to both the SQLite history table and a JSON log.
"""

import math
import time
import datetime

import cv2
import numpy as np
import mediapipe as mp
from PIL import Image, ImageDraw, ImageFont

from PyQt5.QtWidgets import QWidget, QSizePolicy, QMessageBox
from PyQt5.QtMultimedia import QCameraInfo, QMediaPlayer, QMediaContent
from PyQt5.uic import loadUi
from PyQt5.QtCore import QTimer, Qt, QUrl
from PyQt5.QtGui import QPixmap, QImage

from data.database_manager import (
    get_setting, get_workout_exercises, set_setting,
    insert_history_record, get_workout_id_by_name,
)
from modules.posture_analyzer import (
    analyze_squat_form, analyze_ohp_form, analyze_curl_form,
    analyze_jumping_jack_form, analyze_lunge_form,
)
from utils.session_logger import SessionLogger
from utils.resource_helper import resource_path
from utils.logger import get_logger

logger = get_logger(__name__)

# ── Module constants ───────────────────────────────────────────────────────────
_CAMERA_TIMER_MS  = 30
_MAX_REP_SOUNDS   = 20
_MIN_VISIBILITY   = 0.5
_BAR_X            = 30
_BAR_W            = 20
_BAR_H            = 200
_GREEN_BGR        = (0, 200, 0)
_RED_BGR          = (0, 0, 220)


class Training(QWidget):
    """
    Live training session widget.

    Reads workout exercises from the database, opens the selected camera,
    runs MediaPipe Pose on each frame, counts reps, displays real-time
    posture feedback, plays audio cues, and saves the session on completion.

    Two training modes:
    - **Auto**: Each exercise runs for a timed duration (reps × seconds_per_rep).
    - **Manual**: The user advances via a button.
    """

    def __init__(self, parent, user: int, workout: str, parent_widget=None):
        super().__init__(parent_widget)
        loadUi(resource_path("ui/pages/training.ui"), self)

        self.user    = user
        self.workout = workout

        # ── User settings ──────────────────────────────────────────────────────
        self.camera_name      = get_setting(user, "camera")
        self.mode             = get_setting(user, "mode")
        self.auto_mode        = self.mode == "auto"
        self.prepare_duration = get_setting(user, "prepare")
        self.seconds_per_rep  = get_setting(user, "rep")

        # ── Workout data ───────────────────────────────────────────────────────
        self.exercises = get_workout_exercises(workout, user)

        # ── State machine ──────────────────────────────────────────────────────
        self.state                    = None
        self.current_exercise_index   = 0
        self.current_exercise_start   = None
        self.current_exercise_duration= None
        self.start_time               = time.time()
        self.counter                  = 0
        self.stage                    = None
        self.completed_auto_reps      = 0

        # ── Posture feedback (NEW) ─────────────────────────────────────────────
        self.posture_message = "Waiting..."
        self.posture_correct = True
        self.session_start   = time.time()         # for JSON session log
        self.session_logger  = SessionLogger()

        # ── Safe Attribute Defaults ───────────────────────────────────────────
        self.cap = None
        self.timer = None
        self.pose = None
        self.mp_pose = None
        self.mp_draw = None
        self.font = None
        self.reps_effects = {}
        self.sound_effects = {}
        self.is_valid = False

        # ── UI wiring ──────────────────────────────────────────────────────────
        self.next_exercise_button.hide()
        self.next_exercise_button.clicked.connect(self._go_to_next_exercise)

        # ── Camera ────────────────────────────────────────────────────────────
        self.cap = self._initialize_camera(self.camera_name)
        if not self.cap or not self.cap.isOpened():
            camera_label = f"'{self.camera_name}'" if self.camera_name else "default webcam"
            QMessageBox.critical(
                self,
                "Camera Error",
                f"Could not open camera ({camera_label}).\n\n"
                "Please make sure a camera is connected and permitted, or use 'Demo Mode' "
                "from the sidebar to analyze recorded videos without a webcam."
            )
            return

        # ── Font ──────────────────────────────────────────────────────────────
        font_path = resource_path("ui/fonts/seguibl.ttf")
        self.font_size = 28
        try:
            self.font = ImageFont.truetype(font_path, self.font_size)
        except IOError:
            logger.warning("Font '%s' not found. Using default.", font_path)
            self.font = ImageFont.load_default()

        # ── MediaPipe Pose ────────────────────────────────────────────────────
        try:
            self.mp_pose = mp.solutions.pose
            self.pose = self.mp_pose.Pose(
                static_image_mode=False, model_complexity=1,
                enable_segmentation=False,
                min_detection_confidence=_MIN_VISIBILITY,
                min_tracking_confidence=_MIN_VISIBILITY,
            )
            self.mp_draw = mp.solutions.drawing_utils
        except Exception as e:
            logger.error("Failed to initialize MediaPipe Pose: %s", e)
            QMessageBox.critical(self, "Error", f"Failed to initialize pose detection: {e}")
            return

        # ── Audio ─────────────────────────────────────────────────────────────
        self._init_sounds()

        # ── Frame timer ───────────────────────────────────────────────────────
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._update_camera)
        self.timer.start(_CAMERA_TIMER_MS)
        self.is_valid = True

    # ── Camera initialisation ──────────────────────────────────────────────────

    def _initialize_camera(self, camera_name: str):
        """Resolve camera device name to an OpenCV VideoCapture index."""
        available = QCameraInfo.availableCameras()
        index = next((i for i, c in enumerate(available)
                      if c.deviceName() == camera_name), -1)
        if index == -1:
            if available:
                index = 0
                set_setting(self.user, "camera", available[0].deviceName())
                logger.warning("Saved camera not found. Falling back to index 0.")
            else:
                logger.warning("No cameras detected by QCameraInfo. Attempting fallback to index 0.")
                index = 0
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            cap = cv2.VideoCapture(index)
        if not cap.isOpened():
            logger.error("No camera could be opened at index %s.", index)
            return None
        return cap

    # ── Audio initialisation ───────────────────────────────────────────────────

    def _init_sounds(self):
        """Pre-load all WAV effects into QMediaPlayer instances."""
        volume = get_setting(self.user, "volume")

        def _load(path: str) -> QMediaPlayer:
            p = QMediaPlayer()
            p.setMedia(QMediaContent(QUrl.fromLocalFile(resource_path(path))))
            p.setVolume(volume)
            return p

        self.reps_effects   = {i: _load(f"audio/reps/rep_{i}.wav")
                                for i in range(1, _MAX_REP_SOUNDS + 1)}
        self.prepare_sound  = _load("audio/communications/prepare.wav")
        self.exercise_sound = _load("audio/communications/exercise.wav")
        self.finish_sound   = _load("audio/communications/finish.wav")
        self.wrong_ohp_sound= _load("audio/communications/ohp_wrong_1.wav")

    # ── Main loop ──────────────────────────────────────────────────────────────

    def _update_camera(self):
        """Capture one frame, run the state machine, render overlay, display."""
        if not self.cap or not self.cap.isOpened():
            return
        ret, frame = self.cap.read()
        if not ret:
            return

        frame = cv2.flip(frame, 1)
        now   = time.time()

        if   self.state is None:       self._start_prepare()
        elif self.state == "prepare":  self._handle_prepare(frame, now)
        elif self.state == "exercise": self._handle_exercise(frame, now)
        elif self.state == "finished":
            self._draw_text(frame, "Training Complete!", (30, 50), (255, 255, 0))
            self._save_session()
            self.stop_all()

        # ── Posture feedback overlay (NEW) ─────────────────────────────────────
        fb_color = _GREEN_BGR if self.posture_correct else _RED_BGR
        self._draw_text(frame, self.posture_message, (30, 90), fb_color)

        # ── Display frame ──────────────────────────────────────────────────────
        rgb  = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qt_img = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qt_img)
        self.camera_label.setPixmap(
            pix.scaled(self.camera_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.camera_label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)

    # ── State handlers ─────────────────────────────────────────────────────────

    def _handle_prepare(self, frame, now: float):
        elapsed   = now - self.start_time
        remaining = int(self.prepare_duration) - int(elapsed)
        if remaining <= 0:
            if self.current_exercise_index < len(self.exercises):
                self._start_exercise(self.current_exercise_index)
            else:
                self._start_finish()
        else:
            self._draw_text(frame, f"Prepare: {remaining}", (30, 30), (255, 0, 0))
            if self.current_exercise_index < len(self.exercises):
                ex = self.exercises[self.current_exercise_index]
                self._draw_exercise_info(frame, ex[0], ex[1])

    def _handle_exercise(self, frame, now: float):
        if self.current_exercise_index >= len(self.exercises):
            self._start_finish()
            return

        name, reps, cam, ex_id, muscle_id = self.exercises[self.current_exercise_index]

        if cam == 1:
            frame = self._process_pose(frame)
            self._draw_text(frame, f"{name}: {self.counter}/{reps}", (30, 50), (255, 0, 0))
            if self.counter >= reps:
                self._advance_exercise()

        elif self.auto_mode:
            elapsed   = now - self.current_exercise_start
            remaining = self.current_exercise_duration - int(elapsed)
            reps_so_far = int(elapsed // int(self.seconds_per_rep))
            if reps_so_far > self.completed_auto_reps and reps_so_far <= reps:
                self.reps_effects[min(reps_so_far, _MAX_REP_SOUNDS)].play()
                self.completed_auto_reps = reps_so_far
            if remaining <= 0:
                self.completed_auto_reps = 0
                self._advance_exercise()
            else:
                self._draw_text(frame, f"Exercise: {name} ({remaining}s)", (30, 50), (255, 0, 0))
                self._draw_exercise_info(frame, name, reps)
        else:
            self._draw_text(frame, f"Exercise: {name}", (30, 50), (255, 0, 0))
            self._draw_exercise_info(frame, name, reps)

    def _advance_exercise(self):
        self.current_exercise_index += 1
        if self.current_exercise_index < len(self.exercises):
            self._start_prepare()
        else:
            self._start_finish()

    # ── State transitions ──────────────────────────────────────────────────────

    def _start_prepare(self):
        self.state      = "prepare"
        self.start_time = time.time()
        self.next_exercise_button.hide()
        if int(self.prepare_duration) > 2:
            self.prepare_sound.play()

    def _start_exercise(self, index: int):
        self.state   = "exercise"
        name, reps, cam, *_ = self.exercises[index]
        self.counter = 0
        self.stage   = None
        self.exercise_sound.play()
        if self.auto_mode:
            self.current_exercise_start    = time.time()
            self.current_exercise_duration = reps * int(self.seconds_per_rep)
        else:
            self.current_exercise_start    = None
            self.current_exercise_duration = None
            if cam == 0:
                self.next_exercise_button.show()

    def _start_finish(self):
        self.state = "finished"
        self.next_exercise_button.hide()
        self.finish_sound.play()

    def _go_to_next_exercise(self):
        if not self.auto_mode and self.state == "exercise":
            self._advance_exercise()

    # ── Drawing helpers ────────────────────────────────────────────────────────

    def _draw_text(self, frame, text: str, position=(0, 0), color=(255, 255, 255)):
        """Render anti-aliased text on a BGR frame using PIL."""
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        ImageDraw.Draw(img).text(position, text, font=self.font, fill=color)
        frame[:] = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)

    def _draw_exercise_info(self, frame, name: str, reps: int):
        """Show next/current exercise hint at the bottom of the frame."""
        if self.state == "prepare":
            text = f"Next: {name}"
        elif self.state == "exercise":
            text = f"Perform {reps} reps"
        else:
            return
        y = int(frame.shape[0] - self.font_size * 1.8)
        self._draw_text(frame, text, (10, y), _GREEN_BGR)

    def _draw_arrow(self, frame, stage: str, cx: int, cy: int, length: int = 20):
        half = length // 2
        if stage == "up":
            start, end = (cx, cy + half), (cx, cy - half)
        else:
            start, end = (cx, cy - half), (cx, cy + half)
        cv2.arrowedLine(frame, start, end, _GREEN_BGR, 10, tipLength=0.2)

    def _draw_filled_bar(self, frame, progress: float,
                          bx: int, by: int, bw: int = _BAR_W, bh: int = _BAR_H,
                          color=_GREEN_BGR):
        """Draw a vertically-filled progress bar (bottom-up)."""
        progress = max(0.0, min(1.0, progress))
        cv2.rectangle(frame, (bx, by), (bx + bw, by + bh), (0, 0, 0), 2)
        fill_h = int(bh * progress)
        cv2.rectangle(frame, (bx, by + bh - fill_h), (bx + bw, by + bh), color, -1)

    # ── Pose processing ────────────────────────────────────────────────────────

    def _process_pose(self, frame):
        """Run MediaPipe Pose and dispatch to the correct rep counter."""
        results = self.pose.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if results.pose_landmarks:
            self.mp_draw.draw_landmarks(
                frame, results.pose_landmarks, self.mp_pose.POSE_CONNECTIONS)
            if self.current_exercise_index < len(self.exercises):
                name, reps, cam, *_ = self.exercises[self.current_exercise_index]
                if cam == 1:
                    dispatch = {
                        "Squats":        self._count_squats,
                        "Overhead Press":self._count_ohp,
                        "Bicep Curls":   self._count_biceps_curl,
                        "Jumping Jacks": self._count_jumping_jacks,
                        "Lunges":        self._count_lunges,
                        "Push-up":       self._count_pushup,
                        "Push-Up":       self._count_pushup,
                        "Push Up":       self._count_pushup,
                    }
                    fn = dispatch.get(name)
                    if fn:
                        fn(results.pose_landmarks, frame)
        return frame

    @staticmethod
    def _vis_ok(landmarks, *ids, thr: float = _MIN_VISIBILITY) -> bool:
        return all(landmarks.landmark[i.value].visibility > thr for i in ids)

    def _play_rep(self, n: int):
        idx = min(n, _MAX_REP_SOUNDS)
        if idx in self.reps_effects:
            self.reps_effects[idx].play()

    def calculate_angle(self, a, b, c) -> float:
        """Compute angle at joint b (degrees) from three landmarks."""
        ba = np.array([a.x - b.x, a.y - b.y])
        bc = np.array([c.x - b.x, c.y - b.y])
        cosine = np.dot(ba, bc) / (np.linalg.norm(ba) * np.linalg.norm(bc) + 1e-8)
        return float(np.degrees(np.arccos(np.clip(cosine, -1.0, 1.0))))

    # ── Exercise counters ──────────────────────────────────────────────────────

    def _count_squats(self, landmarks, frame):
        """Count squat reps and give real-time posture feedback."""
        try:
            lm = landmarks.landmark
            PL = self.mp_pose.PoseLandmark
            lh, lk, la = lm[PL.LEFT_HIP.value], lm[PL.LEFT_KNEE.value], lm[PL.LEFT_ANKLE.value]
            rh, rk, ra = lm[PL.RIGHT_HIP.value], lm[PL.RIGHT_KNEE.value], lm[PL.RIGHT_ANKLE.value]

            la_ang = self.calculate_angle(lh, lk, la)
            ra_ang = self.calculate_angle(rh, rk, ra)
            avg    = (la_ang + ra_ang) / 2.0

            vis = self._vis_ok(landmarks, PL.LEFT_HIP, PL.LEFT_KNEE, PL.LEFT_ANKLE,
                                PL.RIGHT_HIP, PL.RIGHT_KNEE, PL.RIGHT_ANKLE)
            stage = self.stage
            if vis:
                if la_ang < 90 and ra_ang < 90:   stage = "up"
                elif la_ang > 170 and ra_ang > 170: stage = "down"

            if self.stage == "up" and stage == "down":
                self.counter += 1
                self._play_rep(self.counter)
            self.stage = stage

            # Knee-over-toe check (normalised x coords)
            knee_over_toe = (lk.x > la.x + 0.04) or (rk.x < ra.x - 0.04)

            # Posture feedback (NEW)
            fb = analyze_squat_form(avg, in_squat=(stage == "up"), knee_over_toe=knee_over_toe)
            self.posture_message = fb["message"]
            self.posture_correct = fb["is_correct"]

            # Angle labels
            fh, fw = frame.shape[:2]
            self._draw_text(frame, f"{int(la_ang)}\u00b0",
                             (int(lk.x * fw) + 20, int(lk.y * fh)), _GREEN_BGR)
            self._draw_text(frame, f"{int(ra_ang)}\u00b0",
                             (int(rk.x * fw) + 20, int(rk.y * fh)), _GREEN_BGR)

            raw = (avg - 90) / (170 - 90)
            self._draw_filled_bar(frame, max(0.0, min(1.0, raw)), _BAR_X, fh // 2)
            self._draw_arrow(frame, stage, fw - 50, fh // 2 + _BAR_H // 2, _BAR_H)

        except Exception as e:
            logger.error("Squat counter error: %s", e)

    def _count_ohp(self, landmarks, frame):
        """Count overhead press reps with forearm alignment feedback."""
        try:
            lm = landmarks.landmark
            PL = self.mp_pose.PoseLandmark
            ls, le, lw, lh = (lm[PL.LEFT_SHOULDER.value], lm[PL.LEFT_ELBOW.value],
                               lm[PL.LEFT_WRIST.value], lm[PL.LEFT_HIP.value])
            rs, re, rw, rh = (lm[PL.RIGHT_SHOULDER.value], lm[PL.RIGHT_ELBOW.value],
                               lm[PL.RIGHT_WRIST.value], lm[PL.RIGHT_HIP.value])

            le_ang = self.calculate_angle(ls, le, lw)
            ls_ang = self.calculate_angle(lh, ls, le)
            re_ang = self.calculate_angle(rs, re, rw)
            rs_ang = self.calculate_angle(rh, rs, re)

            l_fa = abs(math.degrees(math.atan2(lw.y - le.y, lw.x - le.x)))
            r_fa = abs(math.degrees(math.atan2(rw.y - re.y, rw.x - re.x)))

            # Posture feedback (NEW)
            fb = analyze_ohp_form(l_fa, r_fa)
            self.posture_message = fb["message"]
            self.posture_correct = fb["is_correct"]
            if not fb["is_correct"]:
                self.wrong_ohp_sound.play()

            vis = self._vis_ok(landmarks, PL.LEFT_SHOULDER, PL.LEFT_ELBOW, PL.LEFT_WRIST,
                                PL.RIGHT_SHOULDER, PL.RIGHT_ELBOW, PL.RIGHT_WRIST)
            stage = self.stage
            if vis:
                if le_ang > 160 and ls_ang > 160 and re_ang > 160 and rs_ang > 160:
                    stage = "down"
                elif le_ang < 90 and ls_ang < 90 and re_ang < 90 and rs_ang < 90:
                    stage = "up"

            if self.stage == "up" and stage == "down":
                self.counter += 1
                self._play_rep(self.counter)
            self.stage = stage

            fh, fw = frame.shape[:2]
            self._draw_text(frame, f"{int(le_ang)}\u00b0",
                             (int(le.x * fw) + 20, int(le.y * fh)), _GREEN_BGR)
            self._draw_text(frame, f"{int(re_ang)}\u00b0",
                             (int(re.x * fw) + 20, int(re.y * fh)), _GREEN_BGR)

            avg = (le_ang + ls_ang + re_ang + rs_ang) / 4.0
            progress = 1.0 - max(0.0, min(1.0, (avg - 90) / (170 - 90)))
            bar_y = fh - 50 - _BAR_H
            self._draw_filled_bar(frame, progress, _BAR_X, bar_y)
            self._draw_arrow(frame, stage, fw - 50, bar_y + _BAR_H // 2, _BAR_H)

        except Exception as e:
            logger.error("OHP counter error: %s", e)

    def _count_biceps_curl(self, landmarks, frame):
        """Count bicep curl reps with contraction / extension feedback."""
        try:
            lm = landmarks.landmark
            PL = self.mp_pose.PoseLandmark
            ls, le, lw = lm[PL.LEFT_SHOULDER.value], lm[PL.LEFT_ELBOW.value], lm[PL.LEFT_WRIST.value]
            rs, re, rw = lm[PL.RIGHT_SHOULDER.value], lm[PL.RIGHT_ELBOW.value], lm[PL.RIGHT_WRIST.value]

            la = self.calculate_angle(ls, le, lw)
            ra = self.calculate_angle(rs, re, rw)
            avg = (la + ra) / 2.0

            vis = self._vis_ok(landmarks, PL.LEFT_SHOULDER, PL.LEFT_ELBOW, PL.LEFT_WRIST,
                                PL.RIGHT_SHOULDER, PL.RIGHT_ELBOW, PL.RIGHT_WRIST)
            stage = self.stage
            if vis:
                if la > 170 and ra > 170: stage = "up"
                elif la < 30 and ra < 30:  stage = "down"

            if self.stage == "down" and stage == "up":
                self.counter += 1
                self._play_rep(self.counter)
            self.stage = stage

            # Posture feedback (NEW)
            fb = analyze_curl_form(avg, stage)
            self.posture_message = fb["message"]
            self.posture_correct = fb["is_correct"]

            fh, fw = frame.shape[:2]
            self._draw_text(frame, f"{int(la)}\u00b0",
                             (int(le.x * fw) + 20, int(le.y * fh)), _GREEN_BGR)
            self._draw_text(frame, f"{int(ra)}\u00b0",
                             (int(re.x * fw) + 20, int(re.y * fh)), _GREEN_BGR)

            progress = 1.0 - max(0.0, min(1.0, (avg - 30) / (170 - 30)))
            bar_y = fh - 50 - _BAR_H
            self._draw_filled_bar(frame, progress, _BAR_X, bar_y)
            self._draw_arrow(frame, stage, fw - 50, bar_y + _BAR_H // 2, _BAR_H)

        except Exception as e:
            logger.error("Curl counter error: %s", e)

    def _count_jumping_jacks(self, landmarks, frame):
        """Count jumping jack reps with arm / foot spread feedback."""
        try:
            lm = landmarks.landmark
            PL = self.mp_pose.PoseLandmark
            ls = lm[PL.LEFT_SHOULDER.value];  rs = lm[PL.RIGHT_SHOULDER.value]
            le = lm[PL.LEFT_ELBOW.value];     re = lm[PL.RIGHT_ELBOW.value]
            lh = lm[PL.LEFT_HIP.value];       rh = lm[PL.RIGHT_HIP.value]
            la = lm[PL.LEFT_ANKLE.value];     ra = lm[PL.RIGHT_ANKLE.value]

            l_arm = self.calculate_angle(lh, ls, le)
            r_arm = self.calculate_angle(rh, rs, re)
            arms_up   = l_arm > 150 and r_arm > 150
            arms_down = l_arm < 30  and r_arm < 30
            feet_wide  = la.x > ls.x and ra.x < rs.x
            feet_close = la.x < ls.x and ra.x > rs.x

            vis = self._vis_ok(landmarks, PL.LEFT_SHOULDER, PL.RIGHT_SHOULDER,
                                PL.LEFT_ELBOW, PL.RIGHT_ELBOW,
                                PL.LEFT_ANKLE, PL.RIGHT_ANKLE)
            stage = self.stage
            if vis:
                if arms_up  and feet_wide:  stage = "down"
                elif arms_down and feet_close: stage = "up"

            if self.stage == "down" and stage == "up":
                self.counter += 1
                self._play_rep(self.counter)
            self.stage = stage

            # Posture feedback (NEW)
            fb = analyze_jumping_jack_form(l_arm, r_arm, feet_wide, stage)
            self.posture_message = fb["message"]
            self.posture_correct = fb["is_correct"]

            fh, fw = frame.shape[:2]
            self._draw_text(frame, f"{int(l_arm)}\u00b0",
                             (int(ls.x * fw) + 20, int(ls.y * fh)), _GREEN_BGR)
            self._draw_text(frame, f"{int(r_arm)}\u00b0",
                             (int(rs.x * fw) + 20, int(rs.y * fh)), _GREEN_BGR)

            bh = 150
            avg_arm = (l_arm + r_arm) / 2.0
            prog = 1.0 - max(0.0, min(1.0, (avg_arm - 60) / (130 - 60)))
            bar_y = fh - 50 - bh
            self._draw_filled_bar(frame, prog, _BAR_X, bar_y, bh=bh)
            self._draw_arrow(frame, stage, fw - 50, bar_y + bh // 2, bh)

        except Exception as e:
            logger.error("Jumping jack counter error: %s", e)

    def _count_lunges(self, landmarks, frame):
        """
        Count lunge reps. (NEW)

        Detection logic: a lunge is detected when one knee angle drops
        significantly below the other (asymmetric bend), indicating that
        one leg is forward and bent while the other is extended behind.
        """
        try:
            lm = landmarks.landmark
            PL = self.mp_pose.PoseLandmark
            lh, lk, la = lm[PL.LEFT_HIP.value], lm[PL.LEFT_KNEE.value], lm[PL.LEFT_ANKLE.value]
            rh, rk, ra = lm[PL.RIGHT_HIP.value], lm[PL.RIGHT_KNEE.value], lm[PL.RIGHT_ANKLE.value]

            l_ang = self.calculate_angle(lh, lk, la)
            r_ang = self.calculate_angle(rh, rk, ra)
            min_ang  = min(l_ang, r_ang)
            max_ang  = max(l_ang, r_ang)
            is_asym  = (max_ang - min_ang) > 30    # asymmetric = lunge (not squat)
            in_lunge = min_ang < 110 and is_asym

            vis = self._vis_ok(landmarks, PL.LEFT_HIP, PL.LEFT_KNEE, PL.LEFT_ANKLE,
                                PL.RIGHT_HIP, PL.RIGHT_KNEE, PL.RIGHT_ANKLE)
            stage = self.stage
            if vis:
                if in_lunge and min_ang < 110:
                    stage = "lunge"
                elif l_ang > 160 and r_ang > 160:
                    stage = "stand"

            if self.stage == "lunge" and stage == "stand":
                self.counter += 1
                self._play_rep(self.counter)
            self.stage = stage

            # Posture feedback (NEW)
            fb = analyze_lunge_form(min_ang, is_asym, in_lunge=(stage == "lunge"))
            self.posture_message = fb["message"]
            self.posture_correct = fb["is_correct"]

            fh, fw = frame.shape[:2]
            self._draw_text(frame, f"L:{int(l_ang)}\u00b0",
                             (int(lk.x * fw) + 20, int(lk.y * fh)), _GREEN_BGR)
            self._draw_text(frame, f"R:{int(r_ang)}\u00b0",
                             (int(rk.x * fw) + 20, int(rk.y * fh)), _GREEN_BGR)

            raw = (min_ang - 70) / (170 - 70)
            self._draw_filled_bar(frame, max(0.0, min(1.0, raw)), _BAR_X, fh // 2)
            self._draw_arrow(frame, "up" if in_lunge else "down",
                              fw - 50, fh // 2 + _BAR_H // 2, _BAR_H)

        except Exception as e:
            logger.error("Lunge counter error: %s", e)

    def _count_pushup(self, landmarks, frame):
        """
        Count push-up reps using the best-visible arm.

        Uses shoulder-elbow-wrist angle on whichever side the camera
        can see most clearly.  Works for side-view recordings.

        Stage: 'up' (arm > 130°) → 'down' (arm < 100°) → 'up' = 1 rep.
        Audio plays immediately when the rep is counted.
        """
        try:
            lm = landmarks.landmark
            PL = self.mp_pose.PoseLandmark

            ls = lm[PL.LEFT_SHOULDER.value];  le = lm[PL.LEFT_ELBOW.value];  lw = lm[PL.LEFT_WRIST.value]
            rs = lm[PL.RIGHT_SHOULDER.value]; re = lm[PL.RIGHT_ELBOW.value]; rw = lm[PL.RIGHT_WRIST.value]

            l_vis = min(ls.visibility, le.visibility, lw.visibility)
            r_vis = min(rs.visibility, re.visibility, rw.visibility)

            if max(l_vis, r_vis) < 0.35:
                return

            if l_vis >= r_vis:
                arm_ang = self.calculate_angle(ls, le, lw)
                ex_px   = (int(le.x * frame.shape[1]) + 20, int(le.y * frame.shape[0]))
            else:
                arm_ang = self.calculate_angle(rs, re, rw)
                ex_px   = (int(re.x * frame.shape[1]) + 20, int(re.y * frame.shape[0]))

            stage = self.stage
            if   arm_ang > 130: stage = "up"
            elif arm_ang < 100: stage = "down"

            if self.stage == "down" and stage == "up":
                self.counter += 1
                self._play_rep(self.counter)        # immediate audio
            self.stage = stage

            # Posture feedback
            if stage == "down" and arm_ang > 90:
                self.posture_message = "Go Lower!"
                self.posture_correct = False
            elif stage == "up" and arm_ang < 140:
                self.posture_message = "Push Up Fully!"
                self.posture_correct = False
            else:
                self.posture_message = "Good Form \u2713"
                self.posture_correct = True

            # Angle overlay on frame
            self._draw_text(frame, f"{int(arm_ang)}\u00b0", ex_px, _GREEN_BGR)

        except Exception as e:
            logger.error("Push-up counter error: %s", e)

    # ── Session save ───────────────────────────────────────────────────────────

    def _save_session(self):
        """Save completed session to SQLite history and JSON log. (ENHANCED)"""
        if not self._save_history_db():
            return
        # JSON session log (NEW)
        try:
            exercise_name = (self.exercises[0][0]
                             if len(self.exercises) == 1
                             else self.workout)
            self.session_logger.log_session(
                exercise=exercise_name,
                reps=self.counter,
                start_time=self.session_start,
                end_time=time.time(),
            )
        except Exception as e:
            logger.error("JSON session log failed: %s", e)

    def _save_history_db(self) -> bool:
        """Persist the completed session to the SQLite history table."""
        workout_id = get_workout_id_by_name(self.user, self.workout)
        if workout_id is None:
            QMessageBox.warning(self, "Error",
                f"Workout '{self.workout}' not found. History not saved.")
            return False

        now = datetime.datetime.now()
        exercise_str = "".join(f"{ex[0]};{ex[1]};" for ex in self.exercises)
        success = insert_history_record(
            self.user, self.workout,
            now.year, now.month, now.day, now.hour, now.minute,
            exercise_str,
        )
        if not success:
            QMessageBox.critical(self, "Error", "Failed to save history.")
        return success

    # ── Cleanup ────────────────────────────────────────────────────────────────

    def stop_all(self):
        """Release camera, stop timer, close MediaPipe Pose safely."""
        timer = getattr(self, "timer", None)
        if timer is not None and timer.isActive():
            timer.stop()

        cap = getattr(self, "cap", None)
        if cap is not None:
            if cap.isOpened():
                cap.release()
            self.cap = None

        pose = getattr(self, "pose", None)
        if pose is not None:
            try:
                pose.close()
            except Exception:
                pass
            self.pose = None

        try:
            cv2.destroyAllWindows()
        except Exception:
            pass

    def closeEvent(self, event):
        self.stop_all()
        event.accept()
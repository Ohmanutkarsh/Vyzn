"""
Downscaled MOG2 motion pre-filter.
Cheaply discards non-motion frames to eliminate unnecessary deep learning inference.
Hardened against OSD timestamp noise, lighting shifts, compression artifacts, and shadow leakage.
"""

from __future__ import annotations
import cv2
import numpy as np
from collections import deque
from typing import Tuple, Dict, List, Optional


class MOG2MotionGate:
    """
    Per-camera MOG2 background subtractor operating on downscaled frames.
    Suppresses shadows to minimize false alarms and computes normalized motion extent.
    """

    def __init__(
        self,
        history: int = 500,
        var_threshold: float = 25.0,
        min_motion_ratio: float = 0.010,  # 1.0% frame change default threshold
        learning_rate: float = 0.004,     # Slow background adaptation rate
        min_contour_area_ratio: float = 0.004,  # 0.4% ROI contour filter
        warmup_frames: int = 0,           # Configurable warmup suppression window
        global_change_ratio: float = 0.60, # Reject sudden full-frame lighting spikes (>60%)
        smooth_window: int = 4            # Moving average smoothing over ~1s
    ):
        self.history = history
        self.var_threshold = var_threshold
        self.min_motion_ratio = min_motion_ratio
        self.learning_rate = learning_rate
        self.min_contour_area_ratio = min_contour_area_ratio
        self.warmup_frames = warmup_frames
        self.global_change_ratio = global_change_ratio
        self.smooth_window = smooth_window

        self._subtractors: Dict[str, cv2.BackgroundSubtractorMOG2] = {}
        self._camera_areas: Dict[str, List[List[List[float]]]] = {}
        self._osd_polygons: Dict[str, List[List[List[float]]]] = {}
        self._dropped_outside: Dict[str, bool] = {}
        self._frame_counts: Dict[str, int] = {}
        self._prev_mean_brightness: Dict[str, float] = {}
        self._history_ratios: Dict[str, deque] = {}
        self._had_global_change: Dict[str, bool] = {}

    def _get_subtractor(self, camera_id: str) -> cv2.BackgroundSubtractorMOG2:
        if camera_id not in self._subtractors:
            self._subtractors[camera_id] = cv2.createBackgroundSubtractorMOG2(
                history=self.history,
                varThreshold=self.var_threshold,
                detectShadows=True  # Detect shadows so we can explicitly threshold them out
            )
            self._frame_counts[camera_id] = 0
            self._history_ratios[camera_id] = deque(maxlen=self.smooth_window)
            self._had_global_change[camera_id] = False
        return self._subtractors[camera_id]

    def set_camera_areas(self, camera_id: str, polygons: Optional[List[List[List[float]]]] = None):
        """Sets normalized polygon watch areas [[ [x, y], ... ], ...] for a camera."""
        if polygons:
            self._camera_areas[camera_id] = polygons
        elif camera_id in self._camera_areas:
            del self._camera_areas[camera_id]

    def set_osd_polygons(self, camera_id: str, polygons: Optional[List[List[List[float]]]] = None):
        """Sets normalized exclusion polygons for camera on-screen display (OSD / clock)."""
        if polygons:
            self._osd_polygons[camera_id] = polygons
        elif camera_id in self._osd_polygons:
            del self._osd_polygons[camera_id]

    def had_motion_dropped_outside(self, camera_id: str) -> bool:
        """Returns True if the most recent frame had motion dropped because it was outside all watch areas."""
        return self._dropped_outside.get(camera_id, False)

    def is_in_warmup(self, camera_id: str) -> bool:
        """Returns True if camera is still in initial MOG2 background seeding warmup."""
        return self._frame_counts.get(camera_id, 0) < self.warmup_frames

    def had_global_change(self, camera_id: str) -> bool:
        """Returns True if the most recent frame had a global lighting / IR switch spike."""
        return self._had_global_change.get(camera_id, False)

    def process_frame(
        self,
        camera_id: str,
        frame: np.ndarray,
        watch_polygons: Optional[List[List[List[float]]]] = None,
        osd_polygons: Optional[List[List[List[float]]]] = None,
        learning_rate: Optional[float] = None
    ) -> Tuple[bool, float, np.ndarray]:
        """
        Applies hardened MOG2 subtraction to frame with watch area ROI masking,
        OSD exclusion, shadow suppression, morphological noise removal,
        contour area filtering, warmup suppression, and lighting spike rejection.

        Returns:
            (has_motion: bool, motion_ratio: float, fg_mask: np.ndarray)
        """
        subtractor = self._get_subtractor(camera_id)
        self._frame_counts[camera_id] = self._frame_counts.get(camera_id, 0) + 1
        frame_idx = self._frame_counts[camera_id]

        lr = learning_rate if learning_rate is not None else self.learning_rate

        # 1. Convert to grayscale & Gaussian blur
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        h, w = gray.shape
        total_pixels = h * w
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # 2. Global lighting jump check (auto-exposure, day/night IR switch)
        cur_mean_brightness = float(np.mean(blurred))
        prev_mean = self._prev_mean_brightness.get(camera_id, cur_mean_brightness)
        self._prev_mean_brightness[camera_id] = cur_mean_brightness
        brightness_jump = abs(cur_mean_brightness - prev_mean)

        # 3. Apply MOG2 with controlled learning rate
        raw_fg = subtractor.apply(blurred, learningRate=lr)

        # 4. Shadow Elimination: drop shadow pixels (value 127 in OpenCV MOG2)
        # Foreground is 255; shadows are 127; background is 0. Threshold at 200 keeps only true foreground.
        _, fg_binary = cv2.threshold(raw_fg, 200, 255, cv2.THRESH_BINARY)

        # 5. Check for global lighting / camera shift
        raw_foreground_ratio = cv2.countNonZero(fg_binary) / float(total_pixels)
        if raw_foreground_ratio >= self.global_change_ratio or (brightness_jump >= 35.0 and raw_foreground_ratio >= 0.40 and frame_idx > 5):
            # Sudden massive change: reject as global illumination event, re-seed background model
            self._had_global_change[camera_id] = True
            # Quickly re-seed subtractor
            subtractor.apply(blurred, learningRate=0.5)
            self._history_ratios[camera_id].clear()
            return False, 0.0, np.zeros_like(fg_binary)
        else:
            self._had_global_change[camera_id] = False

        # 6. Warmup suppression: during first N frames, model trains without generating motion alerts
        if frame_idx <= self.warmup_frames:
            return False, 0.0, np.zeros_like(fg_binary)

        # 7. Morphological cleaning: Open (remove speckles) then Close (fill gaps)
        kernel_open = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        kernel_close = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        fg_cleaned = cv2.morphologyEx(fg_binary, cv2.MORPH_OPEN, kernel_open)
        fg_cleaned = cv2.morphologyEx(fg_cleaned, cv2.MORPH_CLOSE, kernel_close)

        # 8. Build ROI mask (Watch Areas) and Exclusion Mask (OSD / Timestamp)
        polys = watch_polygons if watch_polygons is not None else self._camera_areas.get(camera_id, [])
        osd_list = osd_polygons if osd_polygons is not None else self._osd_polygons.get(camera_id, [])

        # Start with full frame or watch areas
        if polys and len(polys) > 0:
            roi_mask = np.zeros((h, w), dtype=np.uint8)
            for poly in polys:
                if len(poly) >= 3:
                    pts = np.array([[int(p[0] * w), int(p[1] * h)] for p in poly], dtype=np.int32)
                    cv2.fillPoly(roi_mask, [pts], 255)
        else:
            roi_mask = np.full((h, w), 255, dtype=np.uint8)

        # Exclude OSD / Timestamp regions (zero out of roi_mask)
        if osd_list and len(osd_list) > 0:
            for osd in osd_list:
                if len(osd) >= 3:
                    pts = np.array([[int(p[0] * w), int(p[1] * h)] for p in osd], dtype=np.int32)
                    cv2.fillPoly(roi_mask, [pts], 0)

        # Apply ROI mask to cleaned foreground
        masked_fg = cv2.bitwise_and(fg_cleaned, roi_mask)
        roi_pixels = cv2.countNonZero(roi_mask)

        # 9. Minimum Contour Area Filter: eliminate noise smaller than min_contour_area_ratio of ROI
        min_contour_area = max(16.0, float(roi_pixels) * self.min_contour_area_ratio)
        contours, _ = cv2.findContours(masked_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        final_fg = np.zeros_like(masked_fg)
        for cnt in contours:
            if cv2.contourArea(cnt) >= min_contour_area:
                cv2.drawContours(final_fg, [cnt], -1, 255, -1)

        # 10. Compute Motion Ratio & Moving Average Smoothing
        filtered_motion_pixels = cv2.countNonZero(final_fg)
        instant_ratio = filtered_motion_pixels / float(roi_pixels) if roi_pixels > 0 else 0.0

        ratios_hist = self._history_ratios[camera_id]
        ratios_hist.append(instant_ratio)
        smoothed_ratio = float(np.mean(ratios_hist))

        has_motion = smoothed_ratio >= self.min_motion_ratio

        # Check if raw frame had motion, but was dropped because it was outside watch areas
        raw_cleaned_pixels = cv2.countNonZero(fg_cleaned)
        raw_ratio = raw_cleaned_pixels / float(total_pixels)
        raw_has_motion = raw_ratio >= self.min_motion_ratio

        if polys and len(polys) > 0:
            self._dropped_outside[camera_id] = raw_has_motion and not has_motion
        else:
            self._dropped_outside[camera_id] = False

        return has_motion, smoothed_ratio, final_fg

    def reset_camera(self, camera_id: str):
        """Clears background model for a specific camera (e.g. after lighting shift or reconnect)."""
        if camera_id in self._subtractors:
            del self._subtractors[camera_id]
        if camera_id in self._dropped_outside:
            del self._dropped_outside[camera_id]
        if camera_id in self._frame_counts:
            del self._frame_counts[camera_id]
        if camera_id in self._prev_mean_brightness:
            del self._prev_mean_brightness[camera_id]
        if camera_id in self._history_ratios:
            del self._history_ratios[camera_id]
        if camera_id in self._had_global_change:
            del self._had_global_change[camera_id]

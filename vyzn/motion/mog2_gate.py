"""
Downscaled MOG2 motion pre-filter.
Cheaply discards non-motion frames to eliminate unnecessary deep learning inference.
Hardened against OSD timestamp noise, lighting shifts, compression artifacts, and shadow leakage.
"""

from __future__ import annotations
import cv2
import math
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
        learning_rate: float = 0.003,     # 0.003 fixed background adaptation rate
        min_contour_area_ratio: float = 0.0015,  # 0.15% ROI contour filter (auto-tunable)
        warmup_frames: int = 0,           # Configurable warmup suppression window
        global_change_ratio: float = 0.60, # Reject sudden full-frame lighting spikes (>60%)
        smooth_window: int = 8            # Moving average smoothing over 2.0s (~8 frames @ 4fps)
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
        self._camera_contour_ratios: Dict[str, float] = {}
        self._dropped_outside: Dict[str, bool] = {}
        self._frame_counts: Dict[str, int] = {}
        self._prev_mean_brightness: Dict[str, float] = {}
        self._history_ratios: Dict[str, deque] = {}
        self._had_global_change: Dict[str, bool] = {}
        # In simple terms: track motion centroid history to detect and suppress periodic stationary motion (e.g. spinning fans, hair flutter)
        self._motion_centroid_history: Dict[str, deque] = {}
        self._periodic_motion_detected: Dict[str, bool] = {}

    def set_camera_contour_ratio(self, camera_id: str, ratio: float):
        """Sets per-camera minimum contour area ratio override."""
        self._camera_contour_ratios[camera_id] = max(0.0001, float(ratio))

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
            self._motion_centroid_history[camera_id] = deque(maxlen=30)
            self._periodic_motion_detected[camera_id] = False
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

    def is_periodic_motion_detected(self, camera_id: str) -> bool:
        """Returns True if the camera is currently detecting periodic stationary motion (e.g. spinning fan)."""
        return self._periodic_motion_detected.get(camera_id, False)

    def process_frame(
        self,
        camera_id: str,
        frame: np.ndarray,
        watch_polygons: Optional[List[List[List[float]]]] = None,
        osd_polygons: Optional[List[List[List[float]]]] = None,
        learning_rate: Optional[float] = None,
        tracked_boxes: Optional[List[List[float]]] = None,
        ignore_polygons: Optional[List[List[List[float]]]] = None
    ) -> Tuple[bool, float, np.ndarray]:
        """
        Applies hardened MOG2 subtraction to frame with watch area ROI masking,
        OSD exclusion, ignore area exclusion, shadow suppression, morphological noise removal,
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

        # In simple terms: prevent stationary tracked persons from being absorbed into background
        feed_image = blurred
        if tracked_boxes and frame_idx > self.warmup_frames:
            try:
                bg_img = subtractor.getBackgroundImage()
                if bg_img is not None:
                    bg_gray = cv2.cvtColor(bg_img, cv2.COLOR_BGR2GRAY) if len(bg_img.shape) == 3 else bg_img
                    feed_image = blurred.copy()
                    for box in tracked_boxes:
                        bx1, by1, bx2, by2 = int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)
                        bx1, by1 = max(0, bx1), max(0, by1)
                        bx2, by2 = min(w, bx2), min(h, by2)
                        if bx2 > bx1 and by2 > by1:
                            feed_image[by1:by2, bx1:bx2] = bg_gray[by1:by2, bx1:bx2]
            except Exception:
                feed_image = blurred

        # 2. Global lighting jump check (auto-exposure, day/night IR switch)
        cur_mean_brightness = float(np.mean(blurred))
        prev_mean = self._prev_mean_brightness.get(camera_id, cur_mean_brightness)
        self._prev_mean_brightness[camera_id] = cur_mean_brightness
        brightness_jump = abs(cur_mean_brightness - prev_mean)

        # 3. Apply MOG2 with controlled learning rate
        raw_fg = subtractor.apply(feed_image, learningRate=lr)

        # 4. Shadow Elimination: drop shadow pixels (value 127 in OpenCV MOG2)
        # Foreground is 255; shadows are 127; background is 0. Threshold at 200 keeps only true foreground.
        _, fg_binary = cv2.threshold(raw_fg, 200, 255, cv2.THRESH_BINARY)

        # Mark tracked object regions as foreground in fg_binary so stationary persons are never lost
        if tracked_boxes:
            for box in tracked_boxes:
                bx1, by1, bx2, by2 = int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)
                bx1, by1 = max(0, bx1), max(0, by1)
                bx2, by2 = min(w, bx2), min(h, by2)
                if bx2 > bx1 and by2 > by1:
                    fg_binary[by1:by2, bx1:bx2] = 255

        # 5. Check for global lighting / camera shift
        raw_foreground_ratio = cv2.countNonZero(fg_binary) / float(total_pixels)
        if raw_foreground_ratio >= self.global_change_ratio or (brightness_jump >= 25.0 and raw_foreground_ratio >= 0.25 and frame_idx > 5):
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

        # In simple terms: zero out OSD text regions and ignore areas (like ceiling fans) from the ROI mask
        # so motion occurring inside them is completely erased and produces zero motion pixels.
        combined_exclusions = []
        if osd_list and len(osd_list) > 0:
            combined_exclusions.extend(osd_list)
        if ignore_polygons and len(ignore_polygons) > 0:
            combined_exclusions.extend(ignore_polygons)

        if combined_exclusions:
            for exc in combined_exclusions:
                if len(exc) >= 3:
                    pts = np.array([[int(p[0] * w), int(p[1] * h)] for p in exc], dtype=np.int32)
                    cv2.fillPoly(roi_mask, [pts], 0)

        # Apply ROI mask to cleaned foreground
        masked_fg = cv2.bitwise_and(fg_cleaned, roi_mask)
        roi_pixels = cv2.countNonZero(roi_mask)

        # 9. Minimum Contour Area Filter: eliminate noise smaller than min_contour_area_ratio of ROI
        contour_ratio = self._camera_contour_ratios.get(camera_id, self.min_contour_area_ratio)
        min_contour_area = max(16.0, float(roi_pixels) * contour_ratio)
        contours, _ = cv2.findContours(masked_fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        final_fg = np.zeros_like(masked_fg)
        for cnt in contours:
            if cv2.contourArea(cnt) >= min_contour_area:
                cv2.drawContours(final_fg, [cnt], -1, 255, -1)

        # 10. Compute Motion Ratio & Moving Average Smoothing
        filtered_motion_pixels = cv2.countNonZero(final_fg)
        instant_ratio = filtered_motion_pixels / float(roi_pixels) if roi_pixels > 0 else 0.0

        # Periodic stationary motion filter (e.g. spinning ceiling fans, hair flutter in front of camera)
        # In simple terms: if moving pixels stay trapped in the exact same spot without translating across
        # the camera view, and there is no verified tracked person there, classify it as periodic noise and suppress.
        if camera_id not in self._motion_centroid_history:
            self._motion_centroid_history[camera_id] = deque(maxlen=30)
            self._periodic_motion_detected[camera_id] = False

        if instant_ratio > 0.003 and contours:
            c_largest = max(contours, key=cv2.contourArea)
            M = cv2.moments(c_largest)
            if M["m00"] > 0:
                cx = (M["m10"] / M["m00"]) / float(w)
                cy = (M["m01"] / M["m00"]) / float(h)
                self._motion_centroid_history[camera_id].append((cx, cy))
            else:
                self._motion_centroid_history[camera_id].append((0.5, 0.5))
        else:
            self._motion_centroid_history[camera_id].clear()

        # Check if centroid has zero spatial translation across 12+ frames
        hist = self._motion_centroid_history[camera_id]
        if len(hist) >= 12:
            std_x = float(np.std([p[0] for p in hist]))
            std_y = float(np.std([p[1] for p in hist]))
            mean_y = float(np.mean([p[1] for p in hist]))
            spatial_spread = math.hypot(std_x, std_y)
            has_tracked_person = bool(tracked_boxes and len(tracked_boxes) > 0)
            # If motion is stationary periodic oscillation (ceiling fan or flutter) and no confirmed tracked person is present
            is_ceiling_fan = (spatial_spread < 0.040 and mean_y < 0.40)
            is_localized_periodic = (spatial_spread < 0.025)
            if (is_ceiling_fan or is_localized_periodic) and not has_tracked_person:
                self._periodic_motion_detected[camera_id] = True
                # Attenuate the motion ratio so a spinning fan doesn't keep the pipeline recording
                instant_ratio = instant_ratio * 0.10
            else:
                self._periodic_motion_detected[camera_id] = False
        else:
            self._periodic_motion_detected[camera_id] = False

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
        if camera_id in self._motion_centroid_history:
            del self._motion_centroid_history[camera_id]
        if camera_id in self._periodic_motion_detected:
            del self._periodic_motion_detected[camera_id]

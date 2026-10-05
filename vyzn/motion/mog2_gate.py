"""
Downscaled MOG2 motion pre-filter.
Cheaply discards non-motion frames to eliminate unnecessary deep learning inference.
"""

from __future__ import annotations
import cv2
import numpy as np
from typing import Tuple, Dict


class MOG2MotionGate:
    """
    Per-camera MOG2 background subtractor operating on downscaled frames.
    Suppresses shadows to minimize false alarms and computes normalized motion extent.
    """

    def __init__(
        self,
        history: int = 300,
        var_threshold: float = 16.0,
        min_motion_ratio: float = 0.005  # 0.5% frame change threshold
    ):
        self.history = history
        self.var_threshold = var_threshold
        self.min_motion_ratio = min_motion_ratio
        self._subtractors: Dict[str, cv2.BackgroundSubtractorMOG2] = {}
        self._camera_areas: Dict[str, List[List[List[float]]]] = {}
        self._dropped_outside: Dict[str, bool] = {}

    def _get_subtractor(self, camera_id: str) -> cv2.BackgroundSubtractorMOG2:
        if camera_id not in self._subtractors:
            self._subtractors[camera_id] = cv2.createBackgroundSubtractorMOG2(
                history=self.history,
                varThreshold=self.var_threshold,
                detectShadows=False  # Disabling shadows avoids 3x grayscale post-process cost
            )
        return self._subtractors[camera_id]

    def set_camera_areas(self, camera_id: str, polygons: Optional[List[List[List[float]]]] = None):
        """Sets normalized polygon watch areas [[ [x, y], ... ], ...] for a camera."""
        if polygons:
            self._camera_areas[camera_id] = polygons
        elif camera_id in self._camera_areas:
            del self._camera_areas[camera_id]

    def had_motion_dropped_outside(self, camera_id: str) -> bool:
        """Returns True if the most recent frame had motion dropped because it was outside all watch areas."""
        return self._dropped_outside.get(camera_id, False)

    def process_frame(
        self,
        camera_id: str,
        frame: np.ndarray,
        watch_polygons: Optional[List[List[List[float]]]] = None
    ) -> Tuple[bool, float, np.ndarray]:
        """
        Applies MOG2 subtraction to frame with optional watch area polygon masking.
        Returns:
            (has_motion: bool, motion_ratio: float, fg_mask: np.ndarray)
        """
        subtractor = self._get_subtractor(camera_id)

        # Convert to grayscale if 3-channel
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        else:
            gray = frame

        # Apply Gaussian blur to reduce high-frequency sensor noise
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)

        # Compute foreground mask
        fg_mask = subtractor.apply(blurred)

        h, w = gray.shape
        total_pixels = h * w
        raw_motion_pixels = cv2.countNonZero(fg_mask)
        raw_motion_ratio = raw_motion_pixels / float(total_pixels)
        raw_has_motion = raw_motion_ratio >= self.min_motion_ratio

        polys = watch_polygons if watch_polygons is not None else self._camera_areas.get(camera_id, [])

        if polys and len(polys) > 0:
            # Create binary ROI mask: 255 inside watch areas, 0 outside
            roi_mask = np.zeros((h, w), dtype=np.uint8)
            for poly in polys:
                if len(poly) >= 3:
                    pts = np.array([[int(p[0] * w), int(p[1] * h)] for p in poly], dtype=np.int32)
                    cv2.fillPoly(roi_mask, [pts], 255)

            # Mask foreground to only include motion inside watch areas
            masked_fg = cv2.bitwise_and(fg_mask, roi_mask)
            roi_pixels = cv2.countNonZero(roi_mask)
            roi_motion_pixels = cv2.countNonZero(masked_fg)

            motion_ratio = roi_motion_pixels / float(roi_pixels) if roi_pixels > 0 else 0.0
            has_motion = motion_ratio >= self.min_motion_ratio

            # Dropped outside: raw frame had motion, but nothing inside watch areas
            self._dropped_outside[camera_id] = raw_has_motion and not has_motion
            return has_motion, motion_ratio, masked_fg
        else:
            self._dropped_outside[camera_id] = False
            has_motion = raw_has_motion
            return has_motion, raw_motion_ratio, fg_mask

    def reset_camera(self, camera_id: str):
        """Clears background model for a specific camera (e.g. after lighting shift)."""
        if camera_id in self._subtractors:
            del self._subtractors[camera_id]
        if camera_id in self._dropped_outside:
            del self._dropped_outside[camera_id]

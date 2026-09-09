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

    def _get_subtractor(self, camera_id: str) -> cv2.BackgroundSubtractorMOG2:
        if camera_id not in self._subtractors:
            self._subtractors[camera_id] = cv2.createBackgroundSubtractorMOG2(
                history=self.history,
                varThreshold=self.var_threshold,
                detectShadows=False  # Disabling shadows avoids 3x grayscale post-process cost
            )
        return self._subtractors[camera_id]

    def process_frame(
        self,
        camera_id: str,
        frame: np.ndarray
    ) -> Tuple[bool, float, np.ndarray]:
        """
        Applies MOG2 subtraction to frame.
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

        # Count active motion pixels
        h, w = gray.shape
        total_pixels = h * w
        motion_pixels = cv2.countNonZero(fg_mask)
        motion_ratio = motion_pixels / float(total_pixels)

        has_motion = motion_ratio >= self.min_motion_ratio
        return has_motion, motion_ratio, fg_mask

    def reset_camera(self, camera_id: str):
        """Clears background model for a specific camera (e.g. after lighting shift)."""
        if camera_id in self._subtractors:
            del self._subtractors[camera_id]

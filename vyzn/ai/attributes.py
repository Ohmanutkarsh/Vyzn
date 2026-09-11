"""
Appearance attribute extraction module.
Performs fast, lightweight HSV color and clothing analysis on detection bounding boxes
without heavy neural networks or cloud dependencies.
"""

from __future__ import annotations
from typing import Dict, Any, List, Tuple
import cv2
import numpy as np
import logging

logger = logging.getLogger("vyzn.ai.attributes")


def classify_hsv_pixel(h: int, s: int, v: int) -> str:
    """Classifies a single HSV pixel into a standard color bucket."""
    if v < 55:
        return "black"
    if s < 40 and v >= 190:
        return "white"
    if s < 45 and 55 <= v < 190:
        return "grey"

    if (h >= 0 and h <= 10) or (h >= 165 and h <= 179):
        return "red"
    elif 11 <= h <= 24:
        return "orange"
    elif 25 <= h <= 35:
        return "yellow"
    elif 36 <= h <= 85:
        return "green"
    elif 86 <= h <= 100:
        return "cyan"
    elif 101 <= h <= 135:
        return "blue"
    elif 136 <= h <= 164:
        return "purple"
    return "grey"


def get_dominant_color_from_patch(bgr_patch: np.ndarray) -> Tuple[str, float]:
    """Computes the dominant color bucket and its percentage from a BGR image patch."""
    if bgr_patch is None or bgr_patch.size == 0 or bgr_patch.shape[0] < 2 or bgr_patch.shape[1] < 2:
        return "unspecified", 0.0

    # Downsample for fast evaluation (< 0.2 ms)
    small = cv2.resize(bgr_patch, (32, 32), interpolation=cv2.INTER_AREA)
    hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)

    counts: Dict[str, int] = {}
    total = small.shape[0] * small.shape[1]

    for y in range(small.shape[0]):
        for x in range(small.shape[1]):
            h, s, v = hsv[y, x]
            c = classify_hsv_pixel(int(h), int(s), int(v))
            counts[c] = counts.get(c, 0) + 1

    if not counts:
        return "unspecified", 0.0

    dominant = max(counts.items(), key=lambda item: item[1])
    pct = round((dominant[1] / float(total)) * 100.0, 1)
    return dominant[0], pct


def extract_appearance_attributes(
    frame: np.ndarray,
    box: List[float],
    object_type: str = "person"
) -> Dict[str, Any]:
    """
    Extracts structured color and apparel attributes from a detection crop.
    
    Args:
        frame: Full BGR frame (H, W, 3).
        box: Normalized bounding box [x1, y1, x2, y2] (0.0 to 1.0).
        object_type: Detected class ('person', 'vehicle', 'animal', etc.)

    Returns:
        Dictionary with dominant_color, upper_color, lower_color, and tags.
    """
    if frame is None or frame.size == 0:
        return {
            "dominant_color": "unspecified",
            "upper_color": "unspecified",
            "lower_color": "unspecified",
            "confidence": 0.0,
            "tags": []
        }

    h, w = frame.shape[:2]
    x1 = max(0, min(w - 1, int(box[0] * w)))
    y1 = max(0, min(h - 1, int(box[1] * h)))
    x2 = max(0, min(w, int(box[2] * w)))
    y2 = max(0, min(h, int(box[3] * h)))

    if x2 <= x1 or y2 <= y1:
        return {
            "dominant_color": "unspecified",
            "upper_color": "unspecified",
            "lower_color": "unspecified",
            "confidence": 0.0,
            "tags": []
        }

    crop = frame[y1:y2, x1:x2]
    crop_h = crop.shape[0]

    dominant_col, dom_pct = get_dominant_color_from_patch(crop)

    tags = []
    if dominant_col != "unspecified":
        tags.append(f"color_{dominant_col}")

    upper_col = "unspecified"
    lower_col = "unspecified"

    if object_type == "person" and crop_h >= 10:
        # Upper body: 15% to 55% from top
        y_upper_start = int(crop_h * 0.15)
        y_upper_end = int(crop_h * 0.55)
        upper_patch = crop[y_upper_start:y_upper_end, :]
        if upper_patch.size > 0:
            upper_col, _ = get_dominant_color_from_patch(upper_patch)
            if upper_col != "unspecified":
                tags.append(f"upper_{upper_col}")

        # Lower body: 55% to 95% from top
        y_lower_start = int(crop_h * 0.55)
        y_lower_end = int(crop_h * 0.95)
        lower_patch = crop[y_lower_start:y_lower_end, :]
        if lower_patch.size > 0:
            lower_col, _ = get_dominant_color_from_patch(lower_patch)
            if lower_col != "unspecified":
                tags.append(f"lower_{lower_col}")

    # Dominant color fallback to upper body color for person
    final_dom = upper_col if (object_type == "person" and upper_col != "unspecified") else dominant_col

    return {
        "dominant_color": final_dom,
        "upper_color": upper_col,
        "lower_color": lower_col,
        "confidence": dom_pct,
        "tags": tags
    }

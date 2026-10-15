"""
Object detector abstraction and implementations.
Decouples inference backend from application logic to prevent AGPL copyleft lock-in.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional
import numpy as np
import logging

logger = logging.getLogger("vyzn.ai.detector")


CONFIDENCE_GATES = {
    "person": {"start": 0.35, "continue": 0.25},
    "vehicle": {"start": 0.40, "continue": 0.30},
    "animal": {"start": 0.45, "continue": 0.35},
    "carried_item": {"start": 0.50, "continue": 0.40},
}


def get_confidence_gate(category: str, is_night_ir: bool = False, mode: str = "start") -> float:
    """Returns the calibrated confidence gate for start/continue with IR night offset."""
    gates = CONFIDENCE_GATES.get(category, {"start": 0.40, "continue": 0.30})
    base = gates.get(mode, 0.35)
    return round(base + (0.05 if is_night_ir else 0.0), 3)


@dataclass
class Detection:
    box: List[float]       # [x1, y1, x2, y2] normalized to 0.0 - 1.0
    confidence: float      # 0.0 to 1.0
    class_id: int          # COCO class id (0 = person)
    label: str             # 'person', 'vehicle', 'animal', 'carried_item'
    raw_label: str = ""    # 'backpack', 'car', 'dog', etc.


class BaseDetector(ABC):
    """Abstract interface for all computer vision detectors."""

    @abstractmethod
    def detect(self, frame: np.ndarray, is_night_ir: bool = False) -> List[Detection]:
        """Runs inference on a single BGR image."""
        pass


class YOLOv8Detector(BaseDetector):
    """
    Ultralytics YOLOv8 implementation for local development and Phase 1 testing.
    Can be swapped seamlessly for RF-DETR (Apache 2.0) via BaseDetector.
    """

    COCO_MAP = {
        0: ("person", "person"),
        1: ("bicycle", "vehicle"),
        2: ("car", "vehicle"),
        3: ("motorcycle", "vehicle"),
        5: ("bus", "vehicle"),
        7: ("truck", "vehicle"),
        15: ("cat", "animal"),
        16: ("dog", "animal"),
        24: ("backpack", "carried_item"),
        26: ("handbag", "carried_item"),
        28: ("suitcase", "carried_item"),
    }

    def __init__(self, model_name: str = "yolov8n.pt", conf_thresh: float = 0.20):
        from ultralytics import YOLO
        logger.info(f"Loading YOLO model: {model_name}")
        self.model = YOLO(model_name)
        self.conf_thresh = conf_thresh

    def detect(self, frame: np.ndarray, is_night_ir: bool = False) -> List[Detection]:
        h, w = frame.shape[:2]
        # Run raw model with minimum continue threshold (0.20) to capture candidates
        min_thresh = 0.25 if is_night_ir else 0.20
        results = self.model(frame, conf=min_thresh, verbose=False)
        detections: List[Detection] = []

        if not results:
            return detections

        for r in results:
            boxes = r.boxes
            if boxes is None:
                continue

            for box in boxes:
                cls_id = int(box.cls[0].item())
                conf = float(box.conf[0].item())

                # Filter to target categories of interest
                if cls_id in self.COCO_MAP:
                    raw_label, category = self.COCO_MAP[cls_id]
                    xyxy = box.xyxy[0].tolist()
                    # Normalize bounding box coordinates to [0.0, 1.0]
                    norm_box = [
                        max(0.0, xyxy[0] / w),
                        max(0.0, xyxy[1] / h),
                        min(1.0, xyxy[2] / w),
                        min(1.0, xyxy[3] / h)
                    ]
                    detections.append(Detection(
                        box=norm_box,
                        confidence=conf,
                        class_id=cls_id,
                        label=category,
                        raw_label=raw_label
                    ))

        return detections


class MockDetector(BaseDetector):
    """
    Geometry-grounded human silhouette detector for synthetic feeds and fast testing.
    Rejects ceiling fans (aspect ratio ~1.0) and hair flutter (<2% area).
    Only detects a person if upright vertical human proportions (aspect ratio 1.25 to 4.2) are present.
    """

    def __init__(self, fixed_confidence: Optional[float] = None):
        self.fixed_confidence = fixed_confidence

    def detect(self, frame: np.ndarray) -> List[Detection]:
        if frame is None or frame.size == 0:
            return []
        h, w = frame.shape[:2]
        if len(frame.shape) == 3:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if hasattr(cv2, "cvtColor") else np.mean(frame, axis=2).astype(np.uint8)
        else:
            gray = frame

        # Threshold dark foreground objects
        _, thresh = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        detections: List[Detection] = []
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            area_ratio = (cw * ch) / float(h * w)
            aspect_ratio = ch / float(cw) if cw > 0 else 0.0
            height_ratio = ch / float(h)

            # Upright human silhouette check:
            # - Vertical aspect ratio: 1.25 <= aspect_ratio <= 4.2
            # - Substantial height: height_ratio >= 0.18
            # - Substantial area: area_ratio >= 0.025
            if 1.25 <= aspect_ratio <= 4.2 and height_ratio >= 0.18 and area_ratio >= 0.025:
                norm_box = [
                    max(0.0, x / float(w)),
                    max(0.0, y / float(h)),
                    min(1.0, (x + cw) / float(w)),
                    min(1.0, (y + ch) / float(h))
                ]
                conf = self.fixed_confidence if self.fixed_confidence is not None else round(min(0.95, max(0.68, 0.72 + (aspect_ratio - 1.25) * 0.07)), 2)
                detections.append(Detection(
                    box=norm_box,
                    confidence=conf,
                    class_id=0,
                    label="person",
                    raw_label="person"
                ))
        return detections


def get_detector(engine: str = "mock", model_path: Optional[str] = None, **kwargs) -> BaseDetector:
    """Factory helper to instantiate appropriate computer vision detector."""
    if engine.lower() in ("onnx", "opencv", "rfdetr"):
        from vyzn.ai.onnx_detector import ONNXDetector
        return ONNXDetector(model_path=model_path, **kwargs)
    elif engine.lower() in ("yolo", "yolov8", "ultralytics"):
        return YOLOv8Detector(model_name=model_path or "yolov8n.pt", **kwargs)
    else:
        return MockDetector(**kwargs)


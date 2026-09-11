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


@dataclass
class Detection:
    box: List[float]       # [x1, y1, x2, y2] normalized to 0.0 - 1.0
    confidence: float      # 0.0 to 1.0
    class_id: int          # COCO class id (0 = person)
    label: str             # 'person', 'vehicle', 'animal'


class BaseDetector(ABC):
    """Abstract interface for all computer vision detectors."""

    @abstractmethod
    def detect(self, frame: np.ndarray) -> List[Detection]:
        """Runs inference on a single BGR image."""
        pass


class YOLOv8Detector(BaseDetector):
    """
    Ultralytics YOLOv8 implementation for local development and Phase 1 testing.
    Can be swapped seamlessly for RF-DETR (Apache 2.0) via BaseDetector.
    """

    COCO_MAP = {
        0: ("person", "person"),
        2: ("car", "vehicle"),
        3: ("motorcycle", "vehicle"),
        5: ("bus", "vehicle"),
        7: ("truck", "vehicle"),
        15: ("cat", "animal"),
        16: ("dog", "animal"),
    }

    def __init__(self, model_name: str = "yolov8n.pt", conf_thresh: float = 0.25):
        from ultralytics import YOLO
        logger.info(f"Loading YOLO model: {model_name}")
        self.model = YOLO(model_name)
        self.conf_thresh = conf_thresh

    def detect(self, frame: np.ndarray) -> List[Detection]:
        h, w = frame.shape[:2]
        results = self.model(frame, conf=self.conf_thresh, verbose=False)
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
                        label=category
                    ))

        return detections


class MockDetector(BaseDetector):
    """
    Fast deterministic detector for unit tests and synthetic feeds.
    Detects person if frame contains dark rectangular areas.
    """

    def __init__(self, fixed_confidence: float = 0.85):
        self.fixed_confidence = fixed_confidence

    def detect(self, frame: np.ndarray) -> List[Detection]:
        # Fast color/brightness heuristic to mock person detection on synthetic frames
        h, w = frame.shape[:2]
        gray = cv2_gray = np.mean(frame, axis=2).astype(np.uint8) if len(frame.shape) == 3 else frame
        dark_pixels = np.count_nonzero(cv2_gray < 80)
        ratio = dark_pixels / float(h * w)

        if ratio > 0.02:
            return [Detection(
                box=[0.3, 0.2, 0.7, 0.8],
                confidence=self.fixed_confidence,
                class_id=0,
                label="person"
            )]
        return []


def get_detector(engine: str = "mock", model_path: Optional[str] = None, **kwargs) -> BaseDetector:
    """Factory helper to instantiate appropriate computer vision detector."""
    if engine.lower() in ("onnx", "opencv", "rfdetr"):
        from vyzn.ai.onnx_detector import ONNXDetector
        return ONNXDetector(model_path=model_path, **kwargs)
    elif engine.lower() in ("yolo", "yolov8", "ultralytics"):
        return YOLOv8Detector(model_name=model_path or "yolov8n.pt", **kwargs)
    else:
        return MockDetector(**kwargs)


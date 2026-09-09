"""
Pure NumPy lightweight IoU Tracker with 30-frame occlusion coasting.
Replaces fragile centroid matching without requiring deep learning Re-ID overhead.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional
import numpy as np
from vyzn.ai.detector import Detection


@dataclass
class Track:
    track_id: int
    box: List[float]       # [x1, y1, x2, y2]
    label: str
    confidence: float
    start_time: float
    last_seen_time: float
    frames_seen: int = 1
    missed_frames: int = 0

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.last_seen_time - self.start_time)


def calculate_iou(boxA: List[float], boxB: List[float]) -> float:
    """Computes Intersection over Union between two normalized [x1, y1, x2, y2] boxes."""
    xA = max(boxA[0], boxB[0])
    yA = max(boxA[1], boxB[1])
    xB = min(boxA[2], boxB[2])
    yB = min(boxA[3], boxB[3])

    inter_w = max(0.0, xB - xA)
    inter_h = max(0.0, yB - yA)
    inter_area = inter_w * inter_h

    boxA_area = max(0.0, (boxA[2] - boxA[0]) * (boxA[3] - boxA[1]))
    boxB_area = max(0.0, (boxB[2] - boxB[0]) * (boxB[3] - boxB[1]))

    union_area = boxA_area + boxB_area - inter_area
    if union_area <= 0.0:
        return 0.0

    return inter_area / union_area


class IOUTracker:
    """
    Lightweight tracker maintaining track continuity across brief occlusions.
    Coasting window (max_missed_frames = 30) prevents ID splits when subjects walk behind shelves.
    """

    def __init__(self, iou_threshold: float = 0.3, max_missed_frames: int = 30):
        self.iou_threshold = iou_threshold
        self.max_missed_frames = max_missed_frames
        self.next_track_id = 1
        self.tracks: Dict[int, Track] = {}

    def update(self, detections: List[Detection], timestamp: Optional[float] = None) -> List[Track]:
        now = timestamp or time.monotonic()

        if not self.tracks:
            for det in detections:
                self.tracks[self.next_track_id] = Track(
                    track_id=self.next_track_id,
                    box=det.box,
                    label=det.label,
                    confidence=det.confidence,
                    start_time=now,
                    last_seen_time=now,
                    frames_seen=1,
                    missed_frames=0
                )
                self.next_track_id += 1
            return list(self.tracks.values())

        track_ids = list(self.tracks.keys())
        unmatched_tracks = set(track_ids)
        unmatched_detections = set(range(len(detections)))

        if detections and track_ids:
            # Build IoU matrix
            iou_matrix = np.zeros((len(track_ids), len(detections)), dtype=np.float32)
            for i, tid in enumerate(track_ids):
                for j, det in enumerate(detections):
                    if self.tracks[tid].label == det.label:
                        iou_matrix[i, j] = calculate_iou(self.tracks[tid].box, det.box)

            # Greedy matching
            while True:
                max_val = np.max(iou_matrix) if iou_matrix.size > 0 else 0.0
                if max_val < self.iou_threshold:
                    break

                i, j = np.unravel_index(np.argmax(iou_matrix), iou_matrix.shape)
                tid = track_ids[i]
                det = detections[j]

                # Update matched track
                t = self.tracks[tid]
                t.box = det.box
                t.confidence = det.confidence
                t.last_seen_time = now
                t.frames_seen += 1
                t.missed_frames = 0

                unmatched_tracks.discard(tid)
                unmatched_detections.discard(j)

                # Invalidate matched row and col
                iou_matrix[i, :] = -1.0
                iou_matrix[:, j] = -1.0

        # Handle unmatched tracks (coasting)
        dead_tracks = []
        for tid in unmatched_tracks:
            t = self.tracks[tid]
            t.missed_frames += 1
            if t.missed_frames > self.max_missed_frames:
                dead_tracks.append(tid)

        for tid in dead_tracks:
            del self.tracks[tid]

        # Initialize new tracks for unmatched detections
        for j in unmatched_detections:
            det = detections[j]
            self.tracks[self.next_track_id] = Track(
                track_id=self.next_track_id,
                box=det.box,
                label=det.label,
                confidence=det.confidence,
                start_time=now,
                last_seen_time=now,
                frames_seen=1,
                missed_frames=0
            )
            self.next_track_id += 1

        # Return only currently active (not missed in this frame) tracks for alert evaluation
        return [t for t in self.tracks.values() if t.missed_frames == 0]

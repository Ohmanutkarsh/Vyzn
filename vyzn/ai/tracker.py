"""
Pure NumPy lightweight IoU Tracker with 30-frame occlusion coasting.
Replaces fragile centroid matching without requiring deep learning Re-ID overhead.
Supports trajectory logging, stationary hold tracking, and direction analysis.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
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
    trajectory: List[Tuple[float, float, float]] = field(default_factory=list) # [(t, cx, cy), ...]
    stationary_since: Optional[float] = None
    is_stationary: bool = False
    hits: int = 1          # actual detection frames (excludes coasted)
    c_mean: float = 0.0    # exponential moving average of detection confidence
    c_var: float = 0.0     # EMA variance
    c_std: float = 0.0     # running std dev of detection confidence
    id_switch_count: int = 0  # times merged with a lost fragment

    def __post_init__(self):
        if self.c_mean == 0.0 and self.confidence > 0.0:
            self.c_mean = float(self.confidence)

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.last_seen_time - self.start_time)

    @property
    def bbox_height_ratio(self) -> float:
        return max(0.0, min(1.0, float(self.box[3] - self.box[1])))

    @property
    def centroid(self) -> Tuple[float, float]:
        cx = (self.box[0] + self.box[2]) / 2.0
        cy = (self.box[1] + self.box[3]) / 2.0
        return cx, cy

    def record_hit(self, det: Detection, now: float):
        """Updates track state when a detection is matched."""
        old_cx, old_cy = self.centroid
        self.box = det.box
        self.confidence = det.confidence
        self.last_seen_time = now
        self.frames_seen += 1
        self.hits += 1
        self.missed_frames = 0

        # Exponential moving average and variance for confidence
        alpha = 0.25
        diff = det.confidence - self.c_mean
        self.c_mean = float(self.c_mean + alpha * diff)
        self.c_var = float((1.0 - alpha) * (self.c_var + alpha * (diff ** 2)))
        self.c_std = float(np.sqrt(max(0.0, self.c_var)))

        new_cx, new_cy = self.centroid
        self.trajectory.append((now, new_cx, new_cy))
        if len(self.trajectory) > 200:
            self.trajectory = self.trajectory[-200:]

        movement = np.sqrt((new_cx - old_cx) ** 2 + (new_cy - old_cy) ** 2)
        if movement < 0.015:
            if not self.is_stationary:
                self.is_stationary = True
                self.stationary_since = now
        else:
            self.is_stationary = False
            self.stationary_since = None

    def get_travel_direction(self) -> str:
        """Determines primary direction of movement based on trajectory."""
        if len(self.trajectory) < 2:
            return "stationary"
        first = self.trajectory[0]
        last = self.trajectory[-1]
        dx = last[1] - first[1]
        dy = last[2] - first[2]
        dist = np.sqrt(dx * dx + dy * dy)
        if dist < 0.05:
            return "stationary"
        if abs(dx) > abs(dy):
            return "left to right" if dx > 0 else "right to left"
        else:
            return "top to bottom" if dy > 0 else "bottom to top"

    def get_stationary_duration(self, current_time: float) -> float:
        if not self.is_stationary or self.stationary_since is None:
            return 0.0
        return max(0.0, current_time - self.stationary_since)


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
    Two-stage IoU Tracker with time-based occlusion coasting and trajectory Re-ID merge.
    Stage 1 matches high-confidence detections (>= 0.40) to active tracks using IoU >= 0.3.
    Stage 2 matches remaining detections to coasting tracks using IoU >= 0.2.
    Trajectory Re-ID merges lost tracks within 3.0s and 0.1 frame-width to eliminate fragmentations.
    """

    def __init__(
        self,
        iou_threshold: float = 0.3,
        max_missed_frames: Optional[int] = None,
        fps: float = 4.0,
        new_track_thresh: float = 0.40,
        second_match_iou: float = 0.20,
        track_buffer_sec: float = 5.0,
        reid_merge_window_sec: float = 3.0,
        reid_merge_dist_ratio: float = 0.10,
    ):
        self.iou_threshold = iou_threshold
        self.second_match_iou = second_match_iou
        self.fps = fps
        self.track_buffer_sec = track_buffer_sec
        self.max_missed_frames = (
            max_missed_frames if max_missed_frames is not None else int(track_buffer_sec * fps)
        )
        self.new_track_thresh = new_track_thresh
        self.reid_merge_window_sec = reid_merge_window_sec
        self.reid_merge_dist_ratio = reid_merge_dist_ratio
        self.next_track_id = 1
        self.tracks: Dict[int, Track] = {}
        self.lost_tracks: List[Track] = []

    def get_alive_tracks(self, max_missed_seconds: float = 5.0, current_time: Optional[float] = None) -> List[Track]:
        """Returns all tracks that are currently active or coasting within tolerance."""
        now = current_time or time.monotonic()
        alive = []
        for t in self.tracks.values():
            if now - t.last_seen_time <= max_missed_seconds:
                alive.append(t)
        return alive

    def clear(self):
        """Resets all track memory."""
        self.tracks.clear()
        self.lost_tracks.clear()
        self.next_track_id = 1

    def _match_detections_to_tracks(
        self,
        det_indices: List[int],
        track_ids: List[int],
        detections: List[Detection],
        min_iou: float
    ) -> Tuple[List[Tuple[int, int]], List[int], List[int]]:
        """Greedy matching between detection indices and track IDs."""
        if not det_indices or not track_ids:
            return [], track_ids, det_indices

        iou_matrix = np.zeros((len(track_ids), len(det_indices)), dtype=np.float32)
        for i, tid in enumerate(track_ids):
            for j, d_idx in enumerate(det_indices):
                if self.tracks[tid].label == detections[d_idx].label:
                    iou_matrix[i, j] = calculate_iou(self.tracks[tid].box, detections[d_idx].box)

        matched_pairs = []
        unmatched_tracks = set(track_ids)
        unmatched_dets = set(det_indices)

        while True:
            max_val = np.max(iou_matrix) if iou_matrix.size > 0 else 0.0
            if max_val < min_iou:
                break
            i, j = np.unravel_index(np.argmax(iou_matrix), iou_matrix.shape)
            tid = track_ids[i]
            d_idx = det_indices[j]
            matched_pairs.append((tid, d_idx))
            unmatched_tracks.discard(tid)
            unmatched_dets.discard(d_idx)
            iou_matrix[i, :] = -1.0
            iou_matrix[:, j] = -1.0

        return matched_pairs, list(unmatched_tracks), list(unmatched_dets)

    def update(self, detections: List[Detection], timestamp: Optional[float] = None) -> List[Track]:
        now = timestamp if timestamp is not None else time.monotonic()

        # Split detections into high confidence (>= new_track_thresh) and lower confidence
        high_det_indices = [i for i, d in enumerate(detections) if d.confidence >= self.new_track_thresh]
        low_det_indices = [i for i, d in enumerate(detections) if d.confidence < self.new_track_thresh]

        track_ids = list(self.tracks.keys())

        # Stage 1: Match high-confidence detections with active tracks using iou_threshold (0.3)
        stage1_matches, unmatched_tids, unmatched_high_dets = self._match_detections_to_tracks(
            high_det_indices, track_ids, detections, self.iou_threshold
        )

        for tid, d_idx in stage1_matches:
            self.tracks[tid].record_hit(detections[d_idx], now)

        # Stage 2: Match remaining detections (low + unmatched high) with remaining tracks using second_match_iou (0.2)
        remaining_dets = unmatched_high_dets + low_det_indices
        stage2_matches, final_unmatched_tids, final_unmatched_dets = self._match_detections_to_tracks(
            remaining_dets, unmatched_tids, detections, self.second_match_iou
        )

        for tid, d_idx in stage2_matches:
            self.tracks[tid].record_hit(detections[d_idx], now)

        # Update unmatched tracks (increment missed_frames)
        dead_tracks = []
        for tid in final_unmatched_tids:
            t = self.tracks[tid]
            t.missed_frames += 1
            if t.missed_frames > self.max_missed_frames:
                dead_tracks.append(tid)

        for tid in dead_tracks:
            lost = self.tracks.pop(tid)
            self.lost_tracks.append(lost)

        # Clean up lost tracks older than reid_merge_window_sec
        self.lost_tracks = [
            lt for lt in self.lost_tracks if (now - lt.last_seen_time) <= self.reid_merge_window_sec
        ]

        # For unmatched high-confidence detections, attempt trajectory Re-ID merge with recently lost tracks
        unmatched_high_remaining = [
            idx for idx in final_unmatched_dets if detections[idx].confidence >= self.new_track_thresh
        ]

        for d_idx in unmatched_high_remaining:
            det = detections[d_idx]
            det_cx = (det.box[0] + det.box[2]) / 2.0
            det_cy = (det.box[1] + det.box[3]) / 2.0

            best_lost_idx = -1
            best_dist = float("inf")
            for idx, lt in enumerate(self.lost_tracks):
                if lt.label != det.label:
                    continue
                if (now - lt.last_seen_time) > self.reid_merge_window_sec:
                    continue
                lt_cx, lt_cy = lt.centroid
                dist = np.sqrt((det_cx - lt_cx) ** 2 + (det_cy - lt_cy) ** 2)
                if dist <= self.reid_merge_dist_ratio and dist < best_dist:
                    best_dist = dist
                    best_lost_idx = idx

            if best_lost_idx >= 0:
                # Merge into lost track
                lt = self.lost_tracks.pop(best_lost_idx)
                lt.id_switch_count += 1
                lt.record_hit(det, now)
                self.tracks[lt.track_id] = lt
            else:
                # Create new track
                self.tracks[self.next_track_id] = Track(
                    track_id=self.next_track_id,
                    box=det.box,
                    label=det.label,
                    confidence=det.confidence,
                    start_time=now,
                    last_seen_time=now,
                    frames_seen=1,
                    missed_frames=0,
                    trajectory=[(now, det_cx, det_cy)],
                    hits=1,
                    c_mean=float(det.confidence),
                    c_var=0.0,
                    c_std=0.0,
                    id_switch_count=0,
                )
                self.next_track_id += 1

        # Return only currently active (detected this frame) tracks
        return [t for t in self.tracks.values() if t.missed_frames == 0]

"""
Event schemas and data structures matching the SQLite contract.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any


@dataclass
class EventRecord:
    event_group_id: str
    camera_id: str
    start_time: str                     # ISO 8601 UTC string
    end_time: Optional[str] = None      # ISO 8601 UTC string
    object_type: str = "unclassified"   # 'person' | 'vehicle' | 'animal' | 'unclassified'
    confidence: float = 0.0             # 0.0 to 1.0
    score: int = 0                      # 0 to 100
    status: str = "raw"                 # 'raw' | 'compressed' | 'deleted'
    starred: int = 0                    # 0 or 1
    synced: int = 0                     # 0 or 1
    user_triage: str = "unreviewed"     # 'unreviewed' | 'confirmed_threat' | 'false_positive'
    file_path: str = ""                 # Path to .mp4
    thumb_path: str = ""                # Path to .jpg
    dominant_color: str = "unspecified" # 'red' | 'blue' | 'black' | 'white' | etc.
    zone_name: str = "general"          # Intersected zone or 'general'
    location_id: str = "loc_primary"    # Associated property location
    duration_sec: float = 0.0           # Event duration in seconds
    motion_points_count: int = 0        # Count of distinct motion occurrences
    metadata_json: str = "{}"           # Additional forensic and detection metadata
    clip_number: Optional[int] = None   # Monotonically increasing human-readable clip ID
    expires_at_ms: Optional[int] = None # 72-hour hard purge epoch millisecond
    sha256: Optional[str] = None        # SHA-256 integrity hash of media clip
    tier: str = "review"                # 'alert' | 'review'

    @property
    def event_id(self) -> str:
        return self.event_group_id

    def to_dict(self) -> Dict[str, Any]:
        return {
            "event_group_id": self.event_group_id,
            "camera_id": self.camera_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "object_type": self.object_type,
            "confidence": self.confidence,
            "score": self.score,
            "status": self.status,
            "starred": self.starred,
            "synced": self.synced,
            "user_triage": self.user_triage,
            "file_path": self.file_path,
            "thumb_path": self.thumb_path,
            "dominant_color": self.dominant_color,
            "zone_name": self.zone_name,
            "location_id": self.location_id,
            "duration_sec": self.duration_sec,
            "motion_points_count": self.motion_points_count,
            "metadata_json": self.metadata_json,
            "clip_number": self.clip_number,
            "expires_at_ms": self.expires_at_ms,
            "sha256": self.sha256,
            "tier": self.tier,
        }



@dataclass
class DetectionCandidate:
    camera_id: str
    object_type: str
    confidence: float
    motion_ratio: float
    track_duration_sec: float
    bounding_box: List[float]           # [x1, y1, x2, y2] normalized 0.0-1.0
    is_after_hours: bool
    is_in_restricted_zone: bool
    is_night_ir: bool = False
    zone_name: str = "general"
    matched_area_id: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass
class TelemetryData:
    site_id: str
    timestamp_utc: str
    uptime_sec: float
    cpu_temp_c: Optional[float]
    cpu_usage_pct: float
    ram_used_mb: float
    disk_free_pct: float
    active_cameras: int
    queue_depth: int
    unacknowledged_alerts: int = 0

"""
Configuration management for VYZN edge node.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class ZonePolygon(BaseModel):
    name: str = "restricted_zone"
    # List of normalized [x, y] coordinates in range 0.0 to 1.0
    points: List[List[float]] = Field(default_factory=list)


class WatchAreaConfig(BaseModel):
    # In simple terms: configuration for a user-drawn watch area polygon
    id: str
    camera_id: str
    name: str = "Area 1"
    polygon: List[List[float]] = Field(default_factory=list)  # Normalized [[x, y], ...]
    # response can be 'alert' (send notifications), 'review' (save clip silently), or 'ignore' (exclude/mask motion)
    response: str = "alert"  # 'alert' | 'review' | 'ignore'
    min_stay_seconds: int = 0  # 0 | 10 | 30 | 60
    schedule: str = "always"  # 'always' | 'outside_shop_hours'
    version: int = 1


class BusinessHours(BaseModel):
    enabled: bool = True
    start_hour: int = 9   # 09:00 (9 AM)
    start_minute: int = 0
    end_hour: int = 21    # 21:00 (9 PM)
    end_minute: int = 0


class ClipConfig(BaseModel):
    score_interval_seconds: float = 3.0
    active_score_threshold: int = 30
    quiet_gap_seconds: float = 90.0
    pre_roll_seconds: float = 10.0
    post_roll_seconds: float = 10.0
    min_active_ticks: int = 1
    max_clip_seconds: float = 600.0
    preview_seconds: float = 6.0


class LocationConfig(BaseModel):
    location_id: str
    name: str
    address: Optional[str] = ""
    owner_email: Optional[str] = None


class CameraConfig(BaseModel):
    camera_id: str
    name: str
    rtsp_url: str
    enabled: bool = True
    location_id: Optional[str] = "loc_primary"
    target_fps: float = 20.0
    capture_fps: float = 20.0
    ai_inference_fps: float = 20.0
    downscale_width: int = 854
    downscale_height: int = 480
    is_night_ir: bool = False
    owner_email: Optional[str] = None
    business_hours: BusinessHours = Field(default_factory=BusinessHours)
    restricted_zones: List[ZonePolygon] = Field(default_factory=list)
    privacy_zones: List[ZonePolygon] = Field(default_factory=list)
    watch_areas: List[WatchAreaConfig] = Field(default_factory=list)

    # Per-camera lifecycle and motion overrides
    osd_exclude_polygon: Optional[List[List[float]]] = None  # Normalized [[x,y],...] or None
    start_motion_threshold: Optional[float] = None
    continue_motion_threshold: Optional[float] = None
    pre_roll_sec: Optional[float] = None
    post_roll_sec: Optional[float] = None
    merge_gap_sec: Optional[float] = None
    max_clip_duration_sec: Optional[float] = None


class EdgeSettings(BaseSettings):
    site_id: str = "site_local_default"
    site_name: str = "Local Edge Deployment"
    data_dir: Path = Path("./data/clips")
    db_path: Path = Path("./data/clips/index.db")

    # Scoring & Thresholds
    alert_score_threshold: int = 85
    motion_gate_threshold: float = 0.005  # 0.5% frame change
    day_conf_min: float = 0.35
    night_conf_min: float = 0.25

    # Storage & Retention & Clipping
    raw_retention_hours: int = 72
    disk_safety_threshold_pct: float = 85.0
    max_storage_quota_gb: float = 20.0
    pre_roll_sec: float = 10.0
    post_roll_sec: float = 10.0
    event_inactivity_gap_sec: float = 90.0
    clip: ClipConfig = Field(default_factory=ClipConfig)

    # Explicit State Machine & Motion Gate Parameters (Step 1, 2, 5)
    confirm_window_frames: int = 5
    confirm_frames: int = 3
    start_motion_threshold: float = 0.010       # 1.0% of ROI
    continue_motion_threshold: float = 0.003    # 0.3% of ROI
    min_contour_area_ratio: float = 0.004       # 0.4% of ROI
    min_motion_only_seconds: float = 3.0        # Discard clips without detection shorter than 3s
    merge_gap_sec: float = 90.0                 # 90s debounce merge window
    max_clip_duration_sec: float = 600.0        # 600s max clip duration before linked split
    track_lost_tolerance_sec: float = 5.0       # Keep coasting tracks alive up to 5s
    stationary_hold_max_sec: float = 60.0       # Max stationary duration before static_object_timeout
    stream_gap_tolerance_sec: float = 5.0       # Tolerate brief stream reconnect gap
    warmup_frames: int = 150                    # Suppress triggers during initial MOG2 background seeding
    global_change_ratio: float = 0.60           # Reject auto-exposure/IR switch global spikes
    mog2_learning_rate: float = 0.004           # Slow background update rate to avoid fast absorption
    yolo_conf_start: float = 0.35
    yolo_conf_continue: float = 0.25
    enable_vlm_description: bool = False

    # Telemetry & Observability
    telemetry_interval_sec: int = 60
    cloud_webhook_url: Optional[str] = None
    cloud_auth_token: Optional[str] = None

    # Alerts
    telegram_bot_token: Optional[str] = None
    telegram_bot_username: Optional[str] = "Vyzn_security_bot"
    telegram_chat_id: Optional[str] = None
    telegram_webhook_secret: Optional[str] = None
    internal_alert_token: Optional[str] = None

    # Cameras
    cameras: List[CameraConfig] = Field(default_factory=list)

    class Config:
        env_prefix = "VYZN_"
        env_nested_delimiter = "__"
        arbitrary_types_allowed = True


def get_default_settings(data_root: Optional[Path] = None) -> EdgeSettings:
    """Returns default edge settings with safe local directories."""
    # In simple terms: check if the user configured a custom storage folder in Settings
    if not data_root:
        storage_cfg = Path("./config/storage.json")
        if storage_cfg.exists():
            try:
                import json
                with open(storage_cfg, "r") as f:
                    cfg_data = json.load(f)
                    if cfg_data.get("storage_dir"):
                        cand = Path(cfg_data["storage_dir"])
                        try:
                            cand.mkdir(parents=True, exist_ok=True)
                            data_root = cand
                        except Exception:
                            pass
            except Exception:
                pass

    root = data_root or Path("./data/clips")
    return EdgeSettings(
        data_dir=root,
        db_path=root / "index.db"
    )


_SCORING_CONFIG_CACHE: Optional[dict] = None


def get_scoring_config(reload: bool = False) -> dict:
    """Loads and caches scoring parameters from config/scoring.json."""
    global _SCORING_CONFIG_CACHE
    if _SCORING_CONFIG_CACHE is not None and not reload:
        return _SCORING_CONFIG_CACHE

    possible_paths = [
        Path("config/scoring.json"),
        Path(__file__).resolve().parent.parent.parent / "config" / "scoring.json",
        Path(__file__).resolve().parent.parent / "config" / "scoring.json",
    ]
    for p in possible_paths:
        if p.exists():
            try:
                import json
                with open(p, "r", encoding="utf-8") as f:
                    _SCORING_CONFIG_CACHE = json.load(f)
                    return _SCORING_CONFIG_CACHE
            except Exception:
                pass
    return {}


_CLIP_CONFIG_CACHE: Optional[ClipConfig] = None


def get_clip_config(reload: bool = False) -> ClipConfig:
    """Loads and caches clip state machine parameters from config/config.json."""
    global _CLIP_CONFIG_CACHE
    if _CLIP_CONFIG_CACHE is not None and not reload:
        return _CLIP_CONFIG_CACHE

    possible_paths = [
        Path("config/config.json"),
        Path(__file__).resolve().parent.parent.parent / "config" / "config.json",
        Path(__file__).resolve().parent.parent / "config" / "config.json",
    ]
    for p in possible_paths:
        if p.exists():
            try:
                import json
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    clip_data = data.get("clip", {})
                    _CLIP_CONFIG_CACHE = ClipConfig(**clip_data)
                    return _CLIP_CONFIG_CACHE
            except Exception:
                pass
    _CLIP_CONFIG_CACHE = ClipConfig()
    return _CLIP_CONFIG_CACHE



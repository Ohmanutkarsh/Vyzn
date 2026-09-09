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


class BusinessHours(BaseModel):
    enabled: bool = True
    start_hour: int = 9   # 09:00 (9 AM)
    start_minute: int = 0
    end_hour: int = 21    # 21:00 (9 PM)
    end_minute: int = 0


class CameraConfig(BaseModel):
    camera_id: str
    name: str
    rtsp_url: str
    enabled: bool = True
    target_fps: float = 4.0
    downscale_width: int = 640
    downscale_height: int = 360
    is_night_ir: bool = False
    business_hours: BusinessHours = Field(default_factory=BusinessHours)
    restricted_zones: List[ZonePolygon] = Field(default_factory=list)


class EdgeSettings(BaseSettings):
    site_id: str = "site_local_default"
    site_name: str = "Local Edge Deployment"
    data_dir: Path = Path("./data/clips")
    db_path: Path = Path("./data/clips/index.db")

    # Scoring & Thresholds
    alert_score_threshold: int = 70
    motion_gate_threshold: float = 0.005  # 0.5% frame change
    day_conf_min: float = 0.35
    night_conf_min: float = 0.25

    # Storage & Retention
    raw_retention_hours: int = 72
    disk_safety_threshold_pct: float = 85.0

    # Telemetry & Observability
    telemetry_interval_sec: int = 60
    cloud_webhook_url: Optional[str] = None
    cloud_auth_token: Optional[str] = None

    # Alerts
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None

    # Cameras
    cameras: List[CameraConfig] = Field(default_factory=list)

    class Config:
        env_prefix = "VYZN_"
        env_nested_delimiter = "__"
        arbitrary_types_allowed = True


def get_default_settings(data_root: Optional[Path] = None) -> EdgeSettings:
    """Returns default edge settings with safe local directories."""
    root = data_root or Path("./data/clips")
    return EdgeSettings(
        data_dir=root,
        db_path=root / "index.db"
    )

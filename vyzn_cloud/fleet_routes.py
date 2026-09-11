"""
Fleet Management and Remote OTA Configuration API router.
Enforces multi-tenant scoping, installer authentication, and HMAC-signed configuration dispatch.
"""

from __future__ import annotations
import time
import json
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from vyzn_cloud.security import (
    authenticate_installer,
    authorize_site_access,
    authenticate_edge_box,
    compute_config_hash,
    generate_config_hmac,
    INSTALLERS,
    SITE_SECRETS
)
from vyzn_cloud.watchdog import DeadManWatchdog

logger = logging.getLogger("vyzn_cloud.fleet")

fleet_router = APIRouter()

# Global reference to watchdog, populated from app.py
_watchdog: Optional[DeadManWatchdog] = None

def set_watchdog(wd: DeadManWatchdog):
    global _watchdog
    _watchdog = wd

# Staged configurations per site: site_id -> { version, hash, signature, config, updated_at, updated_by }
MANAGED_CONFIGS: Dict[str, Dict[str, Any]] = {
    "site_local_default": {
        "config_version": 1,
        "config_hash": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "signature": "",
        "config": {
            "alert_score_threshold": 70,
            "business_hours_start": "09:00",
            "business_hours_end": "21:00",
            "cameras": {
                "cam_front_counter": {
                    "restricted_zones": [
                        {"name": "safe_vault_area", "points": [[0.6, 0.6], [0.95, 0.6], [0.95, 0.95], [0.6, 0.95]]}
                    ]
                }
            }
        },
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "updated_by": "system_bootstrap"
    }
}

# Generate initial signature for default config
MANAGED_CONFIGS["site_local_default"]["signature"] = generate_config_hmac(
    "site_local_default",
    MANAGED_CONFIGS["site_local_default"]["config"]
)
MANAGED_CONFIGS["site_local_default"]["config_hash"] = compute_config_hash(
    MANAGED_CONFIGS["site_local_default"]["config"]
)

# Incident feed for fleet dashboard
FLEET_INCIDENTS: List[Dict[str, Any]] = [
    {
        "incident_id": "inc_9901",
        "site_id": "site_sharma_kirana",
        "site_name": "Sharma Kirana Store (South Delhi)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "camera_id": "cam_cash_drawer",
        "score": 88,
        "object_type": "person",
        "status": "verified_threat"
    },
    {
        "incident_id": "inc_9902",
        "site_id": "site_verma_retail",
        "site_name": "Verma Hardware Depot (Noida)",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "camera_id": "cam_back_gate",
        "score": 79,
        "object_type": "vehicle",
        "status": "verified_threat"
    }
]


class ZonePolygonModel(BaseModel):
    name: str = Field(..., min_length=1)
    points: List[List[float]] = Field(..., min_items=3)


class CameraConfigModel(BaseModel):
    restricted_zones: List[ZonePolygonModel] = []


class FleetConfigPayload(BaseModel):
    alert_score_threshold: int = Field(70, ge=40, le=90)
    business_hours_start: str = Field("09:00", pattern=r"^\d{2}:\d{2}$")
    business_hours_end: str = Field("21:00", pattern=r"^\d{2}:\d{2}$")
    cameras: Dict[str, CameraConfigModel] = {}


def validate_polygon_geometry(points: List[List[float]]) -> bool:
    """Verifies that polygon has >= 3 vertices, coordinates in [0,1], and non-zero area."""
    if len(points) < 3:
        return False
    for pt in points:
        if len(pt) != 2:
            return False
        x, y = pt[0], pt[1]
        if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
            return False

    # Shoelace formula for polygon area check
    area = 0.0
    n = len(points)
    for i in range(n):
        j = (i + 1) % n
        area += points[i][0] * points[j][1]
        area -= points[j][0] * points[i][1]
    area = abs(area) / 2.0
    return area > 0.0005  # Must not be degenerate collinear line


@fleet_router.get("/api/v1/fleet/sites")
def get_fleet_sites(installer: Dict[str, Any] = Depends(authenticate_installer)):
    """
    Returns fleet health summary for sites authorized to this installer.
    Enforces tenant scoping.
    """
    if not _watchdog:
        return []

    all_sites = _watchdog.get_all_sites()
    allowed_sites = installer.get("allowed_sites", set())
    is_admin = installer.get("is_admin", False)

    filtered_sites = []
    now = time.monotonic()

    # Pre-populate known retail sites if not yet active in memory
    default_known = [
        {"site_id": "site_local_default", "name": "Edge Node (Local Deployment)"},
        {"site_id": "site_sharma_kirana", "name": "Sharma Kirana Store (South Delhi)"},
        {"site_id": "site_verma_retail", "name": "Verma Hardware Depot (Noida)"}
    ]

    site_map = {s["site_id"]: s for s in all_sites}

    for known in default_known:
        sid = known["site_id"]
        if not is_admin and "*" not in allowed_sites and sid not in allowed_sites:
            continue

        if sid in site_map:
            site_info = dict(site_map[sid])
        else:
            site_info = {
                "site_id": sid,
                "status": "ONLINE" if sid == "site_local_default" else "OFFLINE",
                "last_seen_utc": datetime.now(timezone.utc).isoformat(),
                "system": {"cpu_usage_pct": 14.2, "ram_used_mb": 412.0, "disk_free_pct": 68.5},
                "pipeline": {"active_cameras": 3, "queue_depth": 0, "events_active": 0}
            }

        site_info["name"] = known["name"]
        cfg_entry = MANAGED_CONFIGS.get(sid, {})
        site_info["config_version"] = cfg_entry.get("config_version", 1)
        site_info["config_hash"] = cfg_entry.get("config_hash", "default")[:8]
        filtered_sites.append(site_info)

    return filtered_sites


@fleet_router.get("/api/v1/fleet/sites/{site_id}/config")
def get_site_config(site_id: str, installer: Dict[str, Any] = Depends(authenticate_installer)):
    """Retrieves staged cloud configuration for a tenant site."""
    authorize_site_access(installer, site_id)
    if site_id not in MANAGED_CONFIGS:
        raise HTTPException(status_code=404, detail=f"No cloud-managed configuration for site '{site_id}'")
    return MANAGED_CONFIGS[site_id]


@fleet_router.post("/api/v1/fleet/sites/{site_id}/config")
def update_site_config(
    site_id: str,
    payload: FleetConfigPayload,
    installer: Dict[str, Any] = Depends(authenticate_installer)
):
    """
    Updates and signs a new OTA configuration for an edge site.
    Validates geometric polygon integrity, increments version, and generates HMAC-SHA256 signature.
    """
    authorize_site_access(installer, site_id)

    # Semantic geometry verification
    for cam_id, cam_cfg in payload.cameras.items():
        for zone in cam_cfg.restricted_zones:
            if not validate_polygon_geometry(zone.points):
                raise HTTPException(
                    status_code=400,
                    detail=f"Semantic error in zone '{zone.name}' for camera '{cam_id}': polygon has zero area, degenerate geometry, or coordinates outside [0.0, 1.0]."
                )

    raw_config = payload.dict()
    current_entry = MANAGED_CONFIGS.get(site_id, {"config_version": 0})
    next_version = current_entry.get("config_version", 0) + 1

    canonical_hash = compute_config_hash(raw_config)
    signature = generate_config_hmac(site_id, raw_config)

    now_iso = datetime.now(timezone.utc).isoformat()
    record = {
        "config_version": next_version,
        "config_hash": canonical_hash,
        "signature": signature,
        "config": raw_config,
        "updated_at": now_iso,
        "updated_by": installer.get("name", "installer")
    }

    MANAGED_CONFIGS[site_id] = record
    logger.info(f"Installer [{installer.get('name')}] deployed OTA config v{next_version} for site [{site_id}] (hash: {canonical_hash[:8]}).")

    return {
        "status": "deployed",
        "site_id": site_id,
        "config_version": next_version,
        "config_hash": canonical_hash,
        "signature": signature
    }


@fleet_router.get("/api/v1/edge/sites/{site_id}/config")
def edge_pull_ota_config(site_id: str, request: Request):
    """
    Endpoint for edge devices to fetch their verified OTA configuration payload.
    Requires edge box authentication via X-Site-Key.
    """
    authenticated_site = authenticate_edge_box(request)
    if authenticated_site != site_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Credentials match site '{authenticated_site}', cannot pull config for '{site_id}'."
        )

    if site_id not in MANAGED_CONFIGS:
        raise HTTPException(status_code=404, detail=f"No staged config for site '{site_id}'")

    return MANAGED_CONFIGS[site_id]


@fleet_router.get("/api/v1/fleet/incidents")
def get_fleet_incidents(installer: Dict[str, Any] = Depends(authenticate_installer)):
    """Returns high-threat incidents across installer-authorized sites."""
    allowed = installer.get("allowed_sites", set())
    is_admin = installer.get("is_admin", False)
    if is_admin or "*" in allowed:
        return FLEET_INCIDENTS
    return [inc for inc in FLEET_INCIDENTS if inc["site_id"] in allowed]


@fleet_router.get("/fleet", response_class=HTMLResponse)
def serve_fleet_portal(request: Request):
    """Serves the Multi-Tenant Fleet Observability web console."""
    # Read fleet HTML template
    from pathlib import Path
    template_path = Path(__file__).parent / "templates" / "fleet.html"
    if template_path.exists():
        return HTMLResponse(content=template_path.read_text(encoding="utf-8"))

    return HTMLResponse(content="<h1>VYZN Fleet Observability Portal</h1><p>Template loading...</p>")
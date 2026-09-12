"""
Dead-Man Telemetry Watchdog.
Monitors remote edge boxes deployed across retail shops and fires alerts if heartbeats cease.
"""

from __future__ import annotations
import time
import logging
from typing import Dict, Any, List

logger = logging.getLogger("vyzn_cloud.watchdog")


class DeadManWatchdog:
    """
    Maintains heartbeat state for all deployed customer sites.
    Detects dropped connectivity or powered-off edge boxes.
    """

    def __init__(self, silence_threshold_sec: float = 180.0):
        self.silence_threshold_sec = silence_threshold_sec
        self.sites: Dict[str, Dict[str, Any]] = {}

    def record_heartbeat(self, site_id: str, payload: Dict[str, Any], client_host: str = "127.0.0.1"):
        """Records incoming heartbeat from an edge node."""
        now = time.monotonic()
        api_port = payload.get("pipeline", {}).get("api_port") or payload.get("api_port", 8000)
        host = "127.0.0.1" if client_host in ("127.0.0.1", "localhost", "::1", "testclient") else client_host
        edge_url = f"http://{host}:{api_port}"

        self.sites[site_id] = {
            "site_id": site_id,
            "last_seen_monotonic": now,
            "last_seen_utc": payload.get("timestamp"),
            "system": payload.get("system", {}),
            "pipeline": payload.get("pipeline", {}),
            "edge_url": edge_url,
            "client_host": client_host,
            "status": "ONLINE"
        }

    def evaluate_sites(self) -> List[Dict[str, Any]]:
        """
        Evaluates connectivity across all sites.
        Returns list of newly detected offline sites.
        """
        now = time.monotonic()
        offline_alerts = []

        for site_id, site in self.sites.items():
            age = now - site["last_seen_monotonic"]
            if age > self.silence_threshold_sec:
                if site["status"] == "ONLINE":
                    elapsed_str = f"{int(age)}s" if age >= 60 else f"{age:.1f}s"
                    thresh_str = f"{int(self.silence_threshold_sec)}s"
                    offline_alerts.append({
                        "site_id": site_id,
                        "silence_duration_sec": round(age, 1),
                        "message": f"🚨 SITE DOWN ALERT: [{site_id}] has missed heartbeats for {elapsed_str} (configured threshold: {thresh_str})!"
                    })
                    logger.critical(offline_alerts[-1]["message"])
            else:
                site["status"] = "ONLINE"

        return offline_alerts

    def get_all_sites(self) -> List[Dict[str, Any]]:
        """Returns fleet view of all monitored retail locations."""
        self.evaluate_sites()
        return list(self.sites.values())

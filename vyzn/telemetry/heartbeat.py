"""
Remote observability daemon transmitting 60-second JSON telemetry heartbeats.
Enables cloud dead-man watchdog monitoring and remote config synchronization.
"""

from __future__ import annotations
import time
import shutil
import logging
import threading
import psutil
import requests
from datetime import datetime, timezone
from typing import Optional, Dict, Any
from vyzn.core.config import EdgeSettings
from vyzn.core.database import EventDatabase

logger = logging.getLogger("vyzn.telemetry.heartbeat")


class TelemetryHeartbeatDaemon(threading.Thread):
    """
    Periodic heartbeat worker collecting local box metrics and pushing to cloud webhook.
    """

    def __init__(
        self,
        settings: EdgeSettings,
        db: EventDatabase,
        pipeline_status_getter: Any = None
    ):
        super().__init__(name="Telemetry-Heartbeat", daemon=True)
        self.settings = settings
        self.db = db
        self.pipeline_status_getter = pipeline_status_getter
        self.interval_sec = settings.telemetry_interval_sec
        self.running = True
        self.start_time = time.monotonic()

    def run(self):
        logger.info(f"Telemetry heartbeat daemon active (interval: {self.interval_sec}s).")
        while self.running:
            try:
                payload = self.collect_telemetry()
                self.record_and_dispatch(payload)
            except Exception as e:
                logger.error(f"Failed during telemetry heartbeat: {e}")

            for _ in range(self.interval_sec):
                if not self.running:
                    break
                time.sleep(1.0)

    def collect_telemetry(self) -> Dict[str, Any]:
        """Gathers system and camera pipeline metrics."""
        now_utc = datetime.now(timezone.utc).isoformat()
        uptime = time.monotonic() - self.start_time

        cpu_usage = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory()
        ram_used_mb = mem.used / (1024 * 1024)

        usage = shutil.disk_usage(self.settings.data_dir)
        disk_free_pct = (usage.free / float(usage.total)) * 100.0

        # Hardware temperature probing (platform dependent)
        cpu_temp = None
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                for name, entries in temps.items():
                    if entries:
                        cpu_temp = entries[0].current
                        break
        except Exception:
            cpu_temp = None

        pipeline_info = {}
        if self.pipeline_status_getter:
            try:
                pipeline_info = self.pipeline_status_getter()
            except Exception:
                pass

        payload = {
            "site_id": self.settings.site_id,
            "timestamp": now_utc,
            "system": {
                "uptime_sec": round(uptime, 1),
                "cpu_usage_pct": cpu_usage,
                "cpu_temp_c": cpu_temp,
                "ram_used_mb": round(ram_used_mb, 1),
                "disk_free_pct": round(disk_free_pct, 1)
            },
            "pipeline": pipeline_info
        }
        return payload

    def record_and_dispatch(self, payload: Dict[str, Any]):
        # 1. Log to local SQLite telemetry table
        sys_data = payload["system"]
        pipe_data = payload.get("pipeline", {})

        sql = """
        INSERT INTO telemetry_log (
            timestamp_utc, cpu_usage, ram_used_mb, disk_free_pct, active_cameras, queue_depth
        ) VALUES (?, ?, ?, ?, ?, ?)
        """
        params = (
            payload["timestamp"],
            sys_data["cpu_usage_pct"],
            sys_data["ram_used_mb"],
            sys_data["disk_free_pct"],
            pipe_data.get("active_cameras", 0),
            pipe_data.get("queue_depth", 0)
        )
        self.db.writer.queue.put((sql, params, None))

        # 2. Transmit to remote cloud webhook if configured
        if self.settings.cloud_webhook_url:
            headers = {"Content-Type": "application/json"}
            if self.settings.cloud_auth_token:
                headers["Authorization"] = f"Bearer {self.settings.cloud_auth_token}"

            try:
                resp = requests.post(
                    f"{self.settings.cloud_webhook_url}/api/v1/telemetry/heartbeat",
                    json=payload,
                    headers=headers,
                    timeout=5.0
                )
                if resp.status_code == 200:
                    logger.debug("Successfully transmitted cloud telemetry heartbeat.")
                else:
                    logger.warning(f"Cloud heartbeat returned status {resp.status_code}")
            except Exception as e:
                logger.debug(f"Cloud webhook ping skipped/failed: {e}")

    def stop(self):
        self.running = False

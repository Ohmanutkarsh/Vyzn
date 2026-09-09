"""
Alert routing and deduplication engine.
"""

from __future__ import annotations
import time
import logging
from typing import Dict, Optional
from vyzn.alerts.base import AlertProvider
from vyzn.core.events import EventRecord

logger = logging.getLogger("vyzn.alerts.dispatcher")


class AlertDispatcher:
    """
    Coordinates alert delivery to provider with per-camera rate limiting and deduplication.
    """

    def __init__(
        self,
        provider: AlertProvider,
        cooldown_sec: float = 45.0
    ):
        self.provider = provider
        self.cooldown_sec = cooldown_sec
        self._last_alert_time: Dict[str, float] = {}

    def dispatch(
        self,
        event: EventRecord,
        video_path: str,
        thumb_path: str,
        force: bool = False
    ) -> bool:
        now = time.monotonic()
        cam_id = event.camera_id

        # Deduplication check
        last_sent = self._last_alert_time.get(cam_id, 0.0)
        if not force and (now - last_sent < self.cooldown_sec):
            logger.info(
                f"Alert suppressed for {cam_id}: cooldown active ({now - last_sent:.1f}s < {self.cooldown_sec}s)"
            )
            return False

        success = self.provider.send_alert(event, video_path, thumb_path)
        if success:
            self._last_alert_time[cam_id] = now
            logger.info(f"Delivered high-confidence alert for camera {cam_id} (Score: {event.score})")
        return success

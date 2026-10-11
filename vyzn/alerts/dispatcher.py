"""
Alert routing, rate limiting, and governance engine.
Implements cooldown (60s), hourly limits (6/cam/hr), and critical threshold bypass (>= 85).
"""

from __future__ import annotations
import time
import logging
from collections import deque
from typing import Dict, Optional
from vyzn.alerts.base import AlertProvider
from vyzn.core.events import EventRecord
from vyzn.core.config import get_scoring_config

logger = logging.getLogger("vyzn.alerts.dispatcher")


class AlertDispatcher:
    """
    Coordinates alert delivery to provider with per-camera rate limiting and governance.
    Critical alerts (score >= 85) bypass cooldown and hourly throttling.
    """

    def __init__(
        self,
        provider: AlertProvider,
        cooldown_sec: Optional[float] = None,
        max_alerts_per_hour: Optional[int] = None,
        critical_bypass_threshold: Optional[int] = None
    ):
        self.provider = provider
        cfg = get_scoring_config().get("governance", {})
        self.cooldown_sec = cooldown_sec if cooldown_sec is not None else float(cfg.get("cooldown_sec", 60.0))
        self.max_alerts_per_hour = max_alerts_per_hour if max_alerts_per_hour is not None else int(cfg.get("max_alerts_per_camera_per_hour", 6))
        self.critical_bypass_threshold = critical_bypass_threshold if critical_bypass_threshold is not None else int(cfg.get("critical_bypass_threshold", 85))

        self._last_alert_time: Dict[str, float] = {}
        self._hourly_history: Dict[str, deque] = {}

    def dispatch(
        self,
        event: EventRecord,
        video_path: str,
        thumb_path: str,
        force: bool = False
    ) -> bool:
        now = time.monotonic()
        cam_id = event.camera_id
        score = getattr(event, "score", 0)

        # Critical bypass rule: score >= critical_bypass_threshold bypasses cooldown and hourly rate limit
        is_critical = (score >= self.critical_bypass_threshold)

        if not force and not is_critical:
            # 1. Cooldown check
            last_sent = self._last_alert_time.get(cam_id, 0.0)
            if now - last_sent < self.cooldown_sec:
                logger.info(
                    f"Alert suppressed for {cam_id}: cooldown active ({now - last_sent:.1f}s < {self.cooldown_sec}s, Score: {score})"
                )
                return False

            # 2. Max alerts per camera per hour check
            history = self._hourly_history.setdefault(cam_id, deque())
            while history and (now - history[0]) > 3600.0:
                history.popleft()

            if len(history) >= self.max_alerts_per_hour:
                logger.warning(
                    f"Alert suppressed for {cam_id}: hourly rate limit reached ({len(history)}/{self.max_alerts_per_hour} alerts in last hour, Score: {score})"
                )
                return False

        success = self.provider.send_alert(event, video_path, thumb_path)
        if success:
            self._last_alert_time[cam_id] = now
            self._hourly_history.setdefault(cam_id, deque()).append(now)
            tag = "CRITICAL BYPASS " if is_critical else ""
            logger.info(f"Delivered {tag}alert for camera {cam_id} (Score: {score})")
        return success

"""
Dynamic Resource Governor for BYOD & Shared Host Hardware.
Ensures VYZN runs silently on a shopkeeper's billing PC (Windows 10/11 / Linux)
without causing CPU starvation or UI stutter during active business hours.
Dynamically modulates process priority, capture FPS, and inference throttling.
"""

from __future__ import annotations
import os
import sys
import time
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from vyzn.core.config import BusinessHours
from vyzn.scoring.engine import is_time_after_hours

logger = logging.getLogger("vyzn.core.governor")


class ResourceGovernor:
    """
    Manages process priority, thread throttling, and dynamic capture decimation
    based on shop business schedule and host CPU metrics.
    """

    def __init__(
        self,
        business_hours: Optional[BusinessHours] = None,
        day_fps: float = 1.0,
        night_fps: float = 4.0,
        max_cpu_pct: float = 75.0
    ):
        self.business_hours = business_hours or BusinessHours(enabled=True, start_hour=9, end_hour=21)
        self.day_fps = day_fps
        self.night_fps = night_fps
        self.max_cpu_pct = max_cpu_pct

        self._is_business_hours: bool = False
        self._current_target_fps: float = night_fps
        self._is_throttled: bool = False
        self._last_governor_check: float = 0.0

        # Attempt to set initial process priority
        self.update_governance(force=True)

    def is_after_hours(self, dt: Optional[datetime] = None) -> bool:
        target_dt = dt or datetime.now(timezone.utc)
        return is_time_after_hours(target_dt, self.business_hours)

    def get_effective_fps(self) -> float:
        """Returns the recommended capture FPS based on current armed state."""
        return self._current_target_fps

    def should_throttle_inference(self) -> bool:
        """Indicates whether inference loop should yield or decimate frames."""
        return self._is_throttled

    def update_governance(self, force: bool = False, dt: Optional[datetime] = None) -> Dict[str, Any]:
        """
        Periodically recalculates resource constraints and applies host OS priority adjustments.
        """
        now = time.monotonic()
        if not force and (now - self._last_governor_check) < 10.0:
            return self.get_state()

        self._last_governor_check = now
        after_hours = self.is_after_hours(dt)
        self._is_business_hours = not after_hours

        if self._is_business_hours:
            # Business hours: Shopkeeper is billing. Drop FPS and lower process priority
            self._current_target_fps = self.day_fps
            self._apply_os_priority(low_priority=True)
        else:
            # After hours: Shop is locked. Elevate FPS and priority to catch intruders
            self._current_target_fps = self.night_fps
            self._apply_os_priority(low_priority=False)

        return self.get_state()

    def _apply_os_priority(self, low_priority: bool):
        """Applies OS-level process priority tuning."""
        try:
            if sys.platform == "win32":
                import ctypes
                # SetPriorityClass Windows API
                # BELOW_NORMAL_PRIORITY_CLASS = 0x00004000, NORMAL = 0x00000020
                handle = ctypes.windll.kernel32.GetCurrentProcess()
                priority_class = 0x00004000 if low_priority else 0x00000020
                ctypes.windll.kernel32.SetPriorityClass(handle, priority_class)
            else:
                # POSIX nice level: +10 during day, 0 at night
                target_nice = 10 if low_priority else 0
                current_nice = os.nice(0)
                delta = target_nice - current_nice
                if delta != 0:
                    os.nice(delta)
        except Exception as e:
            logger.debug(f"Could not adjust host OS process priority: {e}")

    def get_state(self) -> Dict[str, Any]:
        return {
            "is_business_hours": self._is_business_hours,
            "target_fps": self._current_target_fps,
            "day_fps": self.day_fps,
            "night_fps": self.night_fps,
            "is_throttled": self._is_throttled,
            "governor_active": True
        }

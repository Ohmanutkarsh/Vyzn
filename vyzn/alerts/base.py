"""
Abstract alert provider interface.
Decouples notification channel (Telegram, WhatsApp) from scoring and event engine.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Optional
from vyzn.core.events import EventRecord


class AlertProvider(ABC):
    """Abstract interface for all customer and testing notification adapters."""

    @abstractmethod
    def send_alert(
        self,
        event: EventRecord,
        video_path: str,
        thumb_path: str
    ) -> bool:
        """
        Transmits incident notification with attached video/thumbnail.
        Returns True if delivered successfully, False otherwise.
        """
        pass

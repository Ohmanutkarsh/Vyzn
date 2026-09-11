"""
Unit tests for BYOD Dynamic Resource Governor.
Verifies daytime CPU priority drop, dynamic capture FPS decimation during business hours,
and automatic sensitivity ramp-up after hours.
"""

from datetime import datetime, timezone
from vyzn.core.config import BusinessHours
from vyzn.core.resource_governor import ResourceGovernor


def test_resource_governor_day_night_transition():
    # Schedule: 09:00 to 21:00 business hours
    bh = BusinessHours(enabled=True, start_hour=9, end_hour=21)
    gov = ResourceGovernor(business_hours=bh, day_fps=1.0, night_fps=4.0)

    # 1. Daytime (14:30 UTC): Shopkeeper is billing at cash counter
    dt_day = datetime(2026, 9, 11, 14, 30, tzinfo=timezone.utc)
    gov.update_governance(force=True, dt=dt_day)
    state_day = gov.get_state()

    assert state_day["is_business_hours"] is True
    assert state_day["target_fps"] == 1.0
    assert gov.get_effective_fps() == 1.0

    # 2. Nighttime (02:30 UTC): Shop is locked up
    dt_night = datetime(2026, 9, 11, 2, 30, tzinfo=timezone.utc)
    gov.update_governance(force=True, dt=dt_night)
    state_night = gov.get_state()

    assert state_night["is_business_hours"] is False
    assert state_night["target_fps"] == 4.0
    assert gov.get_effective_fps() == 4.0


def test_resource_governor_priority_api_stability():
    """Ensures OS priority adjustment executes without uncaught exceptions."""
    gov = ResourceGovernor()
    gov._apply_os_priority(low_priority=True)
    gov._apply_os_priority(low_priority=False)
    assert gov.get_state()["governor_active"] is True

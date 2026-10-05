"""
Tests for UI utility functions (formatWhen, formatLeft, escapeHtml).
Matches VYZN v1.1 Specification.
"""

from datetime import datetime, timezone
import time


def simulate_format_when(epoch_ms: int, now_ms: int) -> str:
    """Python reference implementation mirroring frontend/dashboard/utils.js formatWhen."""
    PRE_2020_MS = int(datetime(2020, 1, 1, tzinfo=timezone.utc).timestamp() * 1000)
    if epoch_ms is None or epoch_ms < PRE_2020_MS:
        return "Time unknown"

    diff_sec = (now_ms - epoch_ms) // 1000
    diff_min = diff_sec // 60

    if diff_sec < 60:
        return "Just now"
    if diff_min < 60:
        return f"{diff_min} min ago"

    # IST timezone offset (+5:30 = 19800 seconds)
    IST_OFFSET_MS = int(5.5 * 3600 * 1000)
    ev_dt = datetime.fromtimestamp((epoch_ms + IST_OFFSET_MS) / 1000.0, timezone.utc)
    now_dt = datetime.fromtimestamp((now_ms + IST_OFFSET_MS) / 1000.0, timezone.utc)

    hour = ev_dt.hour % 12 or 12
    am_pm = "am" if ev_dt.hour < 12 else "pm"
    time_str = f"{hour}:{ev_dt.minute:02d} {am_pm}"

    if ev_dt.date() == now_dt.date():
        return f"Today, {time_str}"
    
    from datetime import timedelta
    if ev_dt.date() == (now_dt.date() - timedelta(days=1)):
        return f"Yesterday, {time_str}"

    return f"{ev_dt.strftime('%a %d %b')}, {time_str}"


def simulate_format_left(expires_at_ms: int, now_ms: int) -> str:
    """Python reference mirroring frontend/dashboard/utils.js formatLeft."""
    if not expires_at_ms or expires_at_ms <= now_ms:
        return "Deleting now"

    rem_min = (expires_at_ms - now_ms) // (60 * 1000)
    rem_h = rem_min // 60
    leftover_min = rem_min % 60

    if rem_h >= 24:
        return f"{rem_h} h"
    if rem_h > 0:
        return f"{rem_h} h" if leftover_min == 0 else f"{rem_h} h {leftover_min} min"
    return f"{rem_min} min"


def simulate_escape_html(s: str) -> str:
    if not s:
        return ""
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;")
             .replace("'", "&#39;"))


def test_format_when_relative_and_absolute():
    now_ms = int(datetime(2026, 9, 30, 21, 34, 0, tzinfo=timezone.utc).timestamp() * 1000)

    # 1. Under 1 hour
    assert simulate_format_when(now_ms - 12 * 60 * 1000, now_ms) == "12 min ago"
    assert simulate_format_when(now_ms - 30 * 1000, now_ms) == "Just now"

    # 2. Null, zero, or pre-2020 guard
    assert simulate_format_when(None, now_ms) == "Time unknown"
    assert simulate_format_when(0, now_ms) == "Time unknown"
    assert simulate_format_when(80000 * 1000, now_ms) == "Time unknown"  # 1970 timestamp

    # 3. Same day, previous day
    assert "Today" in simulate_format_when(now_ms - 3 * 3600 * 1000, now_ms)
    assert "Yesterday" in simulate_format_when(now_ms - 26 * 3600 * 1000, now_ms)


def test_format_left_retention():
    now_ms = 1790700000000
    assert simulate_format_left(now_ms + 41 * 3600 * 1000, now_ms) == "41 h"
    assert simulate_format_left(now_ms + 5 * 3600 * 1000 + 20 * 60 * 1000, now_ms) == "5 h 20 min"
    assert simulate_format_left(now_ms + 12 * 60 * 1000, now_ms) == "12 min"
    assert simulate_format_left(now_ms - 1000, now_ms) == "Deleting now"


def test_escape_html_security():
    assert simulate_escape_html('<script>alert("xss")</script>') == '&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;'
    assert simulate_escape_html("Shop's Cash Counter & Shutter") == 'Shop&#39;s Cash Counter &amp; Shutter'

"""
Tests for vyzn_cloud backend service, Dead-Man Watchdog, and WhatsApp webhook handling.
"""

from starlette.testclient import TestClient
from vyzn_cloud.app import cloud_app
from vyzn_cloud.watchdog import DeadManWatchdog


def test_dead_man_watchdog_detects_silence():
    # Set tight 0.5s silence threshold for test
    dog = DeadManWatchdog(silence_threshold_sec=0.2)
    dog.record_heartbeat("site_01", {"timestamp": "2026-09-10T12:00:00Z"})

    # Immediately after heartbeat, site is ONLINE
    sites = dog.get_all_sites()
    assert len(sites) == 1
    assert sites[0]["status"] == "ONLINE"

    # Wait for silence to exceed threshold
    import time
    time.sleep(0.3)

    # Watchdog should detect site has gone offline
    alerts = dog.evaluate_sites()
    assert len(alerts) == 1
    assert alerts[0]["site_id"] == "site_01"
    assert "SITE DOWN ALERT" in alerts[0]["message"]


def test_cloud_webhook_heartbeat_and_triage():
    client = TestClient(cloud_app)

    # 1. Test Ingest Telemetry Heartbeat
    heartbeat_payload = {
        "site_id": "site_nagpur_kirana_02",
        "timestamp": "2026-09-10T15:00:00Z",
        "system": {
            "uptime_sec": 3600,
            "cpu_usage_pct": 28.5,
            "ram_used_mb": 1100,
            "disk_free_pct": 74.0
        },
        "pipeline": {
            "active_cameras": 3,
            "queue_depth": 0
        }
    }
    res = client.post("/api/v1/telemetry/heartbeat", json=heartbeat_payload)
    assert res.status_code == 200
    assert res.json()["status"] == "acknowledged"

    # 2. Test Fleet Sites Status
    res = client.get("/api/v1/sites")
    assert res.status_code == 200
    sites = res.json()
    assert any(s["site_id"] == "site_nagpur_kirana_02" for s in sites)

    # 3. Test WhatsApp Webhook Verification Challenge
    params = {
        "hub.mode": "subscribe",
        "hub.verify_token": "vyzn_secure_webhook_token_2026",
        "hub.challenge": "1123581321"
    }
    res = client.get("/webhook/whatsapp", params=params)
    assert res.status_code == 200
    assert res.text == "1123581321"

    # 4. Test WhatsApp Interactive Reply Callback
    webhook_callback = {
        "entry": [{
            "changes": [{
                "value": {
                    "messages": [{
                        "from": "919876543210",
                        "type": "interactive",
                        "interactive": {
                            "button_reply": {
                                "id": "star_ev_001",
                                "title": "⭐ Star Clip"
                            }
                        }
                    }]
                }
            }]
        }]
    }
    res = client.post("/webhook/whatsapp", json=webhook_callback)
    assert res.status_code == 200
    assert res.json()["status"] == "processed"

    # 5. Check Triage Log Recorded
    res = client.get("/api/v1/triage-log")
    assert res.status_code == 200
    logs = res.json()
    assert len(logs) >= 1
    assert logs[-1]["button_id"] == "star_ev_001"

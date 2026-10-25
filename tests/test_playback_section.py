import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from api.index import app as vercel_app
from vyzn.api.routes import app as edge_app

def test_overview_page_is_clean_and_untouched():
    """Verify overview page is restored to standard live camera view with no timeshift mount."""
    overview_html = Path("public/overview.html").read_text(encoding="utf-8")
    assert "overview-live-player-mount" not in overview_html
    assert "live-player-frame" in overview_html
    assert "live-stream-img" in overview_html

    overview_js = Path("public/overview.js").read_text(encoding="utf-8")
    assert "mountLiveCctvPlayer" not in overview_js

def test_playback_page_structure():
    """Verify playback.html exists and includes Timeshift layout and scripts."""
    playback_html = Path("public/playback.html").read_text(encoding="utf-8")
    assert "Playback & Timeshift" in playback_html
    assert "playback-player-mount" in playback_html
    assert "playback-cameras-list" in playback_html
    assert "/static/playback.js" in playback_html

    playback_js = Path("public/playback.js").read_text(encoding="utf-8")
    assert "mountLiveCctvPlayer" in playback_js
    assert "checkEdgeServer" in playback_js

def test_shell_navigation_includes_playback():
    """Verify shell.js navigation lists Playback item."""
    shell_js = Path("public/components/shell.js").read_text(encoding="utf-8")
    assert "{ id: 'playback', href: '/playback', label: 'Playback'" in shell_js

def test_vercel_playback_route():
    """Test Vercel FastAPI endpoint /playback."""
    client = TestClient(vercel_app)
    resp = client.get("/playback")
    assert resp.status_code == 200
    assert "Playback & Timeshift" in resp.text

def test_edge_playback_route():
    """Test local Edge FastAPI endpoint /playback."""
    client = TestClient(edge_app)
    resp = client.get("/playback")
    assert resp.status_code == 200
    assert "Playback & Timeshift" in resp.text

def test_forward_10s_button_in_player():
    """Verify live-player.js includes forward 10s button and seek handler."""
    player_js = Path("public/components/live-player.js").read_text(encoding="utf-8")
    assert "cctv-btn-forward-10" in player_js
    assert "⏩ 10s" in player_js
    assert "seekRelative(+10)" in player_js

def test_landing_page_start_vyzn_button():
    """Verify landing page has Start VYZN button sending users to /login."""
    index_html = Path("public/index.html").read_text(encoding="utf-8")
    assert "Start VYZN" in index_html
    assert 'href="/login">Start VYZN</a>' in index_html
    assert "Book a demo" not in index_html

def test_cloud_live_streaming_endpoints():
    """Verify Vercel cloud live streaming endpoints return 200."""
    client = TestClient(vercel_app)
    r1 = client.get("/api/v1/cameras/cam_81559/live/live.m3u8")
    assert r1.status_code == 200
    assert "EXTM3U" in r1.text

    r2 = client.get("/api/v1/cameras/cam_81559/live/init.mp4")
    assert r2.status_code == 200

    r3 = client.get("/api/v1/cameras/cam_81559/live/range")
    assert r3.status_code == 200
    assert r3.json().get("is_live") is True

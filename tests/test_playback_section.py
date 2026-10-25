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

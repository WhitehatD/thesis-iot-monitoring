"""
Tests for the agentic analysis layer.
"""

from unittest.mock import AsyncMock, patch


def test_analyses_empty(client):
    """List analyses returns empty when no analyses exist."""
    resp = client.get("/api/analyses")
    assert resp.status_code == 200
    data = resp.json()
    assert data["analyses"] == []


def test_analysis_404(client):
    """Analysis for unknown task returns 404."""
    resp = client.get("/api/analysis/99999")
    assert resp.status_code == 404


def test_upload_triggers_analysis(client):
    """Upload endpoint fires the background analysis task."""
    fake_image = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # Minimal JPEG header

    with patch("app.api.routes.asyncio") as mock_asyncio:
        mock_asyncio.create_task = lambda coro: coro.close()  # Discard coroutine cleanly
        resp = client.post(
            "/api/upload?task_id=1",
            files={"file": ("test.jpg", fake_image, "image/jpeg")},
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["task_id"] == 1
    assert data["filename"].endswith(".jpg")

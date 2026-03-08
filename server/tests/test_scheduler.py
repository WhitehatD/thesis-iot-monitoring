"""
Thesis IoT Server — Scheduler Tests
CRUD + activation tests for the monitoring scheduler.
"""

import json
import pytest


# ══════════════════════════════════════════════════════════════════════════════
#  Create
# ══════════════════════════════════════════════════════════════════════════════

def test_create_schedule(client):
    """POST /api/schedules should create a schedule with tasks."""
    resp = client.post(
        "/api/schedules",
        json={
            "name": "Morning Patrol",
            "description": "Check the parking lot every hour",
            "tasks": [
                {"time": "08:00", "action": "CAPTURE_IMAGE", "objective": "Check entry gate"},
                {"time": "09:00", "action": "CAPTURE_IMAGE", "objective": "Check lot occupancy"},
                {"time": "10:00", "action": "STATUS_REPORT", "objective": ""},
            ],
        },
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "Morning Patrol"
    assert data["description"] == "Check the parking lot every hour"
    assert data["is_active"] is False
    assert len(data["tasks"]) == 3
    assert data["tasks"][0]["time"] == "08:00"
    assert data["tasks"][1]["objective"] == "Check lot occupancy"
    assert data["tasks"][2]["action"] == "STATUS_REPORT"


def test_create_schedule_requires_tasks(client):
    """POST /api/schedules should reject empty task list."""
    resp = client.post(
        "/api/schedules",
        json={"name": "Empty", "tasks": []},
    )
    assert resp.status_code == 422


def test_create_schedule_requires_name(client):
    """POST /api/schedules should reject missing name."""
    resp = client.post(
        "/api/schedules",
        json={"tasks": [{"time": "12:00"}]},
    )
    assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
#  List / Get
# ══════════════════════════════════════════════════════════════════════════════

def test_list_schedules(client):
    """GET /api/schedules should return all schedules."""
    # Create two schedules
    client.post("/api/schedules", json={
        "name": "Schedule A",
        "tasks": [{"time": "08:00"}],
    })
    client.post("/api/schedules", json={
        "name": "Schedule B",
        "tasks": [{"time": "12:00"}, {"time": "14:00"}],
    })

    resp = client.get("/api/schedules")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["schedules"]) >= 2

    names = [s["name"] for s in data["schedules"]]
    assert "Schedule A" in names
    assert "Schedule B" in names


def test_get_schedule(client):
    """GET /api/schedules/{id} should return the schedule with tasks."""
    create_resp = client.post("/api/schedules", json={
        "name": "Detail Test",
        "tasks": [{"time": "15:00", "objective": "Afternoon check"}],
    })
    schedule_id = create_resp.json()["id"]

    resp = client.get(f"/api/schedules/{schedule_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "Detail Test"
    assert len(data["tasks"]) == 1
    assert data["tasks"][0]["objective"] == "Afternoon check"


def test_get_schedule_404(client):
    """GET /api/schedules/{id} should return 404 for non-existent schedule."""
    resp = client.get("/api/schedules/99999")
    assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  Update
# ══════════════════════════════════════════════════════════════════════════════

def test_update_schedule(client):
    """PUT /api/schedules/{id} should replace name, description, and tasks."""
    create_resp = client.post("/api/schedules", json={
        "name": "Before Update",
        "tasks": [{"time": "08:00"}],
    })
    schedule_id = create_resp.json()["id"]

    resp = client.put(
        f"/api/schedules/{schedule_id}",
        json={
            "name": "After Update",
            "description": "Updated description",
            "tasks": [
                {"time": "10:00", "objective": "New task 1"},
                {"time": "11:00", "objective": "New task 2"},
            ],
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["name"] == "After Update"
    assert data["description"] == "Updated description"
    assert len(data["tasks"]) == 2


# ══════════════════════════════════════════════════════════════════════════════
#  Delete
# ══════════════════════════════════════════════════════════════════════════════

def test_delete_schedule(client):
    """DELETE /api/schedules/{id} should remove the schedule."""
    create_resp = client.post("/api/schedules", json={
        "name": "To Delete",
        "tasks": [{"time": "08:00"}],
    })
    schedule_id = create_resp.json()["id"]

    resp = client.delete(f"/api/schedules/{schedule_id}")
    assert resp.status_code == 204

    # Verify it's gone
    get_resp = client.get(f"/api/schedules/{schedule_id}")
    assert get_resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
#  Activate
# ══════════════════════════════════════════════════════════════════════════════

def test_activate_schedule(client):
    """POST /api/schedules/{id}/activate should mark schedule as active and publish MQTT."""
    mock_mqtt = client._mock_mqtt
    mock_mqtt.publish.reset_mock()

    create_resp = client.post("/api/schedules", json={
        "name": "To Activate",
        "tasks": [{"time": "08:00", "objective": "Morning check"}],
    })
    schedule_id = create_resp.json()["id"]

    resp = client.post(f"/api/schedules/{schedule_id}/activate")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "activated"
    assert data["schedule_id"] == schedule_id

    # Verify MQTT was called
    mock_mqtt.publish.assert_called_once()
    call_args = mock_mqtt.publish.call_args
    topic = call_args[0][0]
    payload = json.loads(call_args[0][1])

    assert topic == "device/stm32/commands"
    assert payload["type"] == "schedule"
    assert len(payload["tasks"]) == 1
    assert payload["tasks"][0]["objective"] == "Morning check"


def test_activate_deactivates_others(client):
    """Activating one schedule should deactivate all others."""
    # Create two schedules
    r1 = client.post("/api/schedules", json={
        "name": "First", "tasks": [{"time": "08:00"}],
    })
    r2 = client.post("/api/schedules", json={
        "name": "Second", "tasks": [{"time": "12:00"}],
    })
    id1, id2 = r1.json()["id"], r2.json()["id"]

    # Activate first
    client.post(f"/api/schedules/{id1}/activate")
    data1 = client.get(f"/api/schedules/{id1}").json()
    assert data1["is_active"] is True

    # Activate second — first should become inactive
    client.post(f"/api/schedules/{id2}/activate")
    data1 = client.get(f"/api/schedules/{id1}").json()
    data2 = client.get(f"/api/schedules/{id2}").json()
    assert data1["is_active"] is False
    assert data2["is_active"] is True

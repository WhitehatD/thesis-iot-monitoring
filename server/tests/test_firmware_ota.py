"""
Thesis IoT Server — Firmware OTA Endpoint Tests

Tests for the firmware OTA management endpoints:
  GET  /api/firmware/version   → version metadata
  GET  /api/firmware/download  → binary download
  POST /api/firmware/upload    → authenticated binary upload

Run: python -m pytest tests/test_firmware_ota.py -v
"""

import io
import json
import struct
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ══════════════════════════════════════════════════════════════════════════════
#  Version Endpoint
# ══════════════════════════════════════════════════════════════════════════════

def test_firmware_version_no_firmware(client):
    """GET /api/firmware/version should return 404 if no firmware uploaded."""
    with patch("app.api.firmware_routes.FIRMWARE_META", Path("/nonexistent/meta.json")), \
         patch("app.api.firmware_routes.FIRMWARE_BIN", Path("/nonexistent/fw.bin")):
        resp = client.get("/api/firmware/version")
        assert resp.status_code == 404


def test_firmware_version_with_firmware(client, tmp_path):
    """GET /api/firmware/version should return metadata after upload."""
    # Create a fake firmware binary and metadata
    fw_bin = tmp_path / "firmware.bin"
    fw_meta = tmp_path / "firmware.json"
    fw_data = b"\x00" * 1024
    fw_bin.write_bytes(fw_data)
    fw_meta.write_text(json.dumps({
        "version": "0.3",
        "size": len(fw_data),
        "crc32": 12345678,
        "filename": "firmware.bin",
    }))

    with patch("app.api.firmware_routes.FIRMWARE_BIN", fw_bin), \
         patch("app.api.firmware_routes.FIRMWARE_META", fw_meta):
        resp = client.get("/api/firmware/version")
        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "0.3"
        assert data["size"] == 1024
        assert data["crc32"] == 12345678


# ══════════════════════════════════════════════════════════════════════════════
#  Download Endpoint
# ══════════════════════════════════════════════════════════════════════════════

def test_firmware_download_no_firmware(client):
    """GET /api/firmware/download should return 404 if no binary exists."""
    with patch("app.api.firmware_routes.FIRMWARE_BIN", Path("/nonexistent/fw.bin")):
        resp = client.get("/api/firmware/download")
        assert resp.status_code == 404


def test_firmware_download_with_firmware(client, tmp_path):
    """GET /api/firmware/download should stream the binary file."""
    fw_bin = tmp_path / "firmware.bin"
    fw_data = b"\xDE\xAD\xBE\xEF" * 256  # 1 KB test binary
    fw_bin.write_bytes(fw_data)

    with patch("app.api.firmware_routes.FIRMWARE_BIN", fw_bin):
        resp = client.get("/api/firmware/download")
        assert resp.status_code == 200
        assert len(resp.content) == len(fw_data)
        assert resp.content[:4] == b"\xDE\xAD\xBE\xEF"


# ══════════════════════════════════════════════════════════════════════════════
#  Upload Endpoint
# ══════════════════════════════════════════════════════════════════════════════

def test_firmware_upload(client, tmp_path):
    """POST /api/firmware/upload should save binary and return metadata."""
    fw_dir = tmp_path / "firmware"
    fw_bin = fw_dir / "firmware.bin"
    fw_meta = fw_dir / "firmware.json"

    with patch("app.api.firmware_routes.FIRMWARE_DIR", fw_dir), \
         patch("app.api.firmware_routes.FIRMWARE_BIN", fw_bin), \
         patch("app.api.firmware_routes.FIRMWARE_META", fw_meta), \
         patch("app.api.firmware_routes.settings") as mock_settings:
        mock_settings.firmware_upload_token = ""  # No auth required
        mock_settings.mqtt_topic_commands = "device/stm32/commands"

        test_binary = b"\x08\x00\x00\x20" * 100  # 400 bytes fake firmware
        resp = client.post(
            "/api/firmware/upload",
            params={"version": "0.3"},
            files={"file": ("firmware.bin", io.BytesIO(test_binary), "application/octet-stream")},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["version"] == "0.3"
        assert data["size"] == len(test_binary)
        assert data["status"] == "uploaded"
        assert data["crc32"] > 0

        # Verify binary was saved to disk
        assert fw_bin.exists()
        assert fw_bin.read_bytes() == test_binary

        # Verify metadata was saved
        assert fw_meta.exists()
        meta = json.loads(fw_meta.read_text())
        assert meta["version"] == "0.3"


def test_firmware_upload_auth_required(client, tmp_path):
    """POST /api/firmware/upload should reject unauthenticated uploads when token is set."""
    fw_dir = tmp_path / "firmware"

    with patch("app.api.firmware_routes.FIRMWARE_DIR", fw_dir), \
         patch("app.api.firmware_routes.settings") as mock_settings:
        mock_settings.firmware_upload_token = "secret-ci-token-2026"

        resp = client.post(
            "/api/firmware/upload",
            params={"version": "0.3"},
            files={"file": ("firmware.bin", io.BytesIO(b"\x00" * 100), "application/octet-stream")},
        )
        assert resp.status_code == 403


def test_firmware_upload_auth_valid(client, tmp_path):
    """POST /api/firmware/upload should accept valid auth token."""
    fw_dir = tmp_path / "firmware"
    fw_bin = fw_dir / "firmware.bin"
    fw_meta = fw_dir / "firmware.json"

    with patch("app.api.firmware_routes.FIRMWARE_DIR", fw_dir), \
         patch("app.api.firmware_routes.FIRMWARE_BIN", fw_bin), \
         patch("app.api.firmware_routes.FIRMWARE_META", fw_meta), \
         patch("app.api.firmware_routes.settings") as mock_settings:
        mock_settings.firmware_upload_token = "secret-ci-token-2026"
        mock_settings.mqtt_topic_commands = "device/stm32/commands"

        resp = client.post(
            "/api/firmware/upload",
            params={"version": "0.4"},
            files={"file": ("firmware.bin", io.BytesIO(b"\xAB" * 200), "application/octet-stream")},
            headers={"X-Firmware-Token": "secret-ci-token-2026"},
        )
        assert resp.status_code == 200
        assert resp.json()["version"] == "0.4"


def test_firmware_upload_empty_binary(client, tmp_path):
    """POST /api/firmware/upload should reject empty files."""
    with patch("app.api.firmware_routes.settings") as mock_settings:
        mock_settings.firmware_upload_token = ""

        resp = client.post(
            "/api/firmware/upload",
            params={"version": "0.3"},
            files={"file": ("firmware.bin", io.BytesIO(b""), "application/octet-stream")},
        )
        assert resp.status_code == 400


def test_firmware_upload_publishes_mqtt(client, tmp_path):
    """POST /api/firmware/upload should publish a firmware_update command to MQTT."""
    fw_dir = tmp_path / "firmware"
    fw_bin = fw_dir / "firmware.bin"
    fw_meta = fw_dir / "firmware.json"
    mock_mqtt = client._mock_mqtt

    with patch("app.api.firmware_routes.FIRMWARE_DIR", fw_dir), \
         patch("app.api.firmware_routes.FIRMWARE_BIN", fw_bin), \
         patch("app.api.firmware_routes.FIRMWARE_META", fw_meta), \
         patch("app.api.firmware_routes.settings") as mock_settings:
        mock_settings.firmware_upload_token = ""
        mock_settings.mqtt_topic_commands = "device/stm32/commands"

        mock_mqtt.publish.reset_mock()

        resp = client.post(
            "/api/firmware/upload",
            params={"version": "0.5"},
            files={"file": ("firmware.bin", io.BytesIO(b"\xFF" * 500), "application/octet-stream")},
        )
        assert resp.status_code == 200

        # Verify MQTT was called
        mock_mqtt.publish.assert_called_once()
        call_args = mock_mqtt.publish.call_args
        topic = call_args[0][0]
        payload = json.loads(call_args[0][1])

        assert topic == "device/stm32/commands"
        assert payload["type"] == "firmware_update"
        assert payload["version"] == "0.5"
        assert payload["size"] == 500

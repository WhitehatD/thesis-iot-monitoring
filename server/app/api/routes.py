"""
Thesis IoT Server — API Routes
REST endpoints for planning, image upload, and result retrieval.
"""

import json
import os
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, File, UploadFile, HTTPException
from fastapi.responses import FileResponse

from app.config import settings
from app.api.schemas import (
    PlanRequest, PlanResponse, UploadResponse,
    CaptureRequest, CaptureResponse,
)
from app.mqtt.client import mqtt_client
from app.planning.engine import generate_plan

router = APIRouter()

_capture_counter = 0


@router.get("/time")
async def get_server_time():
    """
    Return the current server time for STM32 RTC synchronization.
    The board calls this once at boot to set its RTC before scheduling.
    """
    now = datetime.now()
    return {
        "hour": now.hour,
        "minute": now.minute,
        "second": now.second,
        "year": now.year % 100,  # RTC uses 2-digit year (26 = 2026)
        "month": now.month,
        "day": now.day,
        "weekday": now.isoweekday(),  # Monday=1..Sunday=7 (matches RTC_WEEKDAY_*)
    }


@router.post("/plan", response_model=PlanResponse)
async def create_plan(request: PlanRequest):
    """
    Accept a natural language prompt and generate an AI-powered task schedule.
    The schedule is also published to the STM32 board via MQTT.
    """
    # Generate schedule using the AI planning engine
    plan = await generate_plan(request.prompt, request.model)

    # Publish schedule to STM32 via MQTT
    schedule_json = json.dumps({"type": "schedule", "tasks": [t.model_dump() for t in plan.tasks]})
    await mqtt_client.publish(settings.mqtt_topic_commands, schedule_json)

    return plan


@router.post("/capture", response_model=CaptureResponse)
async def capture_now(request: CaptureRequest = CaptureRequest()):
    """
    Send an immediate capture command to the STM32 board.
    Sends a 'capture_now' command type — firmware executes instantly
    without going through the scheduler/RTC alarm flow.
    """
    global _capture_counter
    _capture_counter += 1

    command = {"type": "capture_now"}
    command_json = json.dumps(command)
    await mqtt_client.publish(settings.mqtt_topic_commands, command_json)

    return CaptureResponse(
        task_id=_capture_counter,
        status="sent",
        schedule_json=command_json,
    )

@router.post("/upload", response_model=UploadResponse)
async def upload_image(task_id: int, file: UploadFile = File(...)):
    """
    Receive a captured image from the STM32 board.
    The board sends raw RGB565 pixel data — we convert to JPEG server-side.
    """
    import io
    import struct
    import numpy as np
    from PIL import Image

    content = await file.read()

    if len(content) == 0:
        raise HTTPException(status_code=422, detail="Empty upload — no image data received")

    # Save image to disk
    date_dir = datetime.now().strftime("%Y-%m-%d")
    save_dir = os.path.join(settings.upload_dir, date_dir)
    os.makedirs(save_dir, exist_ok=True)

    filename = f"task_{task_id}_{int(time.time())}.jpg"
    filepath = os.path.join(save_dir, filename)

    # Detect raw RGB565 by expected frame sizes
    RGB565_SIZES = {
        640 * 480 * 2: (640, 480),   # VGA
        320 * 240 * 2: (320, 240),   # QVGA
    }

    try:
        if len(content) in RGB565_SIZES:
            width, height = RGB565_SIZES[len(content)]

            # OV5640 FORMAT_CTRL00=0x6F outputs BGR565 (little-endian):
            #   Byte0: B[4:0]G[5:3]  Byte1: G[2:0]R[4:0]
            # As LE uint16: bits[15:11]=Blue, bits[10:5]=Green, bits[4:0]=Red
            #
            # IMPORTANT: Do NOT cast to uint8 before scaling — uint8 * 255 overflows!
            pixels = np.frombuffer(content, dtype=np.uint16)
            b = (((pixels >> 11) & 0x1F).astype(np.uint16) * 255 // 31).astype(np.uint8)
            g = (((pixels >> 5) & 0x3F).astype(np.uint16) * 255 // 63).astype(np.uint8)
            r = ((pixels & 0x1F).astype(np.uint16) * 255 // 31).astype(np.uint8)

            rgb = np.stack([r, g, b], axis=-1).reshape(height, width, 3)
            img = Image.fromarray(rgb, "RGB")
            img.save(filepath, "JPEG", quality=85)
        else:
            # Assume already JPEG or other image format — validate it's readable
            try:
                img = Image.open(io.BytesIO(content))
                img.verify()  # Validate it's a real image
            except Exception:
                pass  # Save raw anyway — might be a valid format PIL doesn't verify well

            with open(filepath, "wb") as f:
                f.write(content)
    except Exception as e:
        print(f"✗ Upload processing failed for task {task_id}: {e} (content_len={len(content)})")
        raise HTTPException(
            status_code=422,
            detail=f"Image processing failed: {str(e)} (received {len(content)} bytes)"
        )

    # Notify dashboard via MQTT
    image_meta = {
        "task_id": task_id,
        "filename": filename,
        "date": date_dir,
        "url": f"/api/images/{date_dir}/{filename}",
        "timestamp": int(time.time()),
    }
    await mqtt_client.publish(
        settings.mqtt_topic_dashboard_images, json.dumps(image_meta)
    )

    return UploadResponse(
        task_id=task_id,
        filename=filename,
        analysis=None,
        recommendation=None,
    )


# ── Image Serving ────────────────────────────────────────

@router.get("/images")
async def list_images():
    """
    List all uploaded images, newest first.
    """
    upload_root = Path(settings.upload_dir)
    images = []

    if upload_root.exists():
        for date_dir in sorted(upload_root.iterdir(), reverse=True):
            if not date_dir.is_dir():
                continue
            for img_file in sorted(date_dir.iterdir(), reverse=True):
                if img_file.suffix.lower() in (".jpg", ".jpeg", ".png"):
                    # Extract task_id from filename: task_{id}_{ts}.jpg
                    parts = img_file.stem.split("_")
                    task_id = int(parts[1]) if len(parts) >= 2 else 0
                    images.append({
                        "filename": img_file.name,
                        "date": date_dir.name,
                        "task_id": task_id,
                        "url": f"/api/images/{date_dir.name}/{img_file.name}",
                        "timestamp": int(img_file.stat().st_mtime),
                    })

    return {"images": images}


@router.get("/images/{date}/{filename}")
async def serve_image(date: str, filename: str):
    """
    Serve an uploaded image file.
    """
    filepath = Path(settings.upload_dir) / date / filename
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    return FileResponse(filepath, media_type="image/jpeg")


# ── Plans & Results ──────────────────────────────────────

@router.get("/results/{plan_id}")
async def get_results(plan_id: int):
    """
    Retrieve analysis results for all tasks in a plan.
    """
    # TODO: Query database for results
    return {
        "plan_id": plan_id,
        "status": "pending",
        "results": [],
    }


@router.get("/plans")
async def list_plans():
    """
    List all created plans.
    """
    # TODO: Query database for plans
    return {"plans": []}

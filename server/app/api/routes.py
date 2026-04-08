"""
Thesis IoT Server — API Routes
REST endpoints for planning, image upload, visual analysis, and result retrieval.
"""

import asyncio
import json
import os
import time
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.api.schemas import (
    PlanRequest, PlanResponse, UploadResponse,
    CaptureRequest, CaptureResponse,
)
from app.analysis.engine import analyze_image
from app.analysis.models import AnalysisResult
from app.db.database import get_db, async_session
from app.mqtt.client import mqtt_client
from app.planning.engine import generate_plan
from app.scheduler.models import ScheduleTask

router = APIRouter()

_capture_counter = int(time.time())


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

    command = {"type": "capture_now", "task_id": _capture_counter}
    command_json = json.dumps(command)
    await mqtt_client.publish(settings.mqtt_topic_commands, command_json)

    return CaptureResponse(
        task_id=_capture_counter,
        status="sent",
        schedule_json=command_json,
    )

@router.post("/ping")
async def ping_board():
    """
    Send an immediate ping command to the STM32 board.
    Triggers the LED light sequence on the physical hardware.
    """
    command = {"type": "ping"}
    command_json = json.dumps(command)
    await mqtt_client.publish(settings.mqtt_topic_commands, command_json)

    return {
        "status": "sent",
        "command": "ping",
    }

@router.post("/erase-wifi")
async def erase_wifi():
    """
    Send an immediate erase_wifi command to the STM32 board.
    Forces the board to erase flash credentials and reboot into the captive portal.
    """
    command = {"type": "erase_wifi"}
    command_json = json.dumps(command)
    await mqtt_client.publish(settings.mqtt_topic_commands, command_json)

    return {
        "status": "sent",
        "command": "erase_wifi",
    }

@router.post("/upload", response_model=UploadResponse)
async def upload_image(task_id: int, file: UploadFile = File(...)):
    """
    Receive a captured image from the STM32 board.
    The board sends raw RGB565 pixel data — we convert to JPEG server-side.
    """
    global _capture_counter
    # Intercept board fallback task IDs (from unprompted/button captures) or 0
    if task_id == 0 or (10000 <= task_id <= 40000):
        _capture_counter += 1
        task_id = _capture_counter

    import io
    import struct
    import numpy as np
    from PIL import Image

    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail="Failed to read upload payload")

    if len(content) == 0:
        raise HTTPException(status_code=422, detail="Empty upload — no image data received")

    date_dir = datetime.now().strftime("%Y-%m-%d")
    save_dir = os.path.join(settings.upload_dir, date_dir)
    filename = f"task_{task_id}_{int(time.time())}.jpg"
    filepath = os.path.join(save_dir, filename)

    RGB565_SIZES = {
        640 * 480 * 2: (640, 480),   # VGA
        320 * 240 * 2: (320, 240),   # QVGA
    }

    try:
        # Save image to disk
        os.makedirs(save_dir, exist_ok=True)

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
        print(f"[ERR] Upload processing failed for task {task_id}: {e} (content_len={len(content)})")
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
    try:
        await mqtt_client.publish(
            settings.mqtt_topic_dashboard_images, json.dumps(image_meta)
        )
    except Exception as e:
        print(f"[WARN] Failed to publish MQTT message for dashboard: {e}")

    # ── Mark schedule task as completed ──
    try:
        async with async_session() as db:
            result = await db.execute(
                select(ScheduleTask).where(ScheduleTask.id == task_id)
            )
            task = result.scalar_one_or_none()
            if task and task.completed_at is None:
                task.completed_at = datetime.now()
                await db.commit()
                # Push real-time update to dashboard
                from app.scheduler.notify import notify_schedule_update
                await notify_schedule_update()
    except Exception:
        pass  # Non-critical — don't fail the upload

    # ── Agentic Layer: trigger async visual analysis ──
    asyncio.create_task(_run_analysis(task_id, filepath, date_dir, filename))

    return UploadResponse(
        task_id=task_id,
        filename=filename,
        analysis=None,
        recommendation=None,
    )


async def _run_analysis(task_id: int, image_path: str, date_dir: str, filename: str):
    """Background task: analyze a captured image with the multimodal LLM."""
    try:
        # Look up the monitoring objective from the schedule task
        objective = "General visual inspection"
        async with async_session() as db:
            result = await db.execute(
                select(ScheduleTask).where(ScheduleTask.id == task_id)
            )
            task = result.scalar_one_or_none()
            if task and task.objective:
                objective = task.objective

        print(f"[AI] Analyzing task {task_id}: objective='{objective}'")

        # Choose model — prefer Claude Sonnet, fall back to vLLM
        model_key = "claude-sonnet" if settings.anthropic_api_key else "qwen3-vl"

        analysis = await analyze_image(image_path, objective, model_key)

        # Persist to database
        async with async_session() as db:
            db_result = AnalysisResult(
                task_id=task_id,
                image_path=image_path,
                objective=objective,
                analysis=analysis.get("findings", ""),
                recommendation=analysis.get("recommendation", ""),
                model_used=analysis.get("model_used", model_key),
                inference_time_ms=analysis.get("inference_time_ms", 0),
            )
            db.add(db_result)
            await db.commit()

        # Publish analysis result to dashboard via MQTT
        analysis_msg = {
            "task_id": task_id,
            "filename": filename,
            "date": date_dir,
            "url": f"/api/images/{date_dir}/{filename}",
            "objective": objective,
            "objective_met": analysis.get("objective_met", False),
            "description": analysis.get("description", ""),
            "findings": analysis.get("findings", ""),
            "recommendation": analysis.get("recommendation", ""),
            "model": analysis.get("model_used", model_key),
            "inference_ms": analysis.get("inference_time_ms", 0),
            "timestamp": int(time.time()),
        }
        await mqtt_client.publish(settings.mqtt_topic_dashboard_analysis, json.dumps(analysis_msg))

        print(
            f"[AI] Analysis complete for task {task_id} "
            f"({analysis.get('inference_time_ms', 0):.0f}ms, {model_key}): "
            f"objective_met={analysis.get('objective_met')}"
        )

    except Exception as e:
        print(f"[ERR] Analysis failed for task {task_id}: {e}")


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


@router.delete("/images/{date}/{filename}")
async def delete_image(date: str, filename: str):
    """
    Delete an uploaded image file from the server.
    """
    filepath = Path(settings.upload_dir) / date / filename
    if not filepath.exists() or not filepath.is_file():
        raise HTTPException(status_code=404, detail="Image not found")
    
    try:
        os.remove(filepath)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to delete image: {str(e)}")
    
    return {"status": "success", "message": "Image deleted"}


# ── Plans & Results ──────────────────────────────────────

@router.get("/analysis/{task_id}")
async def get_analysis(task_id: int, db: AsyncSession = Depends(get_db)):
    """
    Retrieve the latest analysis result for a specific task.
    """
    result = await db.execute(
        select(AnalysisResult)
        .where(AnalysisResult.task_id == task_id)
        .order_by(AnalysisResult.created_at.desc())
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="No analysis found for this task")
    return {
        "task_id": analysis.task_id,
        "objective": analysis.objective,
        "analysis": analysis.analysis,
        "recommendation": analysis.recommendation,
        "model_used": analysis.model_used,
        "inference_time_ms": analysis.inference_time_ms,
        "created_at": analysis.created_at.isoformat() if analysis.created_at else None,
    }


@router.get("/analyses")
async def list_analyses(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """
    List recent analysis results, newest first.
    """
    result = await db.execute(
        select(AnalysisResult)
        .order_by(AnalysisResult.created_at.desc())
        .limit(limit)
    )
    analyses = result.scalars().all()
    return {
        "analyses": [
            {
                "id": a.id,
                "task_id": a.task_id,
                "objective": a.objective,
                "analysis": a.analysis,
                "recommendation": a.recommendation,
                "model_used": a.model_used,
                "inference_time_ms": a.inference_time_ms,
                "image_path": a.image_path,
                "created_at": a.created_at.isoformat() if a.created_at else None,
            }
            for a in analyses
        ]
    }

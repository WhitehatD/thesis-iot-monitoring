"""
Thesis IoT Server — API Routes
REST endpoints for planning, image upload, and result retrieval.
"""

import json
import time
from datetime import datetime

from fastapi import APIRouter, File, UploadFile, HTTPException

from app.config import settings
from app.api.schemas import PlanRequest, PlanResponse, UploadResponse
from app.mqtt.client import mqtt_client
from app.planning.engine import generate_plan

router = APIRouter()


@router.post("/plan", response_model=PlanResponse)
async def create_plan(request: PlanRequest):
    """
    Accept a natural language prompt and generate an AI-powered task schedule.
    The schedule is also published to the STM32 board via MQTT.
    """
    # Generate schedule using the AI planning engine
    plan = await generate_plan(request.prompt, request.model)

    # Publish schedule to STM32 via MQTT
    schedule_json = json.dumps({"tasks": [t.model_dump() for t in plan.tasks]})
    mqtt_client.publish(settings.mqtt_topic_commands, schedule_json)

    return plan


@router.post("/upload", response_model=UploadResponse)
async def upload_image(task_id: int, file: UploadFile = File(...)):
    """
    Receive a captured image from the STM32 board.
    Triggers visual analysis with the configured AI model.
    """
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    # Save image to disk
    import os
    date_dir = datetime.now().strftime("%Y-%m-%d")
    save_dir = os.path.join(settings.upload_dir, date_dir)
    os.makedirs(save_dir, exist_ok=True)

    filename = f"task_{task_id}_{int(time.time())}.jpg"
    filepath = os.path.join(save_dir, filename)

    content = await file.read()
    with open(filepath, "wb") as f:
        f.write(content)

    # TODO: Trigger async visual analysis with MLLM
    # analysis_result = await analyze_image(filepath, task_objective)

    return UploadResponse(
        task_id=task_id,
        filename=filename,
        analysis=None,  # Will be populated after analysis
        recommendation=None,
    )


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

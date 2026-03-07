"""
Thesis IoT Server — API Schemas
Pydantic models for request/response validation.
"""

from datetime import datetime
from pydantic import BaseModel, Field


# ── Planning ─────────────────────────────────────────────

class PlanRequest(BaseModel):
    """User prompt to be decomposed into a task schedule."""
    prompt: str = Field(
        ...,
        description="Natural language monitoring request",
        examples=["Monitor occupancy between 3-5 PM"],
    )
    model: str = Field(
        default="qwen3-vl",
        description="AI model backend: 'qwen3-vl', 'qwen2.5-vl', or 'gemini-3'",
    )


class ScheduledTask(BaseModel):
    """A single task in the generated schedule."""
    time: str = Field(..., description="ISO time for task execution, e.g. '15:00'")
    action: str = Field(default="CAPTURE_IMAGE", description="Action to perform")
    id: int = Field(..., description="Unique task ID")
    objective: str = Field(default="", description="Visual objective for analysis")


class PlanResponse(BaseModel):
    """AI-generated task schedule."""
    plan_id: int
    prompt: str
    tasks: list[ScheduledTask]
    model_used: str
    created_at: datetime


# ── Image Upload ─────────────────────────────────────────

class UploadResponse(BaseModel):
    """Response after image upload."""
    task_id: int
    filename: str
    analysis: str | None = None
    recommendation: str | None = None


# ── Results ──────────────────────────────────────────────

class TaskResult(BaseModel):
    """Analysis result for a completed task."""
    task_id: int
    plan_id: int
    image_path: str
    analysis: str
    recommendation: str
    model_used: str
    inference_time_ms: float
    created_at: datetime

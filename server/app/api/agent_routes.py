"""
Thesis IoT Server — Agentic Chat Endpoint (SSE)

Server-Sent Events endpoint that runs an agentic loop:
  1. Accepts a natural language monitoring request
  2. Streams thinking/planning steps as SSE events
  3. Calls the AI planning engine to generate a schedule
  4. Publishes the schedule to the STM32 board via MQTT
  5. Streams the final result back to the dashboard

SSE event types (matching faa-agent pattern):
  - thinking: AI reasoning text
  - tool_call: Agent is executing a tool (with spinner on frontend)
  - tool_result: Tool execution result (spinner → checkmark)
  - reply: Final markdown response
  - error: Something went wrong
  - done: Stream complete
"""

import json
import time
import uuid
from datetime import datetime

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.config import settings
from app.mqtt.client import mqtt_client
from app.planning.engine import generate_plan, _parse_schedule, PLANNING_SYSTEM_PROMPT

router = APIRouter(prefix="/agent", tags=["Agent"])

# Server-side session history (keyed by session_id)
_sessions: dict[str, list[dict]] = {}
_SESSION_MAX = 50  # Max messages per session


def _sse_event(event: str, data: dict) -> str:
    """Format a Server-Sent Event."""
    return f"data: {json.dumps({'event': event, **data})}\n\n"


@router.post("/chat")
async def agent_chat(request: Request):
    """
    Agentic chat endpoint — accepts a user message and streams
    the AI planning/analysis response as Server-Sent Events.
    """
    body = await request.json()
    message = body.get("message", "").strip()
    session_id = body.get("sessionId", str(uuid.uuid4()))

    if not message:
        return StreamingResponse(
            iter([_sse_event("error", {"text": "Empty message"})]),
            media_type="text/event-stream",
        )

    async def event_stream():
        try:
            # Initialize or retrieve session
            if session_id not in _sessions:
                _sessions[session_id] = []
            history = _sessions[session_id]

            # Add user message to history
            history.append({"role": "user", "content": message})

            # ── Step 1: Classify intent ──
            yield _sse_event("thinking", {
                "text": f"Understanding request: \"{message}\""
            })

            intent = _classify_intent(message)

            if intent == "schedule":
                async for event in _handle_schedule(message, session_id):
                    yield event
            elif intent == "capture":
                async for event in _handle_capture(message, session_id):
                    yield event
            elif intent == "analyze":
                async for event in _handle_analyze(message, session_id):
                    yield event
            elif intent == "status":
                async for event in _handle_status(message, session_id):
                    yield event
            else:
                async for event in _handle_general(message, session_id):
                    yield event

            yield _sse_event("done", {})

        except Exception as e:
            yield _sse_event("error", {"text": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _classify_intent(message: str) -> str:
    """Quick rule-based intent classification."""
    msg = message.lower()

    schedule_words = ["monitor", "schedule", "every", "between", "from", "until",
                      "watch", "check", "observe", "capture every", "take picture",
                      "photograph", "survey", "track"]
    capture_words = ["take a picture", "capture now", "snap", "photo now",
                     "take photo", "shoot"]
    analyze_words = ["analyze", "analysis", "what do you see", "describe",
                     "look at", "examine", "interpret", "last image",
                     "latest capture"]
    status_words = ["status", "online", "battery", "uptime", "health",
                    "how is", "is the board"]

    if any(w in msg for w in capture_words):
        return "capture"
    if any(w in msg for w in analyze_words):
        return "analyze"
    if any(w in msg for w in status_words):
        return "status"
    if any(w in msg for w in schedule_words):
        return "schedule"
    return "general"


async def _handle_schedule(message: str, session_id: str):
    """Generate a monitoring schedule from natural language."""

    # Step: Planning
    yield _sse_event("tool_call", {
        "id": "plan",
        "label": "Generating monitoring schedule with AI...",
    })

    model_key = "claude-sonnet" if settings.anthropic_api_key else "qwen3-vl"

    try:
        plan = await generate_plan(message, model_key)
    except Exception as e:
        yield _sse_event("tool_result", {
            "id": "plan",
            "success": False,
            "summary": f"Planning failed: {e}",
        })
        yield _sse_event("reply", {
            "text": f"I couldn't generate a schedule. The AI backend returned an error: {e}\n\nPlease check that the AI model is configured and running.",
        })
        return

    task_count = len(plan.tasks)
    times = [t.time for t in plan.tasks]

    yield _sse_event("tool_result", {
        "id": "plan",
        "success": True,
        "summary": f"Generated {task_count} tasks ({times[0]}–{times[-1]})" if times else "No tasks",
    })

    # Step: Publish to board
    yield _sse_event("tool_call", {
        "id": "mqtt",
        "label": "Publishing schedule to STM32 board via MQTT...",
    })

    schedule_payload = {
        "type": "schedule",
        "tasks": [t.model_dump() for t in plan.tasks],
    }
    schedule_json = json.dumps(schedule_payload)

    try:
        await mqtt_client.publish(settings.mqtt_topic_commands, schedule_json)
        yield _sse_event("tool_result", {
            "id": "mqtt",
            "success": True,
            "summary": f"Schedule sent to board ({task_count} tasks)",
        })
    except Exception as e:
        yield _sse_event("tool_result", {
            "id": "mqtt",
            "success": False,
            "summary": f"MQTT publish failed: {e}",
        })

    # Build reply
    task_list = "\n".join(
        f"| {t.id} | {t.time} | {t.action} | {t.objective} |"
        for t in plan.tasks
    )

    reply = (
        f"**Schedule created** — {task_count} capture tasks from {times[0]} to {times[-1]}.\n\n"
        f"| ID | Time | Action | Objective |\n"
        f"|---|---|---|---|\n"
        f"{task_list}\n\n"
        f"The schedule has been sent to the board. "
        f"It will capture images at the specified times and upload them for AI analysis.\n\n"
        f"*Model: {model_key}*"
    )

    # Store in session
    _sessions[session_id].append({"role": "assistant", "content": reply})

    yield _sse_event("reply", {"text": reply})


async def _handle_capture(message: str, session_id: str):
    """Send an immediate capture command."""

    yield _sse_event("tool_call", {
        "id": "capture",
        "label": "Sending capture command to STM32 board...",
    })

    task_id = int(time.time())
    command = json.dumps({"type": "capture_now", "task_id": task_id})

    try:
        await mqtt_client.publish(settings.mqtt_topic_commands, command)
        yield _sse_event("tool_result", {
            "id": "capture",
            "success": True,
            "summary": f"Capture command sent (task #{task_id})",
        })
    except Exception as e:
        yield _sse_event("tool_result", {
            "id": "capture",
            "success": False,
            "summary": f"Failed: {e}",
        })
        yield _sse_event("reply", {"text": f"Failed to send capture command: {e}"})
        return

    reply = (
        f"**Capture triggered** (task #{task_id})\n\n"
        f"The board will capture an image and upload it. "
        f"You'll see it appear in the gallery once uploaded and analyzed by the AI."
    )
    _sessions[session_id].append({"role": "assistant", "content": reply})
    yield _sse_event("reply", {"text": reply})


async def _handle_analyze(message: str, session_id: str):
    """Analyze the latest captured image."""
    from sqlalchemy import select
    from app.analysis.models import AnalysisResult
    from app.db.database import async_session

    yield _sse_event("tool_call", {
        "id": "fetch",
        "label": "Fetching latest analysis from database...",
    })

    async with async_session() as db:
        result = await db.execute(
            select(AnalysisResult)
            .order_by(AnalysisResult.created_at.desc())
            .limit(1)
        )
        analysis = result.scalar_one_or_none()

    if not analysis:
        yield _sse_event("tool_result", {
            "id": "fetch",
            "success": False,
            "summary": "No analyses found",
        })
        reply = "No image analyses found yet. Try capturing an image first."
        _sessions[session_id].append({"role": "assistant", "content": reply})
        yield _sse_event("reply", {"text": reply})
        return

    yield _sse_event("tool_result", {
        "id": "fetch",
        "success": True,
        "summary": f"Found analysis for task #{analysis.task_id}",
    })

    reply = (
        f"**Latest Analysis** (task #{analysis.task_id})\n\n"
        f"**Objective:** {analysis.objective}\n\n"
        f"**Findings:** {analysis.analysis}\n\n"
        f"**Recommendation:** {analysis.recommendation}\n\n"
        f"*Model: {analysis.model_used} | Inference: {analysis.inference_time_ms:.0f}ms*"
    )
    _sessions[session_id].append({"role": "assistant", "content": reply})
    yield _sse_event("reply", {"text": reply})


async def _handle_status(message: str, session_id: str):
    """Report board status from recent MQTT telemetry."""
    reply = (
        "**Board Status**\n\n"
        "The board's live status is shown in the telemetry panel on the left. "
        "Key indicators:\n\n"
        "- **Online/Offline** — based on MQTT heartbeats (every 5s)\n"
        "- **Firmware version** — current deployed version\n"
        "- **Total captures** — images captured this session\n\n"
        "You can also click **Ping Node** to verify the board is responsive."
    )
    _sessions[session_id].append({"role": "assistant", "content": reply})
    yield _sse_event("reply", {"text": reply})


async def _handle_general(message: str, session_id: str):
    """Handle general questions about the system."""
    reply = (
        "I'm the IoT Visual Monitoring Agent. I can help you with:\n\n"
        "- **Schedule monitoring** — *\"Monitor the room every 15 minutes from 9 AM to 5 PM\"*\n"
        "- **Capture images** — *\"Take a picture now\"*\n"
        "- **Analyze captures** — *\"What does the latest image show?\"*\n"
        "- **Check status** — *\"Is the board online?\"*\n\n"
        "Try giving me a natural language monitoring request!"
    )
    _sessions[session_id].append({"role": "assistant", "content": reply})
    yield _sse_event("reply", {"text": reply})
